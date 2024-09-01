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
class TestParam:
    key: str
    value: Any


@dataclass
class TestData:
    expected_code: int = 200
    params: list[TestParam] = field(default_factory=list)
    post_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Test:
    name: str
    data: TestData

    def __post_init__(self) -> None:
        self.data = TestData(**self.data)  # type: ignore


@dataclass
class TestDefinition:

    url: str
    method: str
    tests: list[Test] = field(default_factory=list)

    def __post_init__(self) -> None:
        new_tests: list[Test] = []
        for t in self.tests:
            new_tests.append(Test(**t))  # type: ignore
        self.tests = new_tests


def printkv(k: str, v: object) -> None:

    k = f"{k}:"
    print(f"    {k:<18}{v}")


def print_result(idx: int, file_name: str, test_name: str, result: str) -> None:

    print(f"[{idx:<4}] {file_name:<35}{test_name:<35}{result}")


class Tester:

    def __init__(self, server: str) -> None:
        self.server = server
        self.test_id = 0

    def __do_request(self, url: str | urllib.request.Request, test: TestData) -> None:

        code = 0

        try:
            with urllib.request.urlopen(url) as r:
                code = r.code
        except urllib.error.HTTPError as e:
            code = e.code

        err_str = f"{code} != {test.expected_code}"

        assert code == test.expected_code, err_str

    def __parse_test_post(self, url: str, test: TestData) -> None:

        headers = {'Content-Type': 'application/json'}
        data = json.dumps(test.post_data).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers)
        self.__do_request(req, test)

    def __parse_test_get(self, url: str, test: TestData) -> None:
        self.__do_request(url, test)

    def __parse_test(self, url: str, method: str, data: TestData) -> str:

        full_url = f"{self.server}{url}"

        try:

            if "GET" == method:
                self.__parse_test_get(full_url, data)
            elif "POST" == method:
                self.__parse_test_post(full_url, data)
            else:
                raise NotImplementedError(f"method={method}  not implemented")

            status = "SUCCESS"
        except Exception as e:
            status = f"FAILURE ({type(e).__name__}) error: ({e})"

        return status

    def test_file(self, file_path: str) -> None:

        with open(file_path) as f:
            test_data = json.load(f)

        td = TestDefinition(**test_data)

        fn = os.path.basename(file_path)

        for t in td.tests:

            status = self.__parse_test(td.url, td.method, t.data)
            print_result(self.test_id, fn, t.name, status)
            self.test_id += 1

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
