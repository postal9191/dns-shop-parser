"""
services/telegram_bot — рефакторенный пакет Telegram-бота.
Бывший монолитный telegram_bot.py (~1921 стр.) разбит на модули.
"""
from .core import TelegramBot
from .state import ReportState, UserState

__all__ = [
    "TelegramBot",
    "init_telegram_bot",
    "get_telegram_bot",
    "ReportState",
    "UserState",
]

# ─── Singleton globals (восстанавливаем поведение старого telegram_bot.py) ────

telegram_bot: "TelegramBot | None" = None


def init_telegram_bot(db_manager=None, parser_controller=None) -> "TelegramBot":
    global telegram_bot
    telegram_bot = TelegramBot(db_manager, parser_controller)
    return telegram_bot


def get_telegram_bot() -> "TelegramBot | None":
    return telegram_bot