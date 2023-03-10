#!/usr/bin/env python3

import sys
import os
import json
import errno
import argparse
import asyncio
import urllib.parse
from typing import Dict, List, Optional
from http import HTTPStatus

try:
    import openai
    have_openai = True
except ImportError:
    have_openai = False

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


CHAT_SYSTEM = """You're are a snarky and sarsacastic search engine answersing
simple questions. If you don't know the answer just answer with
the shrug ascii"""


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<25}{v}")


class FavIconCache:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))

        self.favicon_dir = os.path.join(script_root, "favicon")

        if (not os.path.exists(self.favicon_dir)):
            os.makedirs(self.favicon_dir)

        default_favicon = os.path.join(script_root, "www", "default.ico")

        self.default = b""

        if (os.path.exists(default_favicon)):
            with open(default_favicon, "rb") as f:
                self.default = f.read()

    def get_default(self) -> Optional[bytes]:
        return self.default

    def get(self, name: str) -> Optional[bytes]:

        file_path = os.path.join(self.favicon_dir, name)

        if (os.path.exists(file_path)):
            with open(file_path, "rb") as f:
                return f.read()

        return None

    def set(self, name: str, data: bytes) -> None:

        file_path = os.path.join(self.favicon_dir, name)

        with open(file_path, "wb") as f:
            f.write(data)


class GCSEHandler:
    def __init__(self, task_count: int = 1) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        self.done = False
        self.task_count = task_count

        self.config = self._load_config()

        self.server_url = self.config["cse_url"]

        api_key = self.config["api_key"]
        cx = self.config["search_engine_id"]

        self.base_url = f"/customsearch/v1?key={api_key}"
        self.base_url += f"&cx={cx}"

        if ("openai_key" in self.config):
            openai.api_key = self.config["openai_key"]
        else:
            have_openai = False

        self.favicon_cache_lock = asyncio.Lock()
        self.favicon_cache = FavIconCache()

        self.connections_lock = asyncio.Lock()
        self.connections: List[AsyncHttpClient] = []

    def _load_config(self) -> Dict[str, str]:

        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        config_file = os.path.join(script_root, "config", "config.json")

        with open(config_file) as f:
            return json.load(f)

    async def _pop_client_connection(self) -> AsyncHttpClient:

        async with self.connections_lock:
            if (len(self.connections) > 0):
                return self.connections.pop()
            else:
                client = AsyncHttpClient(self.server_url)
                await client.connect()
                return client

    async def _return_client_connection(self, client: AsyncHttpClient) -> None:

        async with self.connections_lock:
            self.connections.append(client)

    async def _issue_request(self, q: str, max_attempts: int = 5) -> bytes:

        encoded_q = urllib.parse.quote(q)
        url = f"{self.base_url}&q={encoded_q}&gl=ca"

        data = b''
        attempts = 0
        replied = False
        client = None

        while (False == replied and attempts < max_attempts):

            try:
                client = await self._pop_client_connection()

                resp = await client.get(url)

                if (resp.status >= 200 and resp.status < 300):
                    data = await resp.read_all()
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
        return data

    async def __aenter__(self) -> 'GCSEHandler':
        return self

    async def __aexit__(self, type, value, traceback) -> None:
        pass

    def _gzipped(self, data: bytes) -> bool:
        return (data != b'' and data[0] == 0x1f and data[1] == 0x8b)

    async def _favicon_get(self, url) -> Optional[bytes]:

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

        await req.send_file(os.path.join(self.www_root, "index.html"))

    async def api_search(self, req: AsyncHttpRequest, q: str) -> None:

        if (q == "test"):
            await req.send_file("tests/test.json")
            return

        data = await self._issue_request(q)

        if (data != b''):
            req.add_header("Content-Type", "application/json")

            await req.send_data(data)
        else:
            req.set_status(HTTPStatus.NOT_FOUND)

    async def api_chat(self, req: AsyncHttpRequest, q: str) -> None:

        if (False == have_openai):
            req.set_status(HTTPStatus.NOT_IMPLEMENTED)
            return

        completion = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",

            messages=[
                {"role": "system", "content": CHAT_SYSTEM},
                {"role": "user", "content": q},
            ]
        )

        response_dict = completion.choices[0].message.to_dict()  # type: ignore
        await req.send_as_json(response_dict)

    async def opensearch(self, req: AsyncHttpRequest) -> None:

        opensearch = OPEN_SEARCH_TEMPLATE.replace("__HOST__", req.host)

        req.set_mime_type("application/xml")
        await req.send_as_text(opensearch)

    async def api_favicon(self, req: AsyncHttpRequest, url: str) -> None:

        q = urllib.parse.urlparse(url)

        if (q.hostname is None):
            req.set_status(HTTPStatus.BAD_REQUEST)
            return

        async with self.favicon_cache_lock:
            data = self.favicon_cache.get(q.hostname)

        if (data is None):
            # not cached
            data = await self._favicon_get(url)

            if (data is not None and data != b'' and data[0] == 0x3c and data[1] == 0x21):
                # likely html...
                data = None

            if (data is not None):
                async with self.favicon_cache_lock:
                    self.favicon_cache.set(q.hostname, data)
            else:
                data = self.favicon_cache.get_default()

        if (data is not None):
            req.add_header("Content-Type", "image/x-icon")

            if (self._gzipped(data)):
                req.add_header("content-encoding", "gzip")

            await req.send_data(data)
        else:
            req.set_status(HTTPStatus.NOT_FOUND)


async def run_server(args) -> None:

    script_root = os.path.dirname(os.path.abspath(sys.argv[0]))

    log_file = os.path.join(script_root, "gcse.log")

    async with GCSEHandler() as handler:

        server = AsyncHttpServer(args.addr,
                                 args.port,
                                 log_file=log_file,
                                 verbose=args.verbose)

        if (True == args.disable_cache):
            server.disable_caching()

        api_list = [
            server.get("/search", handler.search, DEF_CACHE_TIMEOUT),
            server.get("/opensearch.xml", handler.opensearch),
            server.get("/api/search", handler.api_search, DEF_CACHE_TIMEOUT),
            server.get("/api/favicon", handler.api_favicon, DEF_CACHE_TIMEOUT),
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
        asyncio.run(run_server(args))
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
