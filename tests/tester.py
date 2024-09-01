#!/usr/bin/env python3

import os
import sys
import argparse
import glob
import json
import urllib.error
import urllib.request
import urllib.parse
import urllib
from typing import Any

from dataclasses import dataclass, field

DEF_SERVER = "http://localhost:8080"


@dataclass
class Test:
    url: str
    method: str
    name: str
    code: int = 200
    data: dict[str, Any] = field(default_factory=dict)


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<18}{v}")


def print_result(idx: int, file_name: str, test_name: str, result: str) -> None:

    print(f"[{idx:<4}] {file_name:<35}{test_name:<35}{result}")


class Tester:

    def __init__(self, server: str) -> None:
        self.server = server
        self.test_id = 0

    def __do_request(self, url: str | urllib.request.Request, test: Test) -> None:

        code = 0

        try:
            with urllib.request.urlopen(url) as r:
                code = r.code
        except urllib.error.HTTPError as e:
            code = e.code

        err_str = f"{code} != {test.code}"

        assert code == test.code, err_str

    def __parse_test_post(self, url: str, test: Test) -> None:

        headers = {'Content-Type': 'application/json'}
        data = json.dumps(test.data).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers)
        self.__do_request(req, test)

    def __parse_test_get(self, url: str, test: Test) -> None:

        sep = '?'
        for p in test.data:
            url += f"{sep}{p}={test.data[p]}"
            sep = '&'

        encoded_url = urllib.parse.quote(url, safe=':/?=&')

        self.__do_request(encoded_url, test)

    def __parse_test(self, test: Test) -> str:

        full_url = f"{self.server}{test.url}"

        try:

            if "GET" == test.method:
                self.__parse_test_get(full_url, test)
            elif "POST" == test.method:
                self.__parse_test_post(full_url, test)
            else:
                raise NotImplementedError(f"{test.method} not implemented")

            status = "SUCCESS"
        except Exception as e:
            status = f"FAILURE ({type(e).__name__}) error: ({e})"

        return status

    def test_file(self, file_path: str) -> None:

        try:
            with open(file_path) as f:
                test_data = json.load(f)

            fn = os.path.basename(file_path)

            for i in test_data["tests"]:

                t = Test(**i)

                status = self.__parse_test(t)

                print_result(self.test_id, fn, t.name, status)
                self.test_id += 1
        except TypeError as e:
            print(f"Unable to parse {file_path} ({e})")

    def test_directory(self, dir_path: str) -> None:

        for f in glob.glob(os.path.join(dir_path, "*.json")):
            self.test_file(f)


def main() -> int:

    status = 1

    parser = argparse.ArgumentParser()

    script_root = os.path.abspath(os.path.dirname(sys.argv[0]))

    def_input = os.path.join(script_root, "api")

    parser.add_argument("-i",
                        "--input",
                        type=str,
                        default=def_input,
                        help=f"/path/to/file|directoryy. Default: {def_input}")

    parser.add_argument("-s",
                        "--server",
                        type=str,
                        default=DEF_SERVER,
                        help=f"Server to test. Default: {DEF_SERVER}")

    args = parser.parse_args()

    try:

        # normalize
        input = os.path.abspath(args.input)

        print("Tester:")
        printkv("Input", input)
        printkv("Server", args.server)

        tester = Tester(args.server)

        print("\n")

        if os.path.isfile(input):
            tester.test_file(input)
        elif os.path.isdir(input):
            tester.test_directory(input)
        else:
            raise FileNotFoundError(f"{input} doesn't exist")

        status = 0
    except KeyboardInterrupt:
        pass

    return status


if __name__ == '__main__':

    status = main()

    if 0 != status:
        sys.exit(status)
