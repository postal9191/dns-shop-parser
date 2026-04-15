"""Парсер DNS товаров (использует куки из get_cookies.py)."""

import sys
import os
from pathlib import Path

# Добавляем директорию проекта в sys.path для импорта модулей
PROJECT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

import asyncio
from datetime import datetime
import pickle

from config import config
from parser.db_manager import DBManager
from parser.simple_dns_parser import SimpleDNSParser
from parser.session_manager import SessionManager
from services.telegram_notifier import TelegramNotifier
from services.telegram_bot import init_telegram_bot
from utils.logger import logger


class DNSMonitorWithCookies:
    """Парсер DNS с загрузкой кук из браузера."""

    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self.parser = SimpleDNSParser(self.session_manager)
        self.db = DBManager(config.db_path)

        # Инициализируем Telegram бот
        self.telegram_bot = init_telegram_bot(self.db)
        self.tg = TelegramNotifier(bot=self.telegram_bot)

        self.parse_interval = config.parse_interval
        self.city_name = config.city_name

    async def load_cookies_from_browser(self) -> bool:
        """Загружает куки сохранённые браузером."""
        cookies_file = Path("browser_cookies.pkl")
        if not cookies_file.exists():
            logger.error("[MAIN] Файл кук не найден. Запустите: python get_cookies.py")
            return False

        try:
            with open(cookies_file, "rb") as f:
                cookies = pickle.load(f)

            logger.info("[MAIN] Загруженкуки из браузера (%d элементов)", len(cookies))

            # Проверяем критичные куки
            critical_cookies = {}
            for c in cookies:
                if c['name'] in ['city_path', 'current_path']:
                    critical_cookies[c['name']] = c['value']

            if 'city_path' in critical_cookies:
                logger.info("[MAIN] ✓ city_path = '%s'", critical_cookies['city_path'])
            if 'current_path' in critical_cookies:
                cp = critical_cookies['current_path']
                cp_display = cp[:80] + "..." if len(cp) > 80 else cp
                logger.info("[MAIN] ✓ current_path = '%s'", cp_display)

            # Инициализируем сессию без Qrator обхода
            await self.session_manager._init_session_with_cookies(cookies)
            logger.info("[MAIN] Сессия инициализирована с браузер-кук")
            return True

        except Exception as exc:
            logger.error("[MAIN] Ошибка загрузки кук: %s", exc)
            return False

    async def parse_all(self) -> None:
        """
        Парсит все категории и товары в текущем городе.
        ОПТИМИЗАЦИЯ: Загружает товары только если изменилось количество в категории.
        """
        # Проверяем это первый запуск (БД пуста)
        total_before = self.db.get_product_count()
        is_first_run = total_before == 0

        logger.info(
            "[PARSE] Начинаем цикл обновления (город: %s, интервал: %d сек)",
            self.city_name,
            self.parse_interval,
        )

        try:
            # Шаг 1: категории
            try:
                categories = await self.parser.fetch_categories()
            except Exception as exc:
                logger.error("[PARSE] Ошибка при получении категорий: %s", exc)
                # Пробуем перезагрузить куки и повторить
                if await self.load_cookies_from_browser():
                    try:
                        categories = await self.parser.fetch_categories()
                    except Exception as exc2:
                        logger.error("[PARSE] Повторная ошибка: %s", exc2)
                        return
                else:
                    return

            if not categories:
                logger.error("[PARSE] Категории не получены")
                return

            logger.info(
                "[PARSE] Получено %d категорий для города %s",
                len(categories),
                self.city_name,
            )

            # Шаг 2: товары по каждой категории (оптимизировано)
            total_new_products = 0
            total_updated = 0

            for i, cat in enumerate(categories, 1):
                # Проверяем было ли изменение количества товаров в категории
                state = self.db.get_category_state(cat.id)
                last_count = state["last_product_count"] if state else 0

                if cat.count == last_count and last_count > 0:
                    # Количество не изменилось, пропускаем
                    logger.debug(
                        "[PARSE] Категория %d/%d: %s - без изменений (%d товаров)",
                        i,
                        len(categories),
                        cat.label,
                        cat.count,
                    )
                    continue

                # Количество изменилось или это первый раз - загружаем товары
                logger.info(
                    "[PARSE] Категория %d/%d: %s (было: %d, сейчас: %d)",
                    i,
                    len(categories),
                    cat.label,
                    last_count,
                    cat.count,
                )

                try:
                    # Получаем UUID товаров
                    uuids = await self.parser.fetch_product_uuids(cat.id)
                    if not uuids:
                        logger.debug("[PARSE]   (товаров не найдено)")
                        self.db.update_category_state(cat.id, cat.label, 0)
                        continue

                    # Проверяем какие товары новые
                    new_uuids = self.db.get_new_products_in_category(cat.id, uuids)

                    # Получаем детали товаров
                    products = await self.parser.fetch_products_details(
                        uuids, cat.id, cat.label
                    )

                    if products:
                        saved = self.db.upsert_products(products)
                        total_updated += saved

                        logger.info(
                            "[PARSE]   OK Загружено и сохранено %d товаров",
                            saved,
                        )

                        # Если есть новые товары и это не первый запуск - отправляем уведомление
                        if new_uuids and not is_first_run:
                            new_products = [p for p in products if p.uuid in new_uuids]
                            if new_products:
                                total_new_products += len(new_products)
                                new_prods_data = [
                                    {
                                        "category": cat.label,
                                        "title": p.title,
                                        "price": p.price,
                                        "price_old": p.price_old,
                                        "url": p.url,
                                    }
                                    for p in new_products
                                ]
                                logger.info(
                                    "[PARSE]   NEW Новых товаров: %d",
                                    len(new_products),
                                )
                                # Отправляем Telegram уведомление всем подписчикам
                                await self.tg.send_new_products_notification(
                                    cat.label, new_prods_data
                                )
                        elif new_uuids and is_first_run:
                            logger.info("[PARSE]   (пропускаем ТГ на первом запуске)")
                        else:
                            logger.debug("[PARSE]   (новых товаров не найдено)")

                    # Обновляем состояние категории
                    self.db.update_category_state(cat.id, cat.label, cat.count)

                    # Задержка между категориями
                    await asyncio.sleep(0.5)

                except Exception as exc:
                    logger.error("[PARSE]   ERR Ошибка при загрузке категории: %s", exc)
                    continue

            # Итоги цикла
            total_in_db = self.db.get_product_count()
            logger.info(
                "[PARSE] Цикл завершён: новых %d, обновлено %d, всего в БД: %d",
                total_new_products,
                total_updated,
                total_in_db,
            )

        except Exception as exc:
            logger.error("[PARSE] ERR Критическая ошибка в цикле парсинга: %s", exc)

    async def run_forever(self) -> None:
        """Бесконечный цикл обновления каждые N секунд."""
        logger.info(
            "[MAIN] Запущен DNS Monitor (город: %s, интервал: %d сек)",
            self.city_name,
            self.parse_interval,
        )

        # Загружаем куки из браузера
        if not await self.load_cookies_from_browser():
            logger.error("[MAIN] Не удалось загрузить куки. Выход.")
            return

        # Запускаем Telegram бот в фоновой задаче
        bot_task = (
            asyncio.create_task(self.telegram_bot.polling_loop())
            if self.telegram_bot.enabled
            else None
        )

        iteration = 0
        try:
            while True:
                iteration += 1
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info("")
                logger.info("=" * 70)
                logger.info("[%s] Итерация #%d", timestamp, iteration)
                logger.info("=" * 70)

                await self.parse_all()

                logger.info(
                    "[MAIN] Следующее обновление через %d сек...",
                    self.parse_interval,
                )
                await asyncio.sleep(self.parse_interval)

        except KeyboardInterrupt:
            logger.info("[MAIN] Остановлено пользователем (Ctrl+C)")
        except Exception as exc:
            logger.error("[MAIN] ERR Необработанное исключение: %s", exc)
        finally:
            if bot_task:
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
            await self.session_manager.close()
            self.db.close()
            await self.tg.close()
            logger.info("[MAIN] Сессия закрыта")


async def main() -> None:
    """Точка входа - запуск один раз (цикл управляется из run.py)."""
    monitor = DNSMonitorWithCookies()

    # Загружаем куки
    if not await monitor.load_cookies_from_browser():
        logger.error("[MAIN] Не удалось загрузить куки. Выход.")
        return

    # Запускаем Telegram бот в фоновой задаче
    bot_task = (
        asyncio.create_task(monitor.telegram_bot.polling_loop())
        if monitor.telegram_bot.enabled
        else None
    )

    try:
        # Парсим один раз (без цикла)
        await monitor.parse_all()
    finally:
        if bot_task:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        await monitor.session_manager.close()
        monitor.db.close()
        await monitor.tg.close()


if __name__ == "__main__":
    asyncio.run(main())
