"""Парсер DNS товаров (безбраузерный режим с Node.js + Playwright)."""

import sys
import os
from pathlib import Path

# Добавляем директорию проекта в sys.path для импорта модулей
PROJECT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

import asyncio
import argparse
import hashlib
import json

from config import config
from data.cities import DEFAULT_CITY_SLUG, SLUG_TO_CITY
from parser.db_manager import DBManager
from parser.simple_dns_parser import SimpleDNSParser
from parser.session_manager import SessionManager
from services.telegram_notifier import TelegramNotifier
from services.telegram_bot import init_telegram_bot
from utils.logger import logger


class DNSMonitorBrowserless:
    """Парсер DNS без браузера (Node.js + Playwright для Qrator)."""

    def __init__(self, city_slug: str | None = None) -> None:
        self.city_slug = city_slug if city_slug is not None else DEFAULT_CITY_SLUG
        self.session_manager = SessionManager(city_slug=self.city_slug)
        self.parser = SimpleDNSParser(self.session_manager, city_slug=self.city_slug)
        self.db = DBManager(config.db_path, default_city_slug=self.city_slug)

        # Инициализируем Telegram бот
        self.telegram_bot = init_telegram_bot(self.db)
        self.tg = TelegramNotifier(bot=self.telegram_bot, db=self.db)

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
        all_new_products: list,
        retry_count: int = 0,
    ) -> tuple[int, int]:
        """
        Обрабатывает одну категорию (fetch UUID, детали, сохранение в БД).
        Возвращает (total_new_products, total_updated).
        При ошибке 503 делает retry до 3 раз с небольшой задержкой.
        """
        total_new_products = 0
        total_updated = 0

        # Получаем состояние категории
        state = self.db.get_category_state(cat.id, self.city_slug)
        last_count = state["last_product_count"] if state else 0
        last_hash = state["uuid_hash"] if state else None

        try:
            # Получаем UUID раздельно по типу товара для маркировки Новый/Б/У
            uuids_new = await self.parser.fetch_product_uuids(cat.id, expected_count=cat.count, status=0)
            uuids_used = await self.parser.fetch_product_uuids(cat.id, expected_count=cat.count, status=1)
        except Exception as exc:
            # Retry логика при ошибках парсинга
            if retry_count < 3:
                wait_time = (2 ** retry_count) + 0.5
                logger.warning(
                    "[PARSE] Категория %d/%d: %s - ошибка: %s. Retry %d/3 через %.1f сек",
                    i, total_categories, cat.label, exc, retry_count + 1, wait_time
                )
                await asyncio.sleep(wait_time)
                return await self._process_category(
                    cat, i, total_categories, is_first_run,
                    all_price_changes, all_new_products, retry_count + 1
                )
            else:
                logger.error(
                    "[PARSE] Категория %d/%d: %s - ошибка после 3 попыток: %s",
                    i, total_categories, cat.label, exc
                )
                return (0, 0)

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
            if cat.count > 0:
                logger.warning(
                    "[PARSE] Категория %d/%d: %s - ожидалось %d товаров, но UUID не получены; "
                    "считаем fetch подозрительным, state/sold-mark не обновляем",
                    i,
                    total_categories,
                    cat.label,
                    cat.count,
                )
                return (0, 0)

            logger.debug(
                "[PARSE] Категория %d/%d: %s - товаров не найдено (count=0)",
                i,
                total_categories,
                cat.label,
            )
            self.db.update_category_state(cat.id, cat.label, 0, self.city_slug, [])
            return (0, 0)

        # Вычисляем хэш текущего состава товаров
        current_hash = hashlib.sha256(json.dumps(sorted(uuids)).encode()).hexdigest()

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
            else self.db.get_new_products_in_category(cat.id, uuids, self.city_slug)
        )

        # Получаем детали товаров (с retry)
        products = None
        for attempt in range(3):
            try:
                products = await self.parser.fetch_products_details(
                    uuids, cat.id, cat.label, uuid_to_status=uuid_to_status
                )
                break
            except Exception as exc:
                if attempt < 2:
                    wait_time = (2 ** attempt) + 0.5
                    logger.warning(
                        "[PARSE] Категория %d/%d: %s - ошибка fetch_products_details: %s. Retry %d/3 через %.1f сек",
                        i, total_categories, cat.label, exc, attempt + 1, wait_time
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "[PARSE] Категория %d/%d: %s - ошибка fetch_products_details после 3 попыток: %s",
                        i, total_categories, cat.label, exc
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

            # Если есть новые товары и это не первый запуск - накапливаем для дайджеста
            if new_uuids and not is_first_run:
                new_products = [p for p in products if p.uuid in new_uuids]
                if new_products:
                    total_new_products += len(new_products)
                    logger.info("[PARSE]   NEW Новых товаров: %d", len(new_products))
                    all_new_products.extend([
                        {
                            "category_id": cat.id,
                            "category": cat.label,
                            "title": p.title,
                            "price": p.price,
                            "price_old": p.price_old,
                            "url": p.url,
                            "status": p.status,
                            "city_slug": p.city_slug,
                        }
                        for p in new_products
                    ])
            elif new_uuids and is_first_run:
                logger.info("[PARSE]   (пропускаем ТГ на первом запуске)")
            else:
                logger.debug("[PARSE]   (новых товаров не найдено)")
        else:
            logger.warning(
                "[PARSE]   ⚠️ UUID получены (%d), но детали товаров не получены; "
                "sold-mark/state update пропущены, чтобы не потерять данные",
                len(uuids),
            )
            return (0, 0)

        # Помечаем купленными только если данные полные
        fetch_complete = (cat.count == 0) or (len(uuids) >= cat.count * 0.9)
        if not fetch_complete:
            logger.warning(
                "[PARSE]   ⚠️ Неполный fetch: получено %d из %d ожидаемых — sold-mark пропущен, hash не обновляем",
                len(uuids), cat.count,
            )
            return (total_new_products, total_updated)

        deleted = self.db.delete_products_not_in_uuids(cat.id, uuids, self.city_slug)
        if deleted:
            logger.info("[PARSE]   SOLD Помечено купленными %d товаров", deleted)

        # Обновляем состояние категории (только при полных данных)
        self.db.update_category_state(cat.id, cat.label, len(uuids), self.city_slug, uuids)

        # Задержка между категориями
        await asyncio.sleep(0.5)

        return (total_new_products, total_updated)

    async def parse_all(self) -> None:
        """
        Парсит все категории и товары в текущем городе.
        Детали товаров загружаются каждый цикл, чтобы проверять изменения цен.
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
                logger.error("[PARSE] Категории не получены — возможно DNS API недоступен")
                await self.tg.send_admin_alert("⚠️ Парсер: категории не получены, DNS API может быть недоступен")
                return

            logger.info(
                "[PARSE] Получено %d категорий",
                len(categories),
            )

            # Сбрасываем прокси пул перед новым циклом парсинга
            await self.session_manager.reset_proxy()

            # Шаг 2: товары по каждой категории (параллельно с ограничением)
            concurrency = config.parse_concurrency
            semaphore = asyncio.Semaphore(concurrency)
            logger.info("[PARSE] Параллельная обработка: %d потоков", concurrency)
            all_price_changes: list = []
            all_new_products: list = []

            async def process_category_with_semaphore(i: int, cat) -> tuple[int, int]:
                """Обработка категории с контролем параллелизма."""
                async with semaphore:
                    try:
                        new_prods, upd = await self._process_category(
                            cat, i, len(categories), is_first_run, all_price_changes, all_new_products
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

            # Отправляем единый дайджест с новыми товарами и изменениями цен
            if all_new_products or all_price_changes:
                await self.tg.send_digest(all_new_products, all_price_changes, plan_types={"pro", "super"})

            # Помечаем купленными товары из категорий, которых больше нет на сайте
            fetched_ids = {cat.id for cat in categories}
            db_category_ids = set(self.db.get_all_category_states(self.city_slug).keys())
            orphaned_ids = db_category_ids - fetched_ids
            for orphaned_id in orphaned_ids:
                deleted = self.db.delete_all_products_in_category(orphaned_id, self.city_slug)
                if deleted:
                    logger.info(
                        "[PARSE] Помечено купленными %d товаров из исчезнувшей категории %s",
                        deleted, orphaned_id,
                    )

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

            # Уведомление админу о завершении цикла
            city_name = SLUG_TO_CITY.get(self.city_slug, self.city_slug)
            await self.tg.send_admin_parse_finish(
                new_cnt=total_new_products,
                updated_cnt=total_updated,
                price_changed=len(all_price_changes),
                total_db=total_in_db,
                prev_cnt=total_before,
                delta=delta,
                city_name=city_name,
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

        from parser.qrator_resolver import check_node_health, qrator_preflight
        if not check_node_health():
            logger.error("[MAIN] ❌ Node.js недоступен. Установите Node.js: https://nodejs.org/")
            return
        if not qrator_preflight():
            logger.error("[MAIN] Qrator preflight failed. Check Node.js/Playwright/proxy diagnostics above.")
            return

        try:
            success = await asyncio.wait_for(
                self.init_session_browserless(),
                timeout=config.qrator_init_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("[MAIN] Qrator init timeout (%.0f sec)", config.qrator_init_timeout)
            await self.tg.send_admin_alert(
                f"Parser: Qrator init timeout ({config.qrator_init_timeout:.0f} sec)"
            )
            return
        if not success:
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
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--city-slug", default=None)
    args = arg_parser.parse_args()
    monitor = DNSMonitorBrowserless(city_slug=args.city_slug)
    await monitor.run_once()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # ВАЖНО: parser.py намеренно всегда завершается с кодом 0.
        # run.py управляет жизненным циклом сервиса и не должен останавливать
        # процесс из-за временных ошибок DNS/Qrator/Node/сети.
        # Эту логику не менять без отдельного архитектурного решения.
        sys.exit(0)
