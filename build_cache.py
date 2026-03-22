#!/usr/bin/env python3
import json

from pathlib import Path
from typing import Literal, Any
import argparse
import subprocess
import shutil
import sys
import os
import datetime

CACHE_NAME: str = "ml-rocm"

class InvalidDataStructureError(Exception):
    """Raised when a parser is expecting a specific data type/structure but recieves something else"""
    pass

def log(level: str, msg: str, **kwargs: Any) -> None:
    # ANSI escape codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    COLORS = {
        "ERROR": "\033[31m",  # Red
        "WARN": "\033[33m",  # Yellow
        "INFO": "\033[32m",  # Green
        "DEBUG": "\033[34m",  # Blue
        "TRACE": "\033[37m",  # White
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


def check_env(no_cachix:bool=False):
    """makes sure that the current environment is compatible"""
    # make sure auth token is present in environment
    if not no_cachix and not os.environ.get("CACHIX_AUTH_TOKEN"):
        log("ERROR", "`CACHIX_AUTH_TOKEN` env variable not found, cannot proceed")
        sys.exit(1)
    # ensure cachix is available
    if not no_cachix and not shutil.which("cachix"):
        log("ERROR", "`cachix` binary not found, cannot proceed")
        sys.exit(1)
    # ensure nix is available
    if not shutil.which("nix"):
        log("ERROR", "`nix` binary not found, cannot proceed")
        sys.exit(1)


def mk_pytarget(pkg: str, pyv: str) -> str:
    """given a package and a python version (in `3xx` format. ie `307` or `312`), create a package target to pass to the nix build function"""
    return f".#{pkg}-py{pyv}"

def get_flake_targets(group: str = "all", system: str = "x86_64-linux") -> list[str]:
    """scans the flake in the current working directory for exported packages and returns them"""
    command = ("nix", "eval", f".#buildGroups.{system}.{group}", "--json")
    scan = subprocess.run(command, check=True, capture_output=True, text=True)
    targets: list[str] = json.loads(scan.stdout)
    if not isinstance(targets, list):
        raise 
    return targets
    

def build_package_batch(targets: list[str], revision: str | None = None, no_cachix: bool = False ):
    """builds a set of nix packages"""
    log("INFO", "Starting batch...", targets=", ".join(targets))
    # TODO: Respect args.no_cachix
    for pkg in targets:
        command = [
            "nix",
            "build",
            "--keep-going",
            "--print-build-logs",
        ]
        # prepend cachix build wrapper if need be
        if not no_cachix:
            command = ["cachix",
            "watch-exec",
            CACHE_NAME,
            "--"] + command
        
        # inject revision if specified
        rev = revision or os.environ.get("NIXPKGS_REV")
        if rev:
            log("WARN", "Overriding nixpkgs revision", revision=rev)
            command.extend(
                ["--override-input", "nixpkgs", f"github:nixos/nixpkgs/{rev}"]
            )

        log("INFO", "building package", package=pkg)
        command.append(f".#{pkg}")

        try:
            subprocess.run(command, check=True)
            if no_cachix:
                log("INFO", f"Successfully built {pkg}")
            else:    
                log("INFO", f"Successfully built and cached {pkg}")
        except subprocess.CalledProcessError as err:
            log("ERROR", f"Failed to build {pkg}", exit_code=str(err.returncode))


def build_arg_parser() -> argparse.ArgumentParser:
    """builds an argparse parser for the script"""
    parser = argparse.ArgumentParser()
    # parameter to overwrite the nixpkgs revision to be built against
    parser.add_argument(
        "-R",
        "--revision",
        help="Override the nixpkgs revision with the provided git commit id",
    )
    # parameter to select the package group to be built
    parser.add_argument(
        "-G",
        "--group",
        default="all",
        help="Specifies the package group to be built",
    )
    # option for a test build
    parser.add_argument(
        "-T",
        "--test",
        help="Build and push a test artifact to verify environment configuration",
        action="store_true",
    )
    # option to disable cachix (mainly for testing)
    parser.add_argument(
        "-N",
        "--no-cachix",
        help="Do not call any cachix functions while building",
        action="store_true",
    )
    return parser


def main() -> None:
    """the main logic loop"""
    parser = build_arg_parser()
    args = parser.parse_args()

    # override cli args if env var is present
    if os.environ.get("NIX_ML_ROCM_NO_CACHIX") == "1":
        args.no_cachix=True

    # ensure environment is configured
    check_env(no_cachix=args.no_cachix)

    # check for arguments that override the nixpkgs revision
    rev: str | None = args.revision
    if args.revision:
        log("INFO", f"building python packages against nixpkgs@{args.revision}")
    # check for arguments to run a test build
    if args.test:
        log("INFO", "Running diagnostic test build...")
        build_package_batch(["test-artifact"], revision=rev, no_cachix=args.no_cachix)
        return
    
    # TODO: refactor package indexing to pull directly from flake file
    if args.group != "all":
        log("INFO", f"Building package group \"{args.group}\"")
    else:
        log("INFO", f"Building all packages")
    
    try:
        avail_targets = get_flake_targets(group=args.group)
    except subprocess.CalledProcessError as err:
        log("ERROR", "error getting package group", group=args.group, error=str(err))
        exit(1)

    try:
        # TODO: refactor package batching and error handling (iteratively build and gracefully fail)
        build_package_batch(avail_targets, revision=rev,no_cachix=args.no_cachix)
    except subprocess.CalledProcessError as err:
        attempted_ids = ", ".join(avail_targets)
        log("ERROR", "error building packages", targets=attempted_ids, error=str(err))


if __name__ == "__main__":
    main()
