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

    async def init_session_browserless(self, force_qrator: bool = False) -> bool:
        """Инициализирует сессию безбраузерным способом (Node.js + Playwright)."""
        try:
            logger.info("[MAIN] Инициализация сессии (безбраузерный режим)")
            result = await self.session_manager._init_session(force_qrator=force_qrator)
            if not result:
                logger.error("[MAIN] ❌ КРИТИЧНО: Сессия не инициализирована (вероятно, Qrator не решился)")
                logger.error("[MAIN] Решения: 1) Проверить IP (забанен?), 2) Очистить Chromium profile, 3) Проверить solve_qrator.js")
                return False
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

        price_changes = []
        if products:
            saved, price_changes = self.db.upsert_products(products)
            total_updated += saved

            logger.info(
                "[PARSE]   OK Загружено и сохранено %d товаров",
                saved,
            )

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
        else:
            logger.warning("[PARSE]   ⚠️ Товары не получены от сайта (может быть сбой парсинга)")

        # Удаляем проданные только если данные полные
        fetch_complete = (cat.count == 0) or (len(uuids) >= cat.count * 0.9)
        if not fetch_complete:
            logger.warning(
                "[PARSE]   ⚠️ Неполный fetch: получено %d из %d ожидаемых — удаление пропущено, hash не обновляем",
                len(uuids), cat.count,
            )
            return (total_new_products, total_updated)

        deleted = self.db.delete_products_not_in_uuids(cat.id, uuids)
        if deleted:
            logger.info("[PARSE]   DEL Удалено %d проданных товаров", deleted)

        # Обновляем состояние категории (только при полных данных)
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
            "[PARSE] Начинаем цикл обновления (интервал: %d сек)",
            self.parse_interval,
        )

        try:
            # Шаг 1: получить категории
            try:
                categories = await self.parser.fetch_categories()
            except Exception as exc:
                logger.error("[PARSE] Ошибка при получении категорий: %s", exc)
                return

            if not categories:
                logger.error("[PARSE] Категории не получены")
                return

            logger.info(
                "[PARSE] Получено %d категорий",
                len(categories),
            )

            # Шаг 2: товары по каждой категории (параллельно с ограничением)
            semaphore = asyncio.Semaphore(config.parse_concurrency)
            all_price_changes = []

            async def process_category_with_semaphore(i: int, cat) -> tuple[int, int]:
                """Обработка категории с контролем параллелизма."""
                async with semaphore:
                    try:
                        new_prods, upd = await self._process_category(
                            cat, i, len(categories), is_first_run, all_price_changes
                        )
                        return (new_prods, upd)
                    except Exception as exc:
                        logger.error("[PARSE]   ERR Ошибка при загрузке категории %d/%d: %s", i, len(categories), exc)
                        return (0, 0)

            # Запускаем параллельную обработку всех категорий
            tasks = [process_category_with_semaphore(i, cat) for i, cat in enumerate(categories, 1)]
            results = await asyncio.gather(*tasks)

            # Собираем результаты
            total_new_products = sum(r[0] for r in results)
            total_updated = sum(r[1] for r in results)

            # Отправляем единое уведомление об изменениях цен
            if all_price_changes:
                await self.tg.send_price_changes_notification(all_price_changes)

            # Итоги цикла
            total_in_db = self.db.get_product_count()
            delta = total_in_db - total_before

            logger.info(
                "[PARSE] Цикл завершён: новых %d, обновлено %d, цены изменились %d, всего в БД: %d (было %d, изменение: %+d)",
                total_new_products,
                total_updated,
                len(all_price_changes),
                total_in_db,
                total_before,
                delta,
            )

            # Если есть расхождение - логируем дополнительную информацию
            if delta != total_new_products and total_new_products > 0:
                logger.warning(
                    "[PARSE] ⚠️ ВНИМАНИЕ: добавлено %d новых, но в БД +%d товаров (разница: %+d). Проверьте логику delete_products_not_in_uuids",
                    total_new_products,
                    delta,
                    delta - total_new_products,
                )

        except Exception as exc:
            logger.error("[PARSE] ERR Критическая ошибка в цикле парсинга: %s", exc)

    async def run_once(self) -> None:
        """Парсинг один раз (без цикла) с инициализацией сессии."""
        logger.info("[MAIN] Запуск DNS Monitor")

        if not await self.init_session_browserless():
            logger.error("[MAIN] ❌ Не удалось инициализировать сессию. Выход.")
            return

        logger.info("[MAIN] ✅ Сессия инициализирована успешно")

        # Polling НЕ запускаем — бот живёт постоянно в run.py.
        # Здесь только отправка уведомлений через broadcast_message (без конфликта).
        try:
            await self.parse_all()
        except Exception as exc:
            logger.error("[MAIN] Ошибка парсинга: %s", exc)
        finally:
            await self.session_manager.close()
            self.db.close()
            await self.telegram_bot.close()


async def main() -> None:
    """Точка входа - запуск один раз (безбраузерный режим, цикл управляется из run.py)."""
    monitor = DNSMonitorBrowserless()
    await monitor.run_once()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        sys.exit(0)
