from unittest.mock import AsyncMock, MagicMock

import pytest

from dns_shop_parser.config import config
from dns_shop_parser.services.telegram_bot.handlers.admin import AdminHandler


@pytest.mark.asyncio
async def test_send_logs_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "telegram_token", "123456789:TEST_SECRET_TOKEN_VALUE", raising=False)
    monkeypatch.setattr(config, "proxy_password", "proxy-secret", raising=False)

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text(
        "\n".join([
            "TELEGRAM_TOKEN=123456789:TEST_SECRET_TOKEN_VALUE",
            "PROXY_PASSWORD=proxy-secret",
            "Cookie: session=secret-cookie",
            "Authorization: Bearer secret-auth",
            "x-csrf-token: secret-csrf",
            "proxy=http://user:proxy-secret@proxy.example.com:10000",
            "https://api.telegram.org/bot123456789:TEST_SECRET_TOKEN_VALUE/sendMessage",
        ]),
        encoding="utf-8",
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    handler = AdminHandler(bot)

    await handler._send_logs("admin-chat")

    sent_text = bot.send_message.call_args.args[1]
    assert "TEST_SECRET_TOKEN_VALUE" not in sent_text
    assert "proxy-secret" not in sent_text
    assert "secret-cookie" not in sent_text
    assert "secret-auth" not in sent_text
    assert "secret-csrf" not in sent_text
    assert "[REDACTED]" in sent_text
