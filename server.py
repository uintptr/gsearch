#!/usr/bin/env python3

import sys
import os
import asyncio
import json

from typing import Dict, List

from ahttp.ahttp import AsyncHttpRequest, AsyncHttpServer, AsyncHttpClient

DEF_CACHE_TIMEOUT_SEC = (1 * (60 * 60))


class GCSEHandler:
    def __init__(self, task_count: int = 1) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.www_root = os.path.join(script_root, "www")

        self.query_queue = asyncio.Queue()
        self.query_tasks: List[asyncio.Task] = []
        self.done = False
        self.task_count = task_count

        self.config = self._load_config()

    def _load_config(self) -> Dict:

        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        config_file = os.path.join(script_root, "config", "config.json")

        with open(config_file) as f:
            return json.load(f)

    async def _query_task(self):

        try:
            while (False == self.done):
                item = await self.query_queue.get()

                if (item is None):
                    continue
        except asyncio.CancelledError as e:
            raise e

    async def __aenter__(self):

        for i in range(0, self.task_count):
            name = f"query_{i}"
            self.query_task = asyncio.create_task(self._query_task(),
                                                  name=name)
        return self

    async def __aexit__(self, type, value, traceback) -> None:
        self.done = True
        await self.query_queue.put(None)
        await self.query_task

    async def static_handler(self, req: AsyncHttpRequest) -> None:

        fn = os.path.abspath(req.path)[1:]

        if (fn == ""):
            fn = "index.html"

        file_path = os.path.join(self.www_root, fn)

        await req.send_file(file_path)

    async def api_search(self, req: AsyncHttpRequest, q: str) -> None:

        await self.query_queue.put(q)
        await req.send_file("results.json")


async def run_server() -> None:

    async with GCSEHandler() as handler:

        server = AsyncHttpServer(verbose=True)

        api_list = [
            server.get("/api/search", handler.api_search,
                       DEF_CACHE_TIMEOUT_SEC)
        ]

        server.add_routes(api_list)
        server.set_static_route(handler.static_handler)

        await server.server_forever()


def main() -> int:

    status = 1

    try:
        asyncio.run(run_server())
        status = 0
    except FileNotFoundError as e:
        print(e)
    except KeyboardInterrupt:
        status = 0

    return status


if __name__ == '__main__':
    status = main()

    if status != 0:
        sys.exit(status)
