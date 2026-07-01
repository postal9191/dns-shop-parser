import sys

import pytest

from dns_shop_parser.entrypoints import parser as parser_entrypoint
from dns_shop_parser.entrypoints import run as run_entrypoint


@pytest.mark.asyncio
async def test_parser_main_keeps_zero_exit_without_strict_flag(monkeypatch):
    class FakeMonitor:
        def __init__(self, city_slug=None):
            self.city_slug = city_slug

        async def run_once(self):
            return False

    monkeypatch.setattr(parser_entrypoint, "DNSMonitorBrowserless", FakeMonitor)
    monkeypatch.setattr(sys, "argv", ["dns-parser-once"])

    assert await parser_entrypoint.main() == 0


@pytest.mark.asyncio
async def test_parser_main_returns_nonzero_with_strict_flag(monkeypatch):
    class FakeMonitor:
        def __init__(self, city_slug=None):
            self.city_slug = city_slug

        async def run_once(self):
            return False

    monkeypatch.setattr(parser_entrypoint, "DNSMonitorBrowserless", FakeMonitor)
    monkeypatch.setattr(sys, "argv", ["dns-parser-once", "--strict-exit-code"])

    assert await parser_entrypoint.main() == 1


@pytest.mark.asyncio
async def test_runner_uses_strict_parser_exit_code(monkeypatch):
    called = {}

    async def fake_run_module(module, log_name, args=None):
        called["module"] = module
        called["args"] = args
        return True

    monkeypatch.setattr(run_entrypoint, "_run_module", fake_run_module)

    assert await run_entrypoint.run_parser("moscow") is True
    assert called["module"] == "dns_shop_parser.entrypoints.parser"
    assert called["args"] == ["--strict-exit-code", "--city-slug", "moscow"]
