#!/usr/bin/env python3

import sys
import os
import json
import errno
import argparse
import asyncio
import urllib.parse
from http import HTTPStatus

from jsonconfig import JSONConfig

from ahttp.ahttp import AsyncHttpRequest, AsyncHttpServer, AsyncHttpClient

DEF_CACHE_TIMEOUT = (1 * (60 * 60))
DEF_PORT = 8080
DEF_ADDR = "0.0.0.0"

OPEN_SEARCH_TEMPLATE = """
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>GSearch</ShortName>
  <Description>Search gsearch.com</Description>
  <Url type="text/html" method="get" template="https://__HOST__/search?q={searchTerms}"/>
  <Image width="16" height="16" type="image/x-icon">https://__HOST__/favicon.ico</Image>
  <InputEncoding>UTF-8</InputEncoding>
  <OutputEncoding>UTF-8</OutputEncoding>
</OpenSearchDescription>"""


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<25}{v}")


class ClientRequestHandler:
    def __init__(self, url: str, method: str = "GET") -> None:
        self.connections_lock = asyncio.Lock()
        self.connections: list[AsyncHttpClient] = []
        self.url = url

        if ("GET" == method):
            self.is_get = True
        else:
            self.is_get = False

    async def _pop_client_connection(self) -> AsyncHttpClient:

        async with self.connections_lock:
            if (len(self.connections) > 0):
                return self.connections.pop()
            else:
                client = AsyncHttpClient(self.url)
                await client.connect()
                return client

    async def _return_client_connection(self, client: AsyncHttpClient) -> None:

        async with self.connections_lock:
            self.connections.append(client)

    async def __aenter__(self) -> 'ClientRequestHandler':
        return self

    async def __aexit__(self, type, value, traceback) -> None:  # type: ignore
        await self.close()

    ############################################################################
    # PUBLIC
    ############################################################################
    async def issue_request(self, params: dict[str, str] = {}, headers: dict[str, str] = {},  data: bytes = b'', max_attempts: int = 5) -> bytes:

        url = self.url

        count = 0
        for k in params.keys():
            v = urllib.parse.quote(params[k])

            if (0 == count):
                url += f"?{k}={v}"
            else:
                url += f"&{k}={v}"

            count += 1

        resp_data = b''
        attempts = 0
        replied = False
        client = None

        while (False == replied and attempts < max_attempts):

            try:
                client = await self._pop_client_connection()

                for k in headers.keys():
                    client.add_header(k, headers[k])

                if (True == self.is_get):
                    resp = await client.get(url)
                else:
                    resp = await client.post(url, data=data)

                if (resp.status >= 200 and resp.status < 300):
                    resp_data = await resp.read_all()
                    replied = True
                else:
                    print(f"{url} returned {resp.status}")

            except ConnectionAbortedError:
                pass
            except ConnectionError:
                pass
            except Exception as e:
                print(f"Exception: {e}")
            finally:
                if (client is not None):
                    if (True == replied):
                        await self._return_client_connection(client)
                    else:
                        try:
                            await client.close()
                        except Exception as e:
                            print(f"Exception: {e}")

            attempts += 1
        return resp_data

    async def close(self) -> None:
        while self.connections:
            c = self.connections.pop()
            await c.close()


class AI(ClientRequestHandler):

    def __init__(self, config: JSONConfig) -> None:

        self.key = config.get("/openai/key")
        self.system = config.get("/openai/system")
        self.temperature = config.get_float("/openai/temperature", 0.7)
        self.model = config.get("/openai/model", "gpt-3.5-turbo")

        url = config.get("/openai/url")

        super().__init__(url, method="POST")

    async def do_request(self, message: str) -> bytes:

        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.key}"}

        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": message}
        ]

        data = {"model": self.model,
                "messages": messages,
                "temperature": self.temperature}

        data = json.dumps(data).encode("utf-8")

        return await super().issue_request(headers=headers, data=data)

    async def chat(self, message: str) -> str | None:

        data = await self.do_request(message)

        completion = json.loads(data.decode("utf-8"))

        if ("choices" in completion):
            if ("message" in completion["choices"][0]):
                message = completion["choices"][0]["message"]

                if "content" in message:
                    return message["content"]  # type: ignore

        return None


class RedditCache:

    def __init__(self, config: JSONConfig, ai: AI) -> None:

        self.query_cache = {}
        self.query_cache_lock = asyncio.Lock()

        self.config = config
        self.ai = ai

    async def get_sub_from_string(self, string: str) -> str | None:

        async with self.query_cache_lock:
            sub = self.config.get_str(f"/reddit/cache/{string}", "")

            if "" != sub:
                return sub

        # we don't have a cache for this yet

        q = f"what is the sub reddit for {string}."
        q += " Just return the name of the subreddit starting with /r/"
        q += " and nothing else"

        r = await self.ai.chat(q)

        if r is not None:
            async with self.query_cache_lock:
                self.config.set(f"/reddit/cache/{string}", r)

            return r

        return None


class GoogleRequestHandler(ClientRequestHandler):

    def __init__(self, config: JSONConfig) -> None:

        self.key = config.get("/google/key")
        self.cx = config.get("/google/cx")
        self.gl = config.get("/google/geo", "ca")
        super().__init__(config.get("/google/url"))

    async def do_request(self, q: str) -> bytes:

        params = {"key": self.key,
                  "cx": self.cx,
                  "gl": self.gl,
                  "q": q}

        return await super().issue_request(params)


