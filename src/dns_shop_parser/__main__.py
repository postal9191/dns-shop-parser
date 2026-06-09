"""Command-line dispatcher for the DNS Shop parser package."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from dns_shop_parser.entrypoints import bot_only, parser, run

_COMMANDS: dict[str, Callable[[], Awaitable[None]]] = {
    "run": run.main,
    "parse": parser.main,
    "bot": bot_only.main,
}


async def _dispatch(command: str, command_args: list[str]) -> None:
    old_argv = sys.argv[:]
    try:
        sys.argv = [f"dns-parser-{command}", *command_args]
        await _COMMANDS[command]()
    finally:
        sys.argv = old_argv


def _print_help() -> None:
    arg_parser = argparse.ArgumentParser(
        prog="python -m dns_shop_parser",
        description="DNS Shop parser command dispatcher.",
    )
    arg_parser.add_argument(
        "command",
        nargs="?",
        choices=tuple(_COMMANDS),
        default="run",
        help="Command to run: run=parser+bot+scheduler, parse=single parse, bot=Telegram polling only.",
    )
    arg_parser.print_help()


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        command = "run"
        command_args: list[str] = []
    elif argv[0] in ("-h", "--help"):
        _print_help()
        return
    elif argv[0] in _COMMANDS:
        command = argv[0]
        command_args = argv[1:]
    else:
        _print_help()
        raise SystemExit(f"unknown command: {argv[0]}")

    asyncio.run(_dispatch(command, command_args))


def run_cli() -> None:
    asyncio.run(run.main())


def parse_cli() -> None:
    asyncio.run(parser.main())


def bot_cli() -> None:
    asyncio.run(bot_only.main())


if __name__ == "__main__":
    main()
