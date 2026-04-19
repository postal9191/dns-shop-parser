"""Парсер DNS товаров (безбраузерный режим с Node.js + Playwright)."""

import sys
import os
from pathlib import Path

# Добавляем директорию проекта в sys.path для импорта модулей
PROJECT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

import asyncio
import hashlib
from datetime import datetime

from config import config
from parser.db_manager import DBManager
from parser.exceptions import CookiesExpiredError
from parser.simple_dns_parser import SimpleDNSParser
from parser.session_manager import SessionManager
from services.telegram_notifier import TelegramNotifier
from services.telegram_bot import init_telegram_bot
from utils.logger import logger


class DNSMonitorBrowserless:
    """Парсер DNS без браузера (Node.js + Playwright для Qrator)."""

    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self.parser = SimpleDNSParser(self.session_manager)
        self.db = DBManager(config.db_path)

        # Инициализируем Telegram бот
        self.telegram_bot = init_telegram_bot(self.db)
        self.tg = TelegramNotifier(bot=self.telegram_bot)

        self.parse_interval = config.parse_interval
        self.city_name = config.city_name

    async def init_session_browserless(self) -> bool:
        """Инициализирует сессию безбраузерным способом (Node.js + Playwright)."""
        try:
            logger.info("[MAIN] Инициализация сессии (безбраузерный режим)")
            await self.session_manager._init_session()
            logger.info("[MAIN] ✓ Сессия инициализирована успешно")
            return True
        except Exception as exc:
            logger.error("[MAIN] Ошибка инициализации сессии: %s", exc)
            return False

    async def _process_category(
        self,
        cat,
        i: int,
        total_categories: int,
        is_first_run: bool,
        all_price_changes: list,
    ) -> tuple[int, int]:
        """
        Обрабатывает одну категорию (fetch UUID, детали, сохранение в БД).
        Возвращает (total_new_products, total_updated).
        Вызывает CookiesExpiredError если куки устарели.
        """
        total_new_products = 0
        total_updated = 0

        # Получаем состояние категории
        state = self.db.get_category_state(cat.id)
        last_count = state["last_product_count"] if state else 0
        last_hash = state["uuid_hash"] if state else None

        # Получаем UUID раздельно по типу товара для маркировки Новый/Б/У
        uuids_new = await self.parser.fetch_product_uuids(cat.id, status=0)
        uuids_used = await self.parser.fetch_product_uuids(cat.id, status=1)
        uuid_to_status = {u: "Новый" for u in uuids_new}
        uuid_to_status.update({u: "Б/У" for u in uuids_used})

        # Дедуплицируем, обрезаем до ожидаемого количества
        seen: set = set()
        uuids: list = []
        for u in (uuids_new + uuids_used):
            if u not in seen:
                seen.add(u)
                uuids.append(u)
        if cat.count and len(uuids) > cat.count:
            uuids = uuids[: cat.count]
            uuid_to_status = {u: uuid_to_status[u] for u in uuids if u in uuid_to_status}

        if not uuids:
            logger.debug(
                "[PARSE] Категория %d/%d: %s - товаров не найдено",
                i,
                total_categories,
                cat.label,
            )
            self.db.update_category_state(cat.id, cat.label, 0, [])
            return (0, 0)

        # Вычисляем хэш текущего состава товаров
        current_hash = hashlib.md5(",".join(sorted(uuids)).encode()).hexdigest()

        uuids_unchanged = current_hash == last_hash
        if uuids_unchanged:
            logger.debug(
                "[PARSE] Категория %d/%d: %s - UUID без изменений (%d товаров), проверяем цены",
                i,
                total_categories,
                cat.label,
                cat.count,
            )
        else:
            logger.info(
                "[PARSE] Категория %d/%d: %s (было: %d, сейчас: %d, состав изменился)",
                i,
                total_categories,
                cat.label,
                last_count,
                len(uuids),
            )

        # Проверяем какие товары новые (если UUID состав не изменился — новых нет)
        new_uuids = (
            []
            if uuids_unchanged
            else self.db.get_new_products_in_category(cat.id, uuids)
        )

        # Получаем детали товаров
        products = await self.parser.fetch_products_details(
            uuids, cat.id, cat.label, uuid_to_status=uuid_to_status
        )

        if products:
            saved, price_changes = self.db.upsert_products(products)
            total_updated += saved

            logger.info(
                "[PARSE]   OK Загружено и сохранено %d товаров",
                saved,
            )

            if not uuids_unchanged:
                deleted = self.db.delete_products_not_in_uuids(cat.id, uuids)
                if deleted:
                    logger.info("[PARSE]   DEL Удалено %d проданных товаров", deleted)

            # Собираем изменения цен (кроме первого запуска)
            if price_changes and not is_first_run:
                logger.info("[PARSE]   PRICE Изменились цены: %d товаров", len(price_changes))
                all_price_changes.extend(price_changes)

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
                            "status": p.status,
                        }
                        for p in new_products
                    ]
                    logger.info(
                        "[PARSE]   NEW Новых товаров: %d",
                        len(new_products),
                    )
                    # Отправляем Telegram уведомление всем подписчикам
                    await self.tg.send_new_products_notification(cat.label, new_prods_data)
            elif new_uuids and is_first_run:
                logger.info("[PARSE]   (пропускаем ТГ на первом запуске)")
            else:
                logger.debug("[PARSE]   (новых товаров не найдено)")

        # Обновляем состояние категории с хэшем UUID (используем реальное количество)
        self.db.update_category_state(cat.id, cat.label, len(uuids), uuids)

        # Задержка между категориями
        await asyncio.sleep(0.5)

        return (total_new_products, total_updated)

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
            # Шаг 1: получить категории
            max_category_retries = 3
            categories = []
            for cat_attempt in range(max_category_retries):
                try:
                    categories = await self.parser.fetch_categories()
                    break
                except CookiesExpiredError as exc:
                    logger.warning("[PARSE] ⚠️ Куки устарели при получении категорий: %s", exc)
                    if cat_attempt < max_category_retries - 1:
                        logger.info("[PARSE] Переинициализирую сессию и пытаюсь снова (%d/%d)...",
                                   cat_attempt + 2, max_category_retries)
                        if await self.init_session_browserless():
                            await asyncio.sleep(3)
                            continue
                        else:
                            logger.error("[PARSE] Не удалось переинициализировать сессию")
                            return
                    else:
                        logger.error("[PARSE] Не удалось получить категории после переинициализации кук")
                        return
                except Exception as exc:
                    logger.error("[PARSE] Ошибка при получении категорий: %s", exc)
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
            all_price_changes = []

            for i, cat in enumerate(categories, 1):
                # Retry цикл для текущей категории при истечении кук
                cookie_retries = 0
                max_cookie_retries = 2
                while True:
                    try:
                        new_prods, upd = await self._process_category(
                            cat, i, len(categories), is_first_run, all_price_changes
                        )
                        total_new_products += new_prods
                        total_updated += upd
                        break  # успех — переходим к следующей категории

                    except CookiesExpiredError as exc:
                        cookie_retries += 1
                        logger.warning(
                            "[PARSE]   ⚠️ Куки устарели при загрузке категории %d/%d (попытка %d)",
                            i,
                            len(categories),
                            cookie_retries,
                        )
                        if cookie_retries > max_cookie_retries:
                            logger.error(
                                "[PARSE]   Исчерпаны попытки обновления кук для категории %d, пропускаем",
                                i,
                            )
                            break
                        # Переинициализируем сессию
                        if await self.init_session_browserless():
                            logger.info(
                                "[PARSE] Сессия переинициализирована, повтор категории %d...",
                                i,
                            )
                            await asyncio.sleep(3)
                            # while True продолжится — повторим категорию
                        else:
                            logger.error(
                                "[PARSE] Не удалось переинициализировать сессию при ошибке куки, пропускаем"
                            )
                            break

                    except Exception as exc:
                        logger.error("[PARSE]   ERR Ошибка при загрузке категории: %s", exc)
                        break  # выходим из retry цикла, переходим к следующей категории

            # Отправляем единое уведомление об изменениях цен
            if all_price_changes:
                await self.tg.send_price_changes_notification(all_price_changes)

            # Итоги цикла
            total_in_db = self.db.get_product_count()
            logger.info(
                "[PARSE] Цикл завершён: новых %d, обновлено %d, цены изменились %d, всего в БД: %d",
                total_new_products,
                total_updated,
                len(all_price_changes),
                total_in_db,
            )

        except Exception as exc:
            logger.error("[PARSE] ERR Критическая ошибка в цикле парсинга: %s", exc)

    async def run_once(self) -> None:
        """Парсинг один раз (без цикла) с инициализацией сессии и retry логикой."""
        logger.info(
            "[MAIN] Запуск DNS Monitor (город: %s)",
            self.city_name,
        )

        # Инициализируем сессию безбраузерным способом (Node.js + Playwright) с повторными попытками
        max_init_retries = 3
        for attempt in range(max_init_retries):
            logger.info("[MAIN] Попытка инициализации сессии (%d/%d)", attempt + 1, max_init_retries)

            if await self.init_session_browserless():
                logger.info("[MAIN] ✅ Сессия инициализирована успешно")
                break

            if attempt < max_init_retries - 1:
                wait_time = 10 * (attempt + 1)  # 10, 20, 30 сек
                logger.warning("[MAIN] ⚠️ Инициализация не удалась, повторная попытка через %d сек...", wait_time)
                await asyncio.sleep(wait_time)
            else:
                logger.error("[MAIN] ❌ Не удалось инициализировать сессию после %d попыток. Выход.", max_init_retries)
                return

        # Запускаем Telegram бот в фоновой задаче
        bot_task = (
            asyncio.create_task(self.telegram_bot.polling_loop())
            if self.telegram_bot.enabled
            else None
        )

        try:
            await self.parse_all()
        except Exception as exc:
            logger.error("[MAIN] Ошибка парсинга: %s", exc)
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


async def main() -> None:
    """Точка входа - запуск один раз (безбраузерный режим, цикл управляется из run.py)."""
    monitor = DNSMonitorBrowserless()
    await monitor.run_once()


if __name__ == "__main__":
    asyncio.run(main())
