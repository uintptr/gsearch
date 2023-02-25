#!/usr/bin/env python3

import sys
import os
import json
import errno
import argparse
import traceback
import asyncio
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional
from http import HTTPStatus

from ahttp.ahttp import AsyncHttpRequest, AsyncHttpServer, AsyncHttpClient

DEF_CACHE_TIMEOUT = (1 * (60 * 60))
DEF_PORT = 8080
DEF_ADDR = "0.0.0.0"


@dataclass
class AsyncQuery:
    q: str
    event = asyncio.Event()
    data: bytes = b""


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<25}{v}")


class FavIconCache:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))

        self.favicon_lock = asyncio.Lock()
        self.favicon_dir = os.path.join(script_root, "favicon")

        if (not os.path.exists(self.favicon_dir)):
            os.makedirs(self.favicon_dir)

    async def get(self, name: str) -> Optional[bytes]:

        file_path = os.path.join(self.favicon_dir, name)

        async with self.favicon_lock:
            if (os.path.exists(file_path)):
                with open(file_path, "rb") as f:
                    return f.read()

        return None

    async def set(self, name: str, data: bytes) -> None:

        file_path = os.path.join(self.favicon_dir, name)

        async with self.favicon_lock:
            with open(file_path, "wb") as f:
                f.write(data)


class GCSEHandler:
    def __init__(self, task_count: int = 1) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        self.query_queue = asyncio.Queue()
        self.query_tasks: List[asyncio.Task] = []
        self.done = False
        self.task_count = task_count

        self.config = self._load_config()

        api_key = self.config["api_key"]
        cx = self.config["search_engine_id"]

        self.base_url = f"/customsearch/v1?key={api_key}"
        self.base_url += f"&cx={cx}"

        self.favicon_cache = FavIconCache()

    def _load_config(self) -> Dict[str, str]:

        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        config_file = os.path.join(script_root, "config", "config.json")

        with open(config_file) as f:
            return json.load(f)

    async def _issue_request(self, client: AsyncHttpClient, q: AsyncQuery) -> bytes:

        encoded_q = urllib.parse.quote(q.q)

        url = f"{self.base_url}&q={encoded_q}"

        resp = await client.send_request("GET", url)

        if (resp.status >= 200 and resp.status < 300):
            return await resp.read_all()

        print(f"{url} returned {resp.status}")

        return b''

    async def _query_loop(self, client) -> None:

        while (True):
            try:
                q = await self.query_queue.get()

                q.data = await self._issue_request(client, q)
                q.event.set()
                self.query_queue.task_done()

                print(f"data len = {len(q.data)}")

            except asyncio.CancelledError as e:
                raise e
            except ConnectionResetError:
                break
            except BrokenPipeError:
                break
            except Exception:
                traceback.print_exc()
                break

    async def _query_task(self) -> None:

        url = self.config["cse_url"]

        try:
            while (True):
                async with AsyncHttpClient(url) as client:
                    await self._query_loop(client)
        except asyncio.CancelledError:
            # swallow it
            pass

    async def __aenter__(self) -> 'GCSEHandler':

        for i in range(0, self.task_count):
            name = f"query_{i}"
            t = asyncio.create_task(self._query_task(), name=name)
            self.query_tasks.append(t)
        return self

    async def __aexit__(self, type, value, traceback) -> None:
        self.done = True

        for t in self.query_tasks:
            t.cancel()
            await t

    async def static_handler(self, req: AsyncHttpRequest) -> None:

        fn = os.path.abspath(req.path)[1:]

        if (fn == ""):
            fn = "index.html"

        file_path = os.path.join(self.www_root, fn)

        await req.send_file(file_path)

    async def api_search(self, req: AsyncHttpRequest, q: str) -> None:

        await req.send_file("results.json")
        return

        aq = AsyncQuery(q)

        aq.event.clear()

        await self.query_queue.put(aq)
        await aq.event.wait()

        if (aq.data != b''):

            with open("results.json", "wb+") as f:
                f.write(aq.data)

            req.add_header("Content-Type", "application/json")
            await req.send_data(aq.data)
        else:
            req.set_status(HTTPStatus.NOT_FOUND)

    async def api_favicon(self, req: AsyncHttpRequest, url: str) -> None:

        q = urllib.parse.urlparse(url)

        if (q.hostname is None):
            req.set_status(HTTPStatus.BAD_REQUEST)
            return

        data = await self.favicon_cache.get(q.hostname)

        if (data is None):

            try:
                async with AsyncHttpClient(url) as client:

                    resp = await client.send_request("GET", q.path)

                    if (resp.status == 200):
                        data = await resp.read_all()

                        if (data != b''):
                            await self.favicon_cache.set(q.hostname, data)
            except OSError as e:
                print(f"Unable to connect to {url}")
            except Exception as e:
                print(f"{url} failed: {e}")

        if (data is not None):
            req.add_header("Content-Type", "image/x-icon")
            await req.send_data(data)
        else:
            req.set_status(HTTPStatus.NOT_FOUND)


async def run_server(args) -> None:

    async with GCSEHandler() as handler:

        server = AsyncHttpServer(args.addr, args.port, verbose=args.verbose)

        if(True == args.cache_disabled):
            server.disable_caching()

        api_list = [
            server.get("/api/search", handler.api_search, DEF_CACHE_TIMEOUT),
            server.get("/api/favicon", handler.api_favicon, DEF_CACHE_TIMEOUT),
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
                        help=f"Verbose. Log to stdout.")

    parser.add_argument("--disable-cache",
                        action="store_true",
                        help=f"Disable caching.")

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
