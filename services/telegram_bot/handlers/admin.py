"""
Обработчик админ-панели — извлечён из telegram_bot.py.
Управляет командами /admin, admin callbacks, интервалом и логами.
"""
import html as _html
from typing import TYPE_CHECKING, Optional

from .. import keyboards as kb

if TYPE_CHECKING:
    from ..core import TelegramBot


class AdminHandler:
    """Обработчик админ-панели и admin callbacks."""

    def __init__(self, bot: "TelegramBot") -> None:
        self._bot = bot

    # ── Public router ─────────────────────────────────────────────────────────

    async def handle(
        self,
        callback_id: str,
        user_id: str,
        chat_id: str,
        message_id: Optional[int],
        data: str,
    ) -> None:
        """Диспетчер admin callbacks — все требуют прав админа."""
        branches = {
            "admin_notify":   self._on_admin_notify,
            "admin_back":     self._on_admin_back,
            "admin_start":    self._on_admin_start,
            "admin_stop":     self._on_admin_stop,
            "admin_restart":  self._on_admin_restart,
            "admin_interval": self._on_admin_interval,
            "admin_logs":     self._on_admin_logs,
            "admin_status":   self._on_admin_status,
        }

        for prefix, handler in branches.items():
            if data == prefix:
                await handler(callback_id, user_id, chat_id, message_id)
                return

        await self._bot._answer_callback(callback_id, "❓ Неизвестная команда", alert=True)

    # ── /admin command ───────────────────────────────────────────────────────

    async def _handle_admin_command(
        self,
        user_id: str,
        chat_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        if user_id != self._bot.admin_id:
            await self._bot.send_message(chat_id, "❌ У вас нет доступа к админ-панели")
            return
        if not self._bot.parser_controller:
            await self._bot.send_message(chat_id, "❌ Контроллер парсера не инициализирован")
            return

        text = "🎛️ <b>Админ-панель парсера DNS</b>\n\nВыберите действие:"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_menu_keyboard(),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_menu_keyboard(),
            )

    # ── Admin callbacks ──────────────────────────────────────────────────────

    async def _on_admin_notify(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        s = self._bot.db.get_user_settings(user_id) if self._bot.db else {}
        text = "🔔 <b>Уведомления админа</b>\n\nВключите или выключите уведомления:"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_notify_keyboard(s),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_notify_keyboard(s),
            )

    async def _on_admin_back(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        text = "🎛️ <b>Админ-панель парсера DNS</b>\n\nВыберите действие:"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_menu_keyboard(),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_menu_keyboard(),
            )

    async def _on_admin_start(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
            return
        result = await self._bot.parser_controller.start()
        await self._bot._answer_callback(
            callback_id,
            "✅ Парсер запущен" if result else "⚠️ Парсер уже работает",
            alert=not result,
        )

    async def _on_admin_stop(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
            return
        result = await self._bot.parser_controller.stop()
        await self._bot._answer_callback(
            callback_id,
            "✅ Парсер остановлен" if result else "⚠️ Парсер уже остановлен",
            alert=not result,
        )

    async def _on_admin_restart(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
            return
        await self._bot.parser_controller.restart()
        await self._bot._answer_callback(callback_id, "✅ Парсер перезагружен")

    async def _on_admin_interval(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        self._bot._user_state.waiting_for_interval.add(user_id)
        await self._bot._answer_callback(callback_id, "")
        await self._bot.send_message(
            chat_id,
            "⏱️ <b>Установка интервала</b>\n\n"
            "Введите новый интервал в секундах (минимум 60):\n"
            "<i>Например: 1800</i>"
        )

    async def _on_admin_logs(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        await self._send_logs(chat_id)

    async def _on_admin_status(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Ошибка: контроллер не готов", alert=True)
            return
        await self._bot._answer_callback(callback_id, "")
        status = self._bot.parser_controller.get_status()
        await self._bot.send_message(chat_id, f"<b>📊 Статус парсера:</b>\n\n{status}")

    # ── Interval input ────────────────────────────────────────────────────────

    async def _handle_interval_input(self, user_id: str, chat_id: str, text: str) -> None:
        self._bot._user_state.waiting_for_interval.discard(user_id)
        try:
            interval = int(text.strip())
        except ValueError:
            await self._bot.send_message(chat_id, "❌ Некорректное значение. Введите число секунд")
            return
        if interval < 60 or interval > 86400:
            await self._bot.send_message(
                chat_id,
                "❌ Интервал должен быть от 60 до 86400 секунд (24 часа)"
            )
            return
        if not self._bot.parser_controller:
            await self._bot.send_message(chat_id, "❌ Контроллер не инициализирован")
            return
        if await self._bot.parser_controller.set_interval(interval):
            await self._bot.send_message(
                chat_id,
                f"✅ Интервал установлен на {interval} сек\n"
                "(будет применен после следующей итерации)"
            )
        else:
            await self._bot.send_message(chat_id, "❌ Ошибка при установке интервала")

    # ── Logs ─────────────────────────────────────────────────────────────────

    async def _send_logs(self, chat_id: str) -> None:
        try:
            log_file = "logs/app.log"
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            last_lines = lines[-100:] if len(lines) > 100 else lines
            logs_text = "".join(last_lines)
            logs_text = _html.escape(logs_text)

            if len(logs_text) > 4096:
                chunks = [logs_text[i:i + 4096] for i in range(0, len(logs_text), 4096)]
                for chunk in chunks:
                    await self._bot.send_message(chat_id, f"<pre>{chunk}</pre>")
            else:
                await self._bot.send_message(
                    chat_id,
                    f"<pre>{logs_text}</pre>" if logs_text else "📭 Логи пусты"
                )
        except FileNotFoundError:
            await self._bot.send_message(chat_id, "📭 Логи не найдены. Файл logs/app.log отсутствует.")
        except Exception:
            await self._bot.send_message(chat_id, "📭 Логи не найдены")
