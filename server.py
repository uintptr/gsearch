#!/usr/bin/env python3

import sys
import os
import json
import errno
import argparse
import asyncio
from http import HTTPStatus
from dataclasses import dataclass, asdict
from typing import Callable, Awaitable

import aiohttp
from aiohttp import web

from jsonconfig import JSONConfig


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


class AI:

    def __init__(self, config: JSONConfig) -> None:

        self.key = config.get("/openai/key")
        self.system = config.get("/openai/system")
        self.temperature = config.get_float("/openai/temperature", 0.7)
        self.model = config.get("/openai/model", "gpt-3.5-turbo")
        self.url = config.get("/openai/url")

        self.__config = config

    async def post(self, message: str) -> bytes:

        headers = {"Authorization": f"Bearer {self.key}"}

        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": message}
        ]

        data = {"model": self.model,
                "messages": messages,
                "temperature": self.temperature}

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, headers=headers, json=data) as response:
                return await response.read()

    async def chat(self, message: str) -> str | None:

        data = await self.post(message)

        completion = json.loads(data.decode("utf-8"))

        if ("choices" in completion):
            if ("message" in completion["choices"][0]):
                message = completion["choices"][0]["message"]

                if "content" in message:
                    return message["content"]  # type: ignore

        return None

    def get_prompt(self) -> str:
        return self.system

    def set_prompt(self, prompt: str) -> None:

        self.system = prompt
        self.__config.set("/openai/system", self.system)

    def get_model(self) -> str:
        return self.model

    def set_model(self, model: str) -> None:
        self.model = model
        self.__config.set("/openai/model", self.model)


class RedditCache:

    def __init__(self, config: JSONConfig, ai: AI) -> None:

        self.query_cache = {}
        self.query_cache_lock = asyncio.Lock()

        self.config = config
        self.ai = ai

    async def get_sub_from_string(self, string: str) -> str | None:

        string = string.lower()

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


@dataclass
class UserCommand:

    cmd: str
    args: str = ""


@dataclass
class CmdHandler:

    name: str
    help: str
    handler: Callable[[UserCommand], Awaitable[str]]
    markdown: bool = False
    hidden: bool = False


@dataclass
class CmdResponse:
    data: str = ""
    markdown: bool = False
    error: str = ""


class CmdLine:

    def __init__(self, ai: AI) -> None:
        self.__ai = ai

        self.__commands = [
            CmdHandler("/help", "This help", self.help, True),
            CmdHandler("/chat", "LLM chat", self.chat, True, True),
            CmdHandler("/prompt", "Get or change prompt", self.prompt),
            CmdHandler("/model", "Get current model", self.model, True),
            CmdHandler("/uptime", "Uptime", self.uptime),
        ]

    async def __exec(self, cmd_line: str) -> tuple[int, str, str]:

        ret = 1
        stdout = ""
        stderr = ""

        p = await asyncio.create_subprocess_shell(cmd_line,
                                                  stdout=asyncio.subprocess.PIPE,
                                                  stderr=asyncio.subprocess.PIPE)

        stdout_buff, stderr_buff = await p.communicate()

        if b'' != stdout_buff:
            stdout = stdout_buff.decode("utf-8")

        if b'' != stderr_buff:
            stderr = stderr_buff.decode("utf-8")

        if p.returncode is not None:
            ret = p.returncode

        return ret, stdout, stderr

    async def help(self, cmd: UserCommand) -> str:

        help_str = "```\ncommands:\n"

        for c in self.__commands:
            if False == c.hidden:
                help_str += f"    {c.name:<12}{c.help}\n"

        help_str += "```"

        return help_str

    async def chat(self, cmd: UserCommand) -> str:

        if "" == cmd.args:
            raise ValueError("Missing message")

        resp = await self.__ai.chat(cmd.args)

        if resp is None:
            resp = ""

        return resp

    async def prompt(self, cmd: UserCommand) -> str:

        if "" != cmd.args:
            self.__ai.set_prompt(cmd.args)

        return self.__ai.get_prompt()

    async def model(self, cmd: UserCommand) -> str:

        if "" != cmd.args:
            self.__ai.set_model(cmd.args)

        return self.__ai.get_model()

    async def uptime(self, cmd: UserCommand) -> str:
        _, uptime, _ = await self.__exec("/usr/bin/uptime")
        return uptime

    async def handler(self, cmd: UserCommand) -> CmdResponse:

        for c in self.__commands:
            if cmd.cmd == c.name:
                response = await c.handler(cmd)
                return CmdResponse(response, c.markdown)

        raise NotImplementedError(f"{cmd} is not implemented")


