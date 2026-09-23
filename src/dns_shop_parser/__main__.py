"""Command-line dispatcher for the DNS Shop parser package."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from dns_shop_parser.entrypoints import bot_only, parser, run
from dns_shop_parser.entrypoints.preflight import run_preflight

_COMMANDS: dict[str, Callable[[], Awaitable[int | None]]] = {
    "run": run.main,
    "parse": parser.main,
    "bot": bot_only.main,
}


async def _dispatch(command: str, command_args: list[str]) -> int:
    old_argv = sys.argv[:]
    try:
        sys.argv = [f"dns-parser-{command}", *command_args]
        result = await _COMMANDS[command]()
        return result if isinstance(result, int) else 0
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
    elif argv[0] == "preflight":
        raise SystemExit(preflight_cli(argv[1:]))
    elif argv[0] in _COMMANDS:
        command = argv[0]
        command_args = argv[1:]
    else:
        _print_help()
        raise SystemExit(f"unknown command: {argv[0]}")

    raise SystemExit(asyncio.run(_dispatch(command, command_args)))


def preflight_cli(argv: list[str] | None = None) -> int:
    parser_ = argparse.ArgumentParser(prog="preflight")
    parser_.add_argument("--db", default="dns_monitor.db")
    parser_.add_argument("--state-dir", default=".")
    parser_.add_argument("--log-dir", default="logs")
    parser_.add_argument("--backup-dir", default="backups")
    parser_.add_argument("--no-node", action="store_true")
    args = parser_.parse_args(argv)
    result = run_preflight(db_path=args.db, state_dir=args.state_dir, log_dir=args.log_dir, backup_dir=args.backup_dir, checks={"node": not args.no_node})
    print(result.summary, file=sys.stderr if not result.ok else sys.stdout)
    return 0 if result.ok else 1


def run_cli() -> None:
    asyncio.run(run.main())


def parse_cli() -> None:
    raise SystemExit(asyncio.run(parser.main()))


def bot_cli() -> None:
    asyncio.run(bot_only.main())


if __name__ == "__main__":
    main()
