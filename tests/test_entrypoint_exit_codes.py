import sys

import pytest

from dns_shop_parser.entrypoints import parser as parser_entrypoint
from dns_shop_parser.entrypoints import run as run_entrypoint


@pytest.mark.asyncio
async def test_parser_main_returns_nonzero_on_failure(monkeypatch):
    """По умолчанию провал парсинга = ненулевой exit code."""
    class FakeMonitor:
        def __init__(self, city_slug=None):
            self.city_slug = city_slug

        async def run_once(self):
            return False

    monkeypatch.setattr(parser_entrypoint, "DNSMonitorBrowserless", FakeMonitor)
    monkeypatch.setattr(sys, "argv", ["dns-parser-once"])

    assert await parser_entrypoint.main() == 1


@pytest.mark.asyncio
async def test_parser_main_keeps_zero_with_lenient_flag(monkeypatch):
    """--lenient-exit-code позволяет вернуть 0 при провале."""
    class FakeMonitor:
        def __init__(self, city_slug=None):
            self.city_slug = city_slug

        async def run_once(self):
            return False

    monkeypatch.setattr(parser_entrypoint, "DNSMonitorBrowserless", FakeMonitor)
    monkeypatch.setattr(sys, "argv", ["dns-parser-once", "--lenient-exit-code"])

    assert await parser_entrypoint.main() == 0


@pytest.mark.asyncio
async def test_parser_main_returns_zero_on_success(monkeypatch):
    """Успешный парсинг = exit code 0."""
    class FakeMonitor:
        def __init__(self, city_slug=None):
            self.city_slug = city_slug

        async def run_once(self):
            return True

    monkeypatch.setattr(parser_entrypoint, "DNSMonitorBrowserless", FakeMonitor)
    monkeypatch.setattr(sys, "argv", ["dns-parser-once"])

    assert await parser_entrypoint.main() == 0


@pytest.mark.asyncio
async def test_runner_passes_city_slug(monkeypatch):
    """run_parser передаёт --city-slug без --strict-exit-code."""
    called = {}

    async def fake_run_module(module, log_name, args=None):
        called["module"] = module
        called["args"] = args
        return True

    monkeypatch.setattr(run_entrypoint, "_run_module", fake_run_module)

    assert await run_entrypoint.run_parser("moscow") is True
    assert called["module"] == "dns_shop_parser.entrypoints.parser"
    assert called["args"] == ["--city-slug", "moscow"]
