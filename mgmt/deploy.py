#!/usr/bin/env python3

import os
import sys
import argparse
import subprocess

DEF_DOCKER_PROC_NAME = "gsearch"
DEF_DOCKER_IMG_NAME = "py:gsearch"
DEF_DOCKER_PORT = 8080


class ShellException(Exception):
    pass


def exec_cmd(cmd_line: str, cwd: str | None = None, check: bool = True) -> tuple[int, str, str]:

    ret = 1

    with subprocess.Popen(cmd_line,
                          shell=True,
                          text=True,
                          cwd=cwd,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as p:

        stdout, stderr = p.communicate()

        if p.returncode is not None:
            ret = p.returncode

        if True == check and 0 != ret:

            err_str = f"{cmd_line} returned {ret}"

            if "" != stdout:
                err_str += f"\n{stdout}"

            if "" != stderr:
                err_str += f"\n{stderr}"

            raise ShellException(err_str)

    return ret, stdout, stderr


def docker_process_by_name(name: str) -> str | None:

    cmd_line = 'docker ps --format "{{.ID}} {{.Names}}"'

    _, out, _ = exec_cmd(cmd_line)

    for line in out.splitlines():
        comp = line.split()

        if comp[1] == name:
            return comp[0]

    return None


def docker_stop(name: str) -> None:

    cid = docker_process_by_name(name)

    if cid is not None:
        exec_cmd(f"docker stop {cid}")
        exec_cmd(f"docker rm {cid}", check=False)


def docker_build_image(app_root: str, image_name: str) -> None:

    cmd_line = f"docker build -t {image_name} ."
    exec_cmd(cmd_line, cwd=app_root)


def docker_image_prune(image_name: str) -> None:

    cmd_line = f"docker image prune -f --filter 'label={image_name}'"

    exec_cmd(cmd_line)


def docker_start(app_root: str, name: str, image: str, port: int) -> None:

    config_dir = os.path.join(app_root, "config")

    cmd_line = "docker run -d --restart unless-stopped"
    cmd_line += f" -p {port}:8080"
    cmd_line += f" -v {config_dir}:/app/config"
    cmd_line += f" --name {name}"
    cmd_line += f" {image}"

    exec_cmd(cmd_line)


def main() -> int:

    status = 1

    parser = argparse.ArgumentParser()

    script_root = os.path.abspath(os.path.dirname(sys.argv[0]))
    app_root = os.path.abspath(os.path.join(script_root, ".."))

    parser.add_argument("--name",
                        "-n",
                        type=str,
                        default=DEF_DOCKER_PROC_NAME,
                        help=f"Docker name. Default: {DEF_DOCKER_PROC_NAME}")

    parser.add_argument("--root",
                        "-r",
                        type=str,
                        default=app_root,
                        help=f"App root. Default: {app_root}")

    parser.add_argument("--image",
                        "-i",
                        type=str,
                        default=DEF_DOCKER_IMG_NAME,
                        help=f"Image name. Default: {DEF_DOCKER_IMG_NAME}")

    parser.add_argument("--port",
                        "-p",
                        type=int,
                        default=DEF_DOCKER_PORT,
                        help=f"Listening port. Default: {DEF_DOCKER_PORT}")

    parser.add_argument("--stop",
                        action="store_true",
                        help=f"stop the service and cleanup")

    args = parser.parse_args()

    try:
        docker_stop(args.name)

        if False == args.stop:
            docker_build_image(args.root, args.image)
            docker_image_prune(args.image)
            docker_start(app_root, args.name, args.image, args.port)
        status = 0
    except Exception as e:
        # something didn't work. clean everything up
        print(e)
        docker_stop(args.name)
        docker_build_image(args.root, args.image)
        docker_image_prune(args.image)

    return status


if __name__ == '__main__':

    status = main()

    if 0 != status:
        sys.exit(status)
