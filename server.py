#!/usr/bin/env python3

import sys
import os
import time
import json
import errno
import argparse
import asyncio

import aiohttp
from jsonconfig import JSONConfig
from aiohttp import web

from openai.types.chat import ChatCompletionAssistantMessageParam
from openai.types.chat import ChatCompletionSystemMessageParam
from openai.types.chat import ChatCompletionUserMessageParam
from openai.types.chat import ChatCompletionMessageParam
from openai import AsyncOpenAI
from http import HTTPStatus
from dataclasses import dataclass, asdict, field

DEF_PORT = 8080
DEF_ADDR = "0.0.0.0"

OPEN_SEARCH_TEMPLATE = """
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>GSearch</ShortName>
  <Description>Search gsearch.com</Description>
  <Url type="text/html" method="get" template="__SCHEME__://__HOST__/search?q={searchTerms}"/>
  <Image width="16" height="16" type="image/x-icon">__SCHEME__://__HOST__/favicon.ico</Image>
  <InputEncoding>UTF-8</InputEncoding>
  <OutputEncoding>UTF-8</OutputEncoding>
</OpenSearchDescription>"""


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<25}{v}")


@dataclass
class GenericResponse:
    error: str | None = None
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class ChatResponse:
    create_ts: float
    response_ts: float
    id: str
    message: str

    def __str__(self):
        return f"id=${self.id} message={self.message}"


@dataclass
class ChatHistory:
    role: str
    content: str
    ts: float = 0


@dataclass
class ChatRequest:
    model: str | None = None
    prompt: str | None = None
    history: list[ChatHistory] = field(default_factory=list)

    def __post_init__(self) -> None:

        new_history: list[ChatHistory] = []

        for h in self.history:
            new_history.append(ChatHistory(**h))  # type: ignore
        self.history = new_history


class Chat:
    def __init__(self, config: JSONConfig) -> None:

        self.url = config.get("/openai/url")
        self.key = config.get("/openai/key")
        self.model = config.get("/openai/model")
        self.system = config.get("/openai/system")
        self.temperature = config.get_float("/openai/temperature", 0.3)
        self.max_prompt = config.get_int("/openai/max_prompt", 12)

        self.config = config

        self.client = AsyncOpenAI(api_key=self.key)

    def __str__(self) -> str:
        return f"model={self.model} system={self.system}"

    def get_model(self) -> str:
        return self.model

    def set_model(self, model: str) -> str:

        self.model = model
        self.config.set("/openai/model", model)

        return self.model

    async def speech_to_text(self, file_path: str) -> str:

        with open(file_path, "rb") as f:

            res = await self.client.audio.transcriptions.create(model="whisper-1",
                                                                file=f)
            return res.text

    async def chat(self, history: list[ChatHistory] = [], user_prompt: str | None = None, user_model: str | None = None) -> ChatResponse:

        messages: list[ChatCompletionMessageParam] = []

        if user_prompt is None:
            prompt = self.system
        else:
            prompt = user_prompt

        if user_model is None:
            model = self.model
        else:
            model = user_model

        s = ChatCompletionSystemMessageParam(content=prompt, role="system")

        messages.append(s)

        history = history[-self.max_prompt:]

        for h in history:

            if ("user" == h.role):
                m = ChatCompletionUserMessageParam(
                    content=h.content, role="user")
            else:
                m = ChatCompletionAssistantMessageParam(
                    content=h.content, role="assistant")

            messages.append(m)

        create_ts = time.time()

        comp = await self.client.chat.completions.create(model=model,
                                                         temperature=self.temperature,
                                                         messages=messages)

        response_ts = time.time()

        id = ""
        message = ""

        id = comp.id

        if (comp.choices[0].message.content is not None):
            message = comp.choices[0].message.content
        else:
            message = "empty response from completions API"

        return ChatResponse(create_ts, response_ts, id, message)

    def get_prompt(self) -> str:
        return self.system

    def set_prompt(self, system: str) -> str:
        self.system = system
        self.config.set("/openai/system", system)

        return self.system


