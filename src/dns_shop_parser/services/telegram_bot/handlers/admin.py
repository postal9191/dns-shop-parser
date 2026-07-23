"""
Обработчик админ-панели — извлечён из telegram_bot.py.
Управляет командами /admin, admin callbacks, интервалом и логами.
"""
import asyncio
import html as _html
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from dns_shop_parser.config import config
from dns_shop_parser.data.cities import SLUG_TO_CITY
from dns_shop_parser.utils.logger import logger
from .. import keyboards as kb

if TYPE_CHECKING:
    from ..core import TelegramBot

# Корень проекта: от handlers/admin.py → parents[5] = dns/
_PROJECT_DIR = Path(__file__).resolve().parents[5]


class AdminHandler:
    """Обработчик админ-панели и admin callbacks."""

    _PLAN_TYPES = {"free", "pro", "super"}

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
            "admin_rights":   self._on_admin_rights,
            "admin_rights_cancel": self._on_admin_rights_cancel,
            "admin_rights_save": self._on_admin_rights_save,
            "admin_rights_noop": self._on_admin_rights_noop,
            "admin_start":    self._on_admin_start,
            "admin_stop":     self._on_admin_stop,
            "admin_restart":  self._on_admin_restart,
            "admin_interval": self._on_admin_interval,
            "admin_logs":     self._on_admin_logs,
            "admin_status":   self._on_admin_status,
            "admin_force_parse": self._on_admin_force_parse,
            "admin_cities":    self._on_admin_cities,
            "admin_update":    self._on_admin_update,
            "admin_update_latest": self._on_admin_update_latest,
            "admin_update_rollback_list": self._on_admin_update_rollback_list,
        }

        for prefix, handler in branches.items():
            if data == prefix:
                await handler(callback_id, user_id, chat_id, message_id)
                return

        if data.startswith("admin_force_city:"):
            await self._on_admin_force_city(callback_id, user_id, chat_id, message_id, data)
            return
        if data.startswith("admin_city_toggle:"):
            await self._on_admin_city_toggle(callback_id, user_id, chat_id, message_id, data)
            return
        if data.startswith("admin_update_rollback:"):
            await self._on_admin_update_rollback(callback_id, user_id, chat_id, message_id, data)
            return
        if data.startswith("admin_rights_page:"):
            await self._on_admin_rights_page(callback_id, user_id, chat_id, message_id, data)
            return
        if data.startswith("admin_rights_pick:"):
            await self._on_admin_rights_pick(callback_id, user_id, chat_id, message_id, data)
            return
        if data.startswith("admin_rights_set:"):
            await self._on_admin_rights_set(callback_id, user_id, chat_id, message_id, data)
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

    async def _on_admin_force_parse(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        text = "🏙 <b>Принудительный парсинг</b>\n\nВыберите город:"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_force_city_keyboard(),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_force_city_keyboard(),
            )

    async def _on_admin_force_city(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "Ошибка: контроллер не готов", alert=True)
            return
        try:
            city_slug = data.split(":", 1)[1]
        except IndexError:
            await self._bot._answer_callback(callback_id, "Неизвестный город", alert=True)
            return

        result = await self._bot.parser_controller.enqueue_city_parse(city_slug)
        city_name = SLUG_TO_CITY.get(city_slug, city_slug)
        if result.status == "queued":
            await self._bot._answer_callback(callback_id, f"Добавлено в очередь: {city_name}")
            return
        if result.status == "duplicate":
            await self._bot._answer_callback(callback_id, f"Уже в очереди или выполняется: {city_name}", alert=True)
            return
        if result.status == "city_disabled":
            await self._bot._answer_callback(callback_id, f"⚠️ {city_name}: парсинг отключён", alert=True)
            return
        if result.status == "runner_missing":
            await self._bot._answer_callback(callback_id, "Runner парсера не настроен", alert=True)
            return
        await self._bot._answer_callback(callback_id, "Неизвестный город", alert=True)

    async def _on_admin_cities(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Контроллер не готов", alert=True)
            return
        await self._bot._answer_callback(callback_id, "")
        disabled = self._bot.parser_controller.get_disabled_cities()
        text = "🏙 <b>Управление городами</b>\n\n✅ — парсинг включён\n❌ — парсинг отключён"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_cities_keyboard(disabled),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_cities_keyboard(disabled),
            )

    async def _on_admin_city_toggle(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        if not self._bot.parser_controller:
            await self._bot._answer_callback(callback_id, "❌ Контроллер не готов", alert=True)
            return
        try:
            city_slug = data.split(":", 1)[1]
        except IndexError:
            await self._bot._answer_callback(callback_id, "Ошибка", alert=True)
            return
        now_enabled = self._bot.parser_controller.toggle_city(city_slug)
        city_name = SLUG_TO_CITY.get(city_slug, city_slug)
        await self._bot._answer_callback(
            callback_id,
            f"{city_name}: {'включён' if now_enabled else 'отключён'}",
        )
        disabled = self._bot.parser_controller.get_disabled_cities()
        text = "🏙 <b>Управление городами</b>\n\n✅ — парсинг включён\n❌ — парсинг отключён"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_cities_keyboard(disabled),
            )

    # ── Server update handlers ──────────────────────────────────────────────

    async def _on_admin_update(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        """Показывает подменю обновления сервера."""
        await self._bot._answer_callback(callback_id, "")
        current = self._git_current_info()
        text = (
            "🚀 <b>Обновление сервера</b>\n\n"
            f"Текущий коммит: <code>{current}</code>\n\n"
            "Выберите действие:"
        )
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_update_keyboard(),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_update_keyboard(),
            )

    async def _on_admin_update_latest(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        """Запускает обновление на последний master в фоне."""
        await self._bot._answer_callback(callback_id, "🔄 Запускаю обновление...")
        asyncio.create_task(self._run_server_update(chat_id, action="update"))

    async def _on_admin_update_rollback_list(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        """Показывает список последних коммитов для отката."""
        await self._bot._answer_callback(callback_id, "")
        commits = await self._git_log_recent()
        if not commits:
            await self._bot.send_message(chat_id, "❌ Не удалось получить список коммитов")
            return
        text = "⏪ <b>Откат на предыдущий коммит</b>\n\nВыберите коммит:"
        if message_id:
            await self._bot.edit_message_text(
                chat_id, message_id, text,
                reply_markup=kb._build_admin_rollback_commits_keyboard(commits),
            )
        else:
            await self._bot.send_message(
                chat_id, text,
                reply_markup=kb._build_admin_rollback_commits_keyboard(commits),
            )

    async def _on_admin_update_rollback(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        """Запускает откат на указанный коммит в фоне."""
        try:
            ref = data.split(":", 1)[1]
        except IndexError:
            await self._bot._answer_callback(callback_id, "Ошибка", alert=True)
            return
        await self._bot._answer_callback(callback_id, f"⏪ Откатываю на {ref}...")
        asyncio.create_task(self._run_server_update(chat_id, action="rollback", ref=ref))

    # ── Git helpers ──────────────────────────────────────────────────────────

    def _git_current_info(self) -> str:
        """Возвращает текущий короткий хеш и сообщение коммита."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=str(_PROJECT_DIR), capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    async def _git_log_recent(self, count: int = 5) -> list[dict]:
        """Возвращает последние N коммитов [{short, message}]."""
        def _run():
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", f"-{count}", "--skip=1"],
                    cwd=str(_PROJECT_DIR), capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    return []
                commits = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        commits.append({"short": parts[0], "message": parts[1]})
                return commits
            except Exception:
                return []

        return await asyncio.to_thread(_run)

    # ── Update/rollback background task ──────────────────────────────────────

    async def _run_server_update(
        self, chat_id: str, action: str, ref: str | None = None,
    ) -> None:
        """Выполняет обновление/откат сервера в фоновой задаче.

        Безопасность: каждая шаг проверяется, при ошибке — сообщение админу
        и отмена оставшихся шагов. Перезапуск через systemd в самом конце.
        """
        admin_id = self._bot.admin_id
        if not admin_id:
            return

        async def notify(text: str) -> None:
            await self._bot.send_admin_message(admin_id, text)

        # Шаг 0: проверяем git
        await notify(f"🔄 <b>Обновление сервера</b> — начато ({action})")

        def _check_git():
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=str(_PROJECT_DIR), capture_output=True, text=True, timeout=10,
                )
                return r.returncode == 0 and "true" in r.stdout
            except Exception:
                return False

        if not await asyncio.to_thread(_check_git):
            await notify("❌ Не git-репозиторий. Обновление отменено.")
            return

        # Шаг 1: git fetch
        await notify("📡 <code>git fetch --all --tags --prune</code>...")
        ok = await self._run_subprocess(["git", "fetch", "--all", "--tags", "--prune"])
        if not ok:
            await notify("❌ <code>git fetch</code> завершился с ошибкой. Обновление отменено.")
            return

        # Шаг 2: git pull (update) или git checkout (rollback)
        current_ref = await self._run_subprocess_output(["git", "rev-parse", "--short", "HEAD"])

        if action == "update":
            await notify("⬇️ <code>git pull --ff-only</code>...")
            ok = await self._run_subprocess(["git", "pull", "--ff-only"])
            if not ok:
                await notify(
                    "❌ <code>git pull --ff-only</code> не удался.\n"
                    "Возможно, есть конфликты. Обновление отменено.\n"
                    "Сервер продолжает работать на текущем коммите."
                )
                return
        elif action == "rollback" and ref:
            await notify(f"⏪ <code>git checkout --detach {ref}</code>...")
            ok = await self._run_subprocess(["git", "checkout", "--detach", ref])
            if not ok:
                await notify(f"❌ Не удалось переключиться на <code>{ref}</code>. Откат отменён.")
                return
        else:
            await notify("❌ Неизвестное действие. Отмена.")
            return

        new_ref = await self._run_subprocess_output(["git", "rev-parse", "--short", "HEAD"])
        await notify(f"✅ Код обновлён: <code>{current_ref}</code> → <code>{new_ref}</code>")

        # Шаг 3: обновление pip зависимостей
        venv_python = _PROJECT_DIR / "venv" / "bin" / "python3"
        if not venv_python.exists():
            venv_python = _PROJECT_DIR / "venv" / "bin" / "python"
        if venv_python.exists():
            req_file = _PROJECT_DIR / "requirements.txt"
            if req_file.exists():
                await notify("📦 <code>pip install -r requirements.txt</code>...")
                ok = await self._run_subprocess([
                    str(venv_python), "-m", "pip", "install",
                    "-r", str(req_file), "--quiet",
                ])
                if not ok:
                    await notify("⚠️ pip install завершился с ошибкой, продолжаем...")

        # Шаг 4: обновление npm зависимостей
        if (_PROJECT_DIR / "package.json").exists():
            await notify("📦 <code>npm install</code>...")
            ok = await self._run_subprocess(["npm", "install", "--quiet"], cwd=str(_PROJECT_DIR))
            if not ok:
                await notify("⚠️ npm install завершился с ошибкой, продолжаем...")

        # Шаг 5: перезапуск через systemd
        service_file = Path("/etc/systemd/system/dns-parser.service")
        if service_file.exists():
            await notify("🔄 Перезапускаю systemd сервис...")
            ok = await self._run_subprocess(["sudo", "systemctl", "restart", "dns-parser"])
            if ok:
                await notify("✅ Сервис перезапущен! Бот перезагрузится через несколько секунд.")
                return
            else:
                await notify("⚠️ systemd restart не удался, пробую перезапуск вручную...")

        # Fallback: если нет systemd, пробуем перезапустить текущий процесс
        await notify("🔄 Перезапускаю процесс...")
        await notify("✅ Обновление завершено! Перезапуск...")

        # Даём время отправить сообщение перед перезапуском
        await asyncio.sleep(2)

        # Перезапуск через os.execv (замена текущего процесса)
        os.execv(sys.executable, [sys.executable, "-m", "dns_shop_parser", "run"])

    async def _run_subprocess(
        self, cmd: list[str], cwd: str | None = None, timeout: int = 120,
    ) -> bool:
        """Запускает subprocess в executor. Возвращает True при успехе."""
        def _run():
            try:
                result = subprocess.run(
                    cmd,
                    cwd=cwd or str(_PROJECT_DIR),
                    capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode != 0:
                    logger.error(
                        "[ADMIN UPDATE] %s exit=%d stderr=%s",
                        " ".join(cmd), result.returncode, result.stderr[:500],
                    )
                return result.returncode == 0
            except subprocess.TimeoutExpired:
                logger.error("[ADMIN UPDATE] %s timeout", " ".join(cmd))
                return False
            except Exception as e:
                logger.error("[ADMIN UPDATE] %s error: %s", " ".join(cmd), e)
                return False

        return await asyncio.to_thread(_run)

    async def _run_subprocess_output(
        self, cmd: list[str], cwd: str | None = None, timeout: int = 15,
    ) -> str:
        """Запускает subprocess и возвращает stdout.strip()."""
        def _run():
            try:
                result = subprocess.run(
                    cmd,
                    cwd=cwd or str(_PROJECT_DIR),
                    capture_output=True, text=True, timeout=timeout,
                )
                return result.stdout.strip() if result.returncode == 0 else ""
            except Exception:
                return ""

        return await asyncio.to_thread(_run)

    def _rights_state(self, admin_id: str) -> tuple[list[dict], dict[str, str], int]:
        us = self._bot._user_state
        return (
            us.admin_rights_users.setdefault(admin_id, []),
            us.admin_rights_draft.setdefault(admin_id, {}),
            us.admin_rights_page.get(admin_id, 0),
        )

    def _sort_rights_users(self, users: list[dict]) -> list[dict]:
        priority = {"super": 0, "pro": 1, "free": 2}
        return sorted(
            users,
            key=lambda u: (
                priority.get(u.get("plan_type", "free"), 3),
                (u.get("username") or "").lower(),
                str(u.get("user_id")),
            ),
        )

    def _find_rights_user(self, admin_id: str, target_user_id: str) -> dict | None:
        users, _, _ = self._rights_state(admin_id)
        return next((u for u in users if str(u.get("user_id")) == target_user_id), None)

    async def _refresh_rights_users(self, admin_id: str) -> list[dict]:
        if not self._bot.db:
            return []
        users = await self._bot._db_call(self._bot.db.get_active_users_with_plan_types)
        users = self._sort_rights_users(users)
        self._bot._user_state.admin_rights_users[admin_id] = users
        self._bot._user_state.admin_rights_draft.setdefault(admin_id, {})
        self._bot._user_state.admin_rights_page.setdefault(admin_id, 0)
        return users

    def _format_rights_list_text(self, users: list[dict], draft: dict[str, str]) -> str:
        changed = sum(
            1 for user in users
            if draft.get(str(user.get("user_id")), user.get("plan_type", "free")) != user.get("plan_type", "free")
        )
        return (
            "👤 <b>Права пользователей</b>\n\n"
            "Выберите пользователя, измените plan_type и нажмите <b>Сохранить</b>.\n"
            f"Активных пользователей: {len(users)}\n"
            f"Несохранённых изменений: {changed}"
        )

    def _format_rights_user_text(self, user: dict, selected_plan: str) -> str:
        username = user.get("username") or "-"
        if username != "-" and not username.startswith("@"):
            username = f"@{username}"
        return (
            "👤 <b>Права пользователя</b>\n\n"
            f"UserName: <b>{_html.escape(username)}</b>\n"
            f"UserId: <code>{_html.escape(str(user.get('user_id')))}</code>\n"
            f"Текущий plan_type: <b>{_html.escape(str(user.get('plan_type', 'free')))}</b>\n"
            f"Выбранный plan_type: <b>{_html.escape(selected_plan)}</b>"
        )

    async def _show_admin_rights_list(
        self,
        chat_id: str,
        message_id: Optional[int],
        admin_id: str,
        *,
        refresh: bool = False,
    ) -> None:
        if refresh or admin_id not in self._bot._user_state.admin_rights_users:
            users = await self._refresh_rights_users(admin_id)
        else:
            users, _, _ = self._rights_state(admin_id)
        _, draft, page = self._rights_state(admin_id)
        text = self._format_rights_list_text(users, draft)
        reply_markup = kb._build_admin_rights_users_keyboard(users, page, draft)
        if message_id:
            await self._bot.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
        else:
            await self._bot.send_message(chat_id, text, reply_markup=reply_markup)

    async def _on_admin_rights(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")
        await self._show_admin_rights_list(chat_id, message_id, user_id, refresh=True)

    async def _on_admin_rights_noop(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        await self._bot._answer_callback(callback_id, "")

    async def _on_admin_rights_page(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        try:
            page = max(0, int(data.split(":", 1)[1]))
        except (IndexError, ValueError):
            await self._bot._answer_callback(callback_id, "Ошибка страницы", alert=True)
            return
        self._bot._user_state.admin_rights_page[user_id] = page
        await self._bot._answer_callback(callback_id, "")
        await self._show_admin_rights_list(chat_id, message_id, user_id)

    async def _on_admin_rights_pick(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        target_user_id = data.split(":", 1)[1]
        if user_id not in self._bot._user_state.admin_rights_users:
            await self._refresh_rights_users(user_id)
        target = self._find_rights_user(user_id, target_user_id)
        if not target:
            await self._bot._answer_callback(callback_id, "Пользователь не найден", alert=True)
            return
        _, draft, _ = self._rights_state(user_id)
        selected = draft.get(target_user_id, target.get("plan_type", "free"))
        has_changes = any(
            draft.get(str(u.get("user_id")), u.get("plan_type", "free")) != u.get("plan_type", "free")
            for u in self._bot._user_state.admin_rights_users[user_id]
        )
        await self._bot._answer_callback(callback_id, "")
        await self._bot.edit_message_text(
            chat_id,
            message_id,
            self._format_rights_user_text(target, selected),
            reply_markup=kb._build_admin_rights_plan_keyboard(target, selected, has_changes),
        )

    async def _on_admin_rights_set(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int], data: str,
    ) -> None:
        try:
            _, target_user_id, plan_type = data.split(":", 2)
        except ValueError:
            await self._bot._answer_callback(callback_id, "Ошибка", alert=True)
            return
        if plan_type not in self._PLAN_TYPES:
            await self._bot._answer_callback(callback_id, "Недопустимый plan_type", alert=True)
            return
        if user_id not in self._bot._user_state.admin_rights_users:
            await self._refresh_rights_users(user_id)
        target = self._find_rights_user(user_id, target_user_id)
        if not target:
            await self._bot._answer_callback(callback_id, "Пользователь не найден", alert=True)
            return
        _, draft, _ = self._rights_state(user_id)
        current = target.get("plan_type", "free")
        if plan_type == current:
            draft.pop(target_user_id, None)
        else:
            draft[target_user_id] = plan_type
        has_changes = bool(draft)
        await self._bot._answer_callback(callback_id, "Изменение в черновике")
        await self._bot.edit_message_text(
            chat_id,
            message_id,
            self._format_rights_user_text(target, plan_type),
            reply_markup=kb._build_admin_rights_plan_keyboard(target, plan_type, has_changes),
        )

    async def _on_admin_rights_cancel(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        self._bot._user_state.admin_rights_draft[user_id] = {}
        await self._bot._answer_callback(callback_id, "Изменения отменены")
        await self._show_admin_rights_list(chat_id, message_id, user_id)

    async def _on_admin_rights_save(
        self, callback_id: str, user_id: str, chat_id: str, message_id: Optional[int],
    ) -> None:
        users, draft, _ = self._rights_state(user_id)
        if not self._bot.db:
            await self._bot._answer_callback(callback_id, "БД не инициализирована", alert=True)
            return
        if not draft:
            await self._bot._answer_callback(callback_id, "Нет изменений", alert=True)
            return
        users_by_id = {str(u.get("user_id")): u for u in users}
        changes = []
        for target_user_id, new_plan in list(draft.items()):
            target = users_by_id.get(target_user_id)
            if not target:
                continue
            old_plan = target.get("plan_type", "free")
            if old_plan == new_plan:
                continue
            self._bot.db.upsert_user_settings(target_user_id, plan_type=new_plan)
            target["plan_type"] = new_plan
            username = target.get("username") or "-"
            changes.append((username, target_user_id, old_plan, new_plan))
        self._bot._user_state.admin_rights_draft[user_id] = {}
        self._bot._user_state.admin_rights_users[user_id] = self._sort_rights_users(users)
        await self._bot._answer_callback(callback_id, "Сохранено")
        if changes:
            lines = [
                f"{_html.escape(name)} id {uid}: {_html.escape(old)} → {_html.escape(new)}"
                for name, uid, old, new in changes
            ]
            await self._bot.send_message(chat_id, "✅ <b>Права обновлены</b>\n\n" + "\n".join(lines))
        await self._show_admin_rights_list(chat_id, message_id, user_id)

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
        def _redact_log_text(text: str) -> str:
            redacted = text
            for secret in (
                getattr(config, "telegram_token", ""),
                getattr(config, "proxy_password", ""),
            ):
                if secret:
                    redacted = redacted.replace(secret, "[REDACTED]")

            redacted = re.sub(
                r"https?://([^:\s/@]+):([^@\s]+)@",
                r"http://[REDACTED]:[REDACTED]@",
                redacted,
            )
            redacted = re.sub(
                r"(?i)(/bot)([0-9]{6,}:[A-Za-z0-9_-]{20,})",
                r"\1[REDACTED]",
                redacted,
            )
            redacted = re.sub(
                r"(?i)\b([0-9]{6,}:[A-Za-z0-9_-]{20,})\b",
                "[REDACTED]",
                redacted,
            )
            redacted = re.sub(
                r"(?im)^(\s*(?:cookie|authorization|x-csrf-token)\s*[:=]\s*).*$",
                r"\1[REDACTED]",
                redacted,
            )
            redacted = re.sub(
                r"(?i)(['\"]?(?:cookie|authorization|x-csrf-token)['\"]?\s*:\s*['\"])[^'\"]*(['\"])",
                r"\1[REDACTED]\2",
                redacted,
            )
            redacted = re.sub(
                r"(?im)^(\s*(?:TELEGRAM_TOKEN|PROXY_PASSWORD)\s*=\s*).*$",
                r"\1[REDACTED]",
                redacted,
            )
            return redacted

        try:
            log_file = "logs/app.log"
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            last_lines = lines[-100:] if len(lines) > 100 else lines
            logs_text = _redact_log_text("".join(last_lines))
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
