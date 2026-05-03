import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest


def _load_monitor_class():
    module_path = Path(__file__).resolve().parents[1] / "parser.py"
    spec = importlib.util.spec_from_file_location("dns_monitor_entrypoint", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DNSMonitorBrowserless


@pytest.mark.asyncio
async def test_process_category_passes_expected_count_to_uuid_fetch():
    DNSMonitorBrowserless = _load_monitor_class()
    monitor = DNSMonitorBrowserless.__new__(DNSMonitorBrowserless)
    monitor.city_slug = "moscow"

    monitor.db = MagicMock()
    monitor.db.get_category_state.return_value = None

    monitor.parser = MagicMock()
    monitor.parser.fetch_product_uuids = AsyncMock(side_effect=[[], []])

    cat = MagicMock()
    cat.id = "category-1"
    cat.label = "Category"
    cat.count = 7

    result = await monitor._process_category(
        cat,
        1,
        1,
        False,
        [],
        [],
    )

    assert result == (0, 0)
    monitor.parser.fetch_product_uuids.assert_has_awaits(
        [
            call("category-1", expected_count=7, status=0),
            call("category-1", expected_count=7, status=1),
        ]
    )