class RedditCache:

    def __init__(self, config: JSONConfig, chat: Chat) -> None:

        self.query_cache = {}
        self.query_cache_lock = asyncio.Lock()

        self.config = config
        self.chat = chat

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

        msg = ChatHistory("user", q)

        r = await self.chat.chat([msg], "you are usefull assistant")

        async with self.query_cache_lock:
            self.config.set(f"/reddit/cache/{string}", r.message)

        return r.message


@dataclass
class Bookmark:
    url: str
    name: str = ""
    shortcut: str | None = None


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


class SearchAPI:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        config_file = os.path.join(script_root, "config", "config.json")
        self.__config = JSONConfig(config_file)

        self.gcse = GoogleRequestHandler(self.__config)
        self.chat = Chat(self.__config)
        self.reddit_cache = RedditCache(self.__config, self.chat)

        self.bookmarks_lock = asyncio.Lock()

    def __get_lucky_url(self, gcse_data: bytes) -> str | None:

        gcse = json.loads(gcse_data.decode("utf-8"))

        if "items" not in gcse:
            return None

        item = gcse["items"][0]

        if "link" not in item:
            return None

        return item["link"]

    async def __find_bookmark(self, q: str) -> Bookmark | None:

        async with self.bookmarks_lock:

            for b in self.__config.get_list("/bookmarks", []):

                bookmark = Bookmark(**b)

                if bookmark.name == q or bookmark.shortcut == q:
                    return bookmark

            return None

    async def __rdr(self, q: str) -> str | None:

        location = None

        if q.startswith("a "):
            # amazon
            q = q[2:]
            location = f"https://www.amazon.ca/s?k={q}"
        if q.startswith("b "):
            b = await self.__find_bookmark(q[2:])
            if b is not None:
                location = b.url
        elif q.startswith("c "):
            # chat / ai
            q = q[2:]
            location = f"/chat.html?q={q}"
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
            gcse_data = await self.gcse.get(q[2:])
            location = self.__get_lucky_url(gcse_data)
        elif q.startswith("m "):
            # maps
            q = q[2:]
            location = f"https://www.google.com/maps/search/{q}/"
        elif q.startswith("r "):
            # reddit
            sub = await self.reddit_cache.get_sub_from_string(q[2:])
            if sub is not None:
                location = f"https://old.reddit.com{sub}"
        elif q.startswith("w "):
            # wikipedia
            wq = f"{q[2:]} wikipedia"
            gcse_data = await self.gcse.get(wq)
            location = self.__get_lucky_url(gcse_data)

        return location

    async def __chat_set(self, req: web.Request, value_name: str) -> tuple[HTTPStatus, GenericResponse]:

        status = HTTPStatus.BAD_REQUEST

        resp = GenericResponse()

        try:
            user_data = await req.json()

            if value_name not in user_data:
                raise ValueError(f'Missing "{value_name}"')

            value = user_data[value_name]

            if value_name == "model":
                self.chat.set_model(value)
            elif value_name == "prompt":
                self.chat.set_prompt(value)
            else:
                raise NotImplementedError(f"{value_name} not implemented")

            status = HTTPStatus.OK

        except ValueError as e:
            resp.error = str(e)
        except NotImplementedError as e:
            resp.error = str(e)

        return status, resp

    ############################################################################
    # PUBLIC
    ############################################################################

    async def static(self, request: web.Request) -> web.StreamResponse:

        fn = os.path.abspath(request.path)[1:]

        if (fn == ""):
            fn = "index.html"

        return web.FileResponse(os.path.join(self.www_root, fn))

    async def opensearch(self, req: web.Request) -> web.Response:

        template = OPEN_SEARCH_TEMPLATE.replace("__HOST__", req.host)
        template = template.replace("__SCHEME__", req.scheme)
        return web.Response(text=template, content_type="application/xml")

    async def api_search(self, req: web.Request) -> web.Response:

        if "q" not in req.rel_url.query:
            return web.Response(status=HTTPStatus.EXPECTATION_FAILED)

        q = req.rel_url.query["q"].replace(".", " ")

        location = await self.__rdr(q)

        if location is not None:

            headers = {
                "Location": location
            }

            return web.Response(headers=headers, status=HTTPStatus.FOUND)

        # a real search
        data = await self.gcse.get(q)

        if (data != b''):
            return web.Response(body=data, content_type="application/json")

        return web.Response(status=HTTPStatus.NOT_FOUND)

    #######################################
    # BOOKMARKS
    #######################################

    async def api_bookmarks(self, req: web.Request) -> web.Response:

        async with self.bookmarks_lock:
            blist = self.__config.get_list("/bookmarks", [])

        return web.json_response(blist)

    async def api_bookmarks_add(self, req: web.Request) -> web.Response:

        error = ""

        try:
            # this'll make sure we got "something" from the user
            user_data = await req.json()
            bookmark = Bookmark(**user_data)

            async with self.bookmarks_lock:

                exists = False

                bookmarks = self.__config.get_list("/bookmarks", [])

                for b in bookmarks:

                    if b["name"] == bookmark.name:
                        exists = True
                        break

                if False == exists:
                    bookmarks.append(asdict(bookmark))

                    self.__config.set("/bookmarks", bookmarks)

            status = HTTPStatus.OK
        except NotImplementedError as e:
            error = str(e)
            status = HTTPStatus.NOT_IMPLEMENTED
        except ValueError as e:
            error = str(e)
            status = HTTPStatus.BAD_REQUEST
        except TypeError as e:
            error = str(e)
            status = HTTPStatus.BAD_REQUEST
        except Exception as e:
            status = HTTPStatus.BAD_REQUEST

        return web.Response(text=error, status=status)

    async def api_bookmarks_del(self, req: web.Request) -> web.Response:

        if "name" not in req.rel_url.query:
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        name = req.rel_url.query["name"]

        async with self.bookmarks_lock:

            status = HTTPStatus.NOT_FOUND

            bookmarks = self.__config.get_list("/bookmarks", [])

            for b in bookmarks:
                if b["name"] == name:
                    bookmarks.remove(b)
                    self.__config.set("/bookmarks", bookmarks)
                    status = HTTPStatus.OK
                    break

        return web.Response(status=status)

    #######################################
    # CHAT
    #######################################

    async def api_chat(self, req: web.Request) -> web.Response:

        resp = GenericResponse()
        status = HTTPStatus.BAD_REQUEST

        try:
            user_data = await req.json()

            # type check AND convert to a ChatRequest

            chat_req = ChatRequest(**user_data)

            chat_resp = await self.chat.chat(chat_req.history,
                                             chat_req.prompt,
                                             chat_req.model)

            resp.data = asdict(chat_resp)

            status = HTTPStatus.OK
        except ValueError as e:
            resp.error = str(e)
        except TypeError as e:
            resp.error = str(e)

        return web.json_response(asdict(resp), status=status)

    async def api_chat_model_get(self, req: web.Request) -> web.Response:

        resp = GenericResponse()
        resp.data = {"model": self.chat.get_model()}
        return web.json_response(asdict(resp))

    async def api_chat_model_set(self, req: web.Request) -> web.Response:

        status, resp = await self.__chat_set(req, "model")
        return web.json_response(asdict(resp), status=status)

    async def api_chat_prompt_get(self, req: web.Request) -> web.Response:

        resp = GenericResponse()
        resp.data = {"prompt": self.chat.get_prompt()}
        return web.json_response(asdict(resp))

    async def api_chat_prompt_set(self, req: web.Request) -> web.Response:

        status, resp = await self.__chat_set(req, "prompt")
        return web.json_response(asdict(resp), status=status)


def run_server(addr: str, port: int) -> None:

    handler = SearchAPI()

    routes = [
        # opensearch
        web.get("/opensearch.xml", handler.opensearch),

        # search
        web.get("/api/search", handler.api_search),

        # bookmarks
        web.get("/api/bookmarks", handler.api_bookmarks),
        web.post("/api/bookmarks/add", handler.api_bookmarks_add),
        web.get("/api/bookmarks/del", handler.api_bookmarks_del),

        # chat
        web.post("/api/chat", handler.api_chat),
        web.get("/api/chat/model", handler.api_chat_model_get),
        web.post("/api/chat/model", handler.api_chat_model_set),
        web.get("/api/chat/prompt", handler.api_chat_prompt_get),
        web.post("/api/chat/prompt", handler.api_chat_prompt_set),

        # static file handler
        web.get("/{path:.*}", handler.static),
    ]

    app = web.Application()

    app.add_routes(routes)

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