class GoogleRequestHandler:

    def __init__(self, config: JSONConfig) -> None:

        self.key = config.get("/google/key")
        self.cx = config.get("/google/cx")
        self.gl = config.get("/google/geo", "ca")
        self.url = config.get("/google/url")

    async def get(self, q: str) -> bytes:

        params = {"key": self.key,
                  "cx": self.cx,
                  "gl": self.gl,
                  "q": q}

        async with aiohttp.ClientSession() as s:
            async with s.get(self.url, params=params) as r:
                return await r.read()


class GCSEHandler:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        config_file = os.path.join(script_root, "config", "config.json")

        config = JSONConfig(config_file)

        self.google_request = GoogleRequestHandler(config)
        self.ai = AI(config)
        self.reddit_cache = RedditCache(config, self.ai)
        self.cmdline = CmdLine(self.ai)

    def __get_lucky_url(self, gcse_data: bytes) -> str | None:

        gcse = json.loads(gcse_data.decode("utf-8"))

        if "items" not in gcse:
            return None

        item = gcse["items"][0]

        if "link" not in item:
            return None

        return item["link"]

    async def __rdr(self, req: web.Request, q: str) -> str | None:

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
            gcse_data = await self.google_request.get(q[2:])
            location = self.__get_lucky_url(gcse_data)
        elif q.startswith("a "):
            # amazon
            q = q[2:]
            location = f"https://www.amazon.ca/s?k={q}"
        elif q.startswith("m "):
            # maps
            q = q[2:]
            location = f"https://www.google.com/maps/search/{q}/"
        elif q.startswith("c "):
            # chat / ai
            q = q[2:]
            location = f"{req.scheme}://{req.host}/chat.html?q={q}"

        return location

    ############################################################################
    # PUBLIC
    ############################################################################

    async def static(self, request: web.Request) -> web.StreamResponse:

        fn = os.path.abspath(request.path)[1:]

        if (fn == ""):
            fn = "index.html"

        return web.FileResponse(os.path.join(self.www_root, fn))

    async def search(self, req: web.Request) -> web.Response | web.FileResponse:

        location = None

        if "q" not in req.rel_url.query:
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        q = req.rel_url.query["q"].replace(".", " ")

        location = await self.__rdr(req, q)

        if location is not None:

            headers = {
                "Location": location
            }

            return web.Response(headers=headers,
                                status=HTTPStatus.MOVED_PERMANENTLY)

        index = os.path.join(self.www_root, "index.html")
        return web.FileResponse(index)

    async def api_search(self, req: web.Request) -> web.Response:

        if "q" not in req.rel_url.query:
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        q = req.rel_url.query["q"].replace(".", " ")

        data = await self.google_request.get(q)

        if (data != b''):
            return web.Response(body=data, content_type="application/json")

        return web.Response(status=HTTPStatus.NOT_FOUND)

    async def api_chat(self, req: web.Request) -> web.Response:

        if "q" not in req.rel_url.query:
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        q = req.rel_url.query["q"].replace(".", " ")

        data = await self.ai.post(q)

        completion = json.loads(data.decode("utf-8"))

        if ("choices" not in completion):
            return web.Response(status=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)

        choices = completion["choices"][0]

        if "message" not in choices:
            return web.Response(status=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)

        message = choices["message"]
        return web.Response(text=json.dumps(message),
                            content_type="application/json")

    async def opensearch(self, req: web.Request) -> web.Response:

        template = OPEN_SEARCH_TEMPLATE.replace("__HOST__", req.host)
        return web.Response(text=template, content_type="application/xml")

    async def api_cmd(self, req: web.Request) -> web.Response:

        data = await req.json()

        user_cmd = UserCommand(**data)

        resp = CmdResponse()

        try:

            if "cmd" not in data:
                raise ValueError("missing command")

            resp = await self.cmdline.handler(user_cmd)
            status = HTTPStatus.OK
        except NotImplementedError as e:
            resp.error = str(e)
            status = HTTPStatus.NOT_IMPLEMENTED
        except ValueError as e:
            resp.error = str(e)
            status = HTTPStatus.BAD_REQUEST

        return web.json_response(asdict(resp), status=status)


def run_server(addr: str, port: int) -> None:

    handler = GCSEHandler()

    routes = [
        web.get("/search", handler.search),
        web.get("/opensearch.xml", handler.opensearch),
        web.get("/api/search", handler.api_search),
        web.get("/api/chat", handler.api_chat),
        web.get("/{path:.*}", handler.static)
    ]

    app = web.Application()

    app.add_routes(routes)

    app.router.add_post("/api/cmd", handler.api_cmd)

    web.run_app(app, port=port, host=addr, reuse_address=True)  # type: ignore


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

    args = parser.parse_args()

    print("gsearch:")
    printkv("Listening Address", args.addr)
    printkv("Listening Port", args.port)

    try:
        run_server(args.addr, args.port)
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
