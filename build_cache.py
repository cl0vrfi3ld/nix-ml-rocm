#!/usr/bin/env python3

from pathlib import Path
import subprocess
import shutil
import sys
import os
import datetime
from typing import Literal, Any

CACHE_NAME: str = "ml-rocm"
SUPPORTED_PYTHON_VERSIONS = Literal["311", "312"]  # TODO: add 3.13 support
PYTHON_VERSIONS: list[SUPPORTED_PYTHON_VERSIONS] = [
    "311", "312"]  # TODO: add 3.13 support
PYTHON_PACKAGES: list[str] = ["torch", "torchaudio", "torchvision"]


def log(level: str, msg: str, **kwargs: Any) -> None:
    # ANSI escape codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    COLORS = {
        "ERROR": "\033[31m",   # Red
        "WARN": "\033[33m",    # Yellow
        "INFO": "\033[32m",    # Green
        "DEBUG": "\033[34m",   # Blue
        "TRACE": "\033[37m",   # White
    }

    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    color = COLORS.get(level, RESET)

    # Format key-value pairs with colored keys
    kv_pairs = " ".join(f"\033[36m{k}\033[0m={v}" for k, v in kwargs.items())

    # Build the final message
    ts_str = f"{DIM}{timestamp}{RESET}"
    level_str = f"{BOLD}{color}{level:<5}{RESET}"

    if kv_pairs:
        out_msg = f"{ts_str}  {level_str} {msg} {kv_pairs}"
    else:
        out_msg = f"{ts_str}  {level_str} {msg}"

    file = sys.stderr if level in ["ERROR", "WARN"] else sys.stdout
    print(out_msg, file=file)


def parse_apply_dotenv(file_path: Path) -> dict[str, str]:
    """ parse a .env format file """
    with open(file_path, mode="r")as fh:
        lines = fh.readlines()
    parsed: dict[str, str] = {}
    for l in lines:
        l = l.strip()
        if not l or l.startswith("#"): continue # Skip empty lines and comments
        k, v = l.split("=", 1)
        _ = parsed.setdefault(k, v)
    
    log("INFO", "applying parsed values")

    for name, value in parsed.items():
        os.environ[name] = value
        log("INFO", f"set {name}")

    return parsed


def check_env():
    """ makes sure that the current environment is compatible """
    # ensure cachix is available
    if not shutil.which("cachix"):
        log("ERROR", "`cachix` binary not found, cannot proceed")
        sys.exit(1)
    # ensure nix is available
    if not shutil.which("nix"):
        log("ERROR", "`nix` binary not found, cannot proceed")
        sys.exit(1)
    # find a .env file
    dotenvf = Path(".env")
    if dotenvf.exists():
        log("INFO", "found .env file", path=dotenvf.absolute())
        # parse found file
        dotenv_vars = parse_apply_dotenv(dotenvf)        


def mk_target(pkg: str, pyv: SUPPORTED_PYTHON_VERSIONS) -> str:
    """ given a package and a python version, create a package target to pass to the nix build function """
    return f".#{pkg}-py{pyv}"


def build_package_batch(targets: list[str]):
    """ build all packages for the python ecosystem """
    command = [
        "cachix", "watch-exec", CACHE_NAME, "--",
        "nix", "build",
        "--keep-going",
        "--print-build-logs"
    ] + targets
    attempted_ids = ", ".join(targets)
    log("INFO", "building packages", targets=attempted_ids)
    _ = subprocess.run(command, check=True)


def main() -> None:
    """ the main logic loop """
    check_env()
    
    # check for arguments to run a test build
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        log("INFO", "Running diagnostic test build...")
        build_package_batch([".#test-artifact"])
        return
    
    log("INFO", "building python packages")
    py_pkg_ids: list[str] = []
    for v in PYTHON_VERSIONS:
        for p in PYTHON_PACKAGES:
            py_pkg_ids.append(mk_target(pkg=p, pyv=v))

    try:
        build_package_batch(py_pkg_ids)
    except subprocess.CalledProcessError as err:
        attempted_ids = ", ".join(py_pkg_ids)
        log("ERROR", "error building packages",
            targets=attempted_ids, error=str(err))

if __name__ == "__main__":
    main()