class GCSEHandler:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        config_file = os.path.join(script_root, "config", "config.json")

        config = JSONConfig(config_file)

        self.google_request = GoogleRequestHandler(config)
        self.ai = AI(config)
        self.reddit_cache = RedditCache(config, self.ai)

    async def __aenter__(self) -> 'GCSEHandler':
        return self

    async def __aexit__(self, _, value, traceback) -> None:  # type: ignore
        await self.google_request.close()

    def _gzipped(self, data: bytes) -> bool:
        return (data != b'' and data[0] == 0x1f and data[1] == 0x8b)

    async def _favicon_get(self, url: str) -> bytes | None:

        q = urllib.parse.urlparse(url)

        try:
            async with AsyncHttpClient(url) as client:

                resp = await client.get(q.path)

                if (resp.status >= 200 and resp.status < 300):
                    return await resp.read_all()

        except OSError:
            print(f"Unable to connect to {url}")
        except Exception as e:
            print(f"{url} failed: {e}")

        return None

    def __get_lucky_url(self, gcse_data: bytes) -> str | None:

        gcse = json.loads(gcse_data.decode("utf-8"))

        if "items" not in gcse:
            return None

        item = gcse["items"][0]

        if "link" not in item:
            return None

        return item["link"]

    ############################################################################
    # PUBLIC
    ############################################################################
    async def static_handler(self, req: AsyncHttpRequest) -> None:

        fn = os.path.abspath(req.path)[1:]

        if (fn == ""):
            fn = "index.html"

        file_path = os.path.join(self.www_root, fn)

        await req.send_file(file_path)

    async def search(self, req: AsyncHttpRequest, q: str) -> None:

        location = None

        if q.startswith("r "):
            # reddit
            sub = await self.reddit_cache.get_sub_from_string(q[2:])
            if sub is not None:
                location = f"https://old.reddit.com{sub}"
        elif q.startswith("g "):
            # google
            q = q[2:]
            location = f"https://google.com/search?q={q}"
        elif q.startswith("i "):
            # google images
            q = q[2:]
            location = f"https://www.google.com/search?q={q}&tbm=isch"
        elif q.startswith("l "):
            # lucky
            gcse_data = await self.google_request.do_request(q[2:])
            location = self.__get_lucky_url(gcse_data)

        if location is not None:
            req.add_header("Location", location)
            req.set_status(HTTPStatus.MOVED_PERMANENTLY)
            await req.send_headers()
        else:
            await req.send_file(os.path.join(self.www_root, "index.html"))

    async def api_search(self, req: AsyncHttpRequest, q: str) -> None:

        if q == "test":
            await req.send_file("tests/test.json")
            return

        data = await self.google_request.do_request(q)

        if (data != b''):
            req.add_header("Content-Type", "application/json")
            await req.send_data(data)
        else:
            req.set_status(HTTPStatus.NOT_FOUND)

    async def api_chat(self, req: AsyncHttpRequest, q: str) -> None:

        data = await self.ai.do_request(q)

        completion = json.loads(data.decode("utf-8"))

        if ("choices" in completion):
            if ("message" in completion["choices"][0]):
                message = completion["choices"][0]["message"]
                await req.send_as_json(message)
            else:
                req.set_status(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        else:
            req.set_status(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)

        return

    async def opensearch(self, req: AsyncHttpRequest) -> None:

        opensearch = OPEN_SEARCH_TEMPLATE.replace("__HOST__", req.host)

        req.set_mime_type("application/xml")
        await req.send_as_text(opensearch)


async def run_server(addr: str, port: int, verbose: bool, disable_cache: bool) -> None:

    script_root = os.path.dirname(os.path.abspath(sys.argv[0]))

    log_file = os.path.join(script_root, "gcse.log")

    async with GCSEHandler() as handler:

        server = AsyncHttpServer(addr,
                                 port,
                                 log_file=log_file,
                                 verbose=verbose)

        if (True == disable_cache):
            server.disable_caching()

        api_list = [
            server.get("/search", handler.search, DEF_CACHE_TIMEOUT),
            server.get("/opensearch.xml", handler.opensearch),
            server.get("/api/search", handler.api_search, DEF_CACHE_TIMEOUT),
            server.get("/api/chat", handler.api_chat, DEF_CACHE_TIMEOUT),
        ]

        server.add_routes(api_list)
        server.set_static_route(handler.static_handler)

        await server.server_forever()


def main() -> int:

    status = 1

    parser = argparse.ArgumentParser()

    parser.add_argument("-p",
                        "--port",
                        type=int,
                        default=DEF_PORT,
                        help=f"port to listen on. Default is {DEF_PORT}")

    parser.add_argument("-a",
                        "--addr",
                        type=str,
                        default=DEF_ADDR,
                        help=f"addr to listen on. Default is {DEF_ADDR}")

    parser.add_argument("-v",
                        "--verbose",
                        action="store_true",
                        help="Verbose. Log to stdout.")

    parser.add_argument("--disable-cache",
                        action="store_true",
                        help="Disable caching.")

    args = parser.parse_args()

    print("gsearch:")
    printkv("Listening Address", args.addr)
    printkv("Listening Port", args.port)
    printkv("Verbose", args.verbose)
    printkv("Cache Disabled", args.disable_cache)

    try:
        asyncio.run(run_server(args.addr,
                               args.port,
                               args.verbose,
                               args.disable_cache))
        status = 0
    except FileNotFoundError as e:
        print(e)
    except OSError as e:
        if (e.errno == errno.EADDRINUSE):
            print(f"Address {args.addr}:{args.port} already in use")
        else:
            raise e
    except KeyboardInterrupt:
        status = 0

    return status


if __name__ == '__main__':
    status = main()

    if status != 0:
        sys.exit(status)
