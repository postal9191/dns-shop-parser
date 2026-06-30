"""
DNS парсер без Playwright.

Вместо headless браузера используем:
- aiohttp для запросов
- Автоматический логин при CookiesExpiredError (401/403)
- JSON-парсинг каталога (UUID + hash + оригинальные контейнеры)
"""

import asyncio
import json
import random
import re
import string
from typing import Any, Optional

import aiohttp

from dns_shop_parser.config import config
from dns_shop_parser.parser.exceptions import CookiesExpiredError
from dns_shop_parser.parser.models import Category, Product
from dns_shop_parser.parser.session_manager import SessionManager, HTTPLogger
from dns_shop_parser.utils.logger import logger


_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
# Только UUID товаров (type:4 = product-buy), без рекомендаций (type:3).
# В сыром JSON кавычки внутри inlineJs экранированы: \"id\":\"<UUID>\",\"type\":4
_PRODUCT_UUID_RE = re.compile(
    r'\\\"id\\\":\\\"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\\\",\\\"type\\\":4',
    re.IGNORECASE,
)
# Hash из inline JS конфигурации product-buy (fallback для HTML-ответов)
_PRODUCT_BUY_HASH_RE = re.compile(
    r'\\\"hash\\\":\\\"([0-9a-f]{40,})\\\"',
    re.IGNORECASE,
)

# Тип для batch из каталога: (hash, [контейнеры])
# Каждая страница каталога = один self-contained batch
CatalogBatch = tuple[str, list[dict]]


def _random_container_id() -> str:
    """Генерирует случайный id контейнера вида 'as-AbCdEf'."""
    chars = string.ascii_letters + string.digits
    suffix = "".join(random.choices(chars, k=6))
    return f"as-{suffix}"


class SimpleDNSParser:
    def __init__(self, session_manager: SessionManager, city_slug: str = "") -> None:
        self._sm = session_manager
        self.city_slug = city_slug
        self._filters_url = config.api_base_url + config.filters_path
        self._catalog_url = config.api_base_url + "/catalog/markdown/"
        self._product_buy_url = config.api_base_url + "/ajax-state/product-buy/"
        # ID магазина (Уценка Индустр-льный) — фильтр товаров по городу
        self._shop_id = "b6588e3c-c5b1-11ee-913e-00155d7dfe09"

    async def close(self) -> None:
        pass

    async def _post_json(self, url: str, payload: dict) -> Any:
        headers = self._sm._build_headers()

        await HTTPLogger.log_request("POST", url, data=payload)

        resp = await self._sm.request("POST", url, json=payload, headers=headers, timeout=_TIMEOUT)
        async with resp as post_resp:
            await HTTPLogger.log_response(
                post_resp.status, url,
                content_type=post_resp.content_type,
            )

            self._check_status(post_resp, url)
            self._sm._extract_cookies_from_response(post_resp)
            try:
                return await post_resp.json(content_type=None)
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                text = await post_resp.text()
                logger.debug("Не-JSON от %s: %s", url, text[:300])
                return {}

    async def _post_form(self, url: str, raw_data: str) -> Any:
        """POST с application/x-www-form-urlencoded телом."""
        headers = self._sm._build_headers({"content-type": "application/x-www-form-urlencoded"})

        await HTTPLogger.log_request("POST", url, headers=headers, data=raw_data[:300])

        resp = await self._sm.request("POST", url, data=raw_data, headers=headers, timeout=_TIMEOUT)
        async with resp as form_resp:
            await HTTPLogger.log_response(
                form_resp.status, url,
                content_type=form_resp.content_type,
            )

            self._check_status(form_resp, url)
            self._sm._extract_cookies_from_response(form_resp)
            try:
                return await form_resp.json(content_type=None)
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                text = await form_resp.text()
                logger.debug("Не-JSON от %s: %s", url, text[:300])
                return {}

    async def _get_html(self, url: str, params: dict | None = None) -> str:
        headers = self._sm._build_headers()

        await HTTPLogger.log_request("GET", url, params=params)

        resp = await self._sm.request("GET", url, params=params, headers=headers, timeout=_TIMEOUT)
        async with resp as get_resp:
            await HTTPLogger.log_response(
                get_resp.status, url,
                content_type=get_resp.content_type,
            )

            self._check_status(get_resp, url)
            self._sm._extract_cookies_from_response(get_resp)
            return await get_resp.text()

    def _check_status(self, resp: aiohttp.ClientResponse, url: str) -> None:
        if resp.status in (401, 403):
            logger.error(
                "DNS вернул %d для %s — куки устарели.", resp.status, url
            )
            raise CookiesExpiredError(f"HTTP {resp.status} от {url}")
        if resp.status == 429:
            logger.warning("Rate limit 429 от %s", url)
            raise aiohttp.ClientError("rate_limited")
        resp.raise_for_status()

    # -------------------------------------------------------------------
    # Шаг 1: категории
    # -------------------------------------------------------------------

    async def fetch_categories(self) -> list[Category]:
        """Простой HTTP GET (без Playwright) → список категорий."""
        logger.info("[PARSER] Получаю категории товаров уценки")

        # ВАЖНО: сначала вызываем /catalog/markdown/ чтобы получить правильный current_path для города
        logger.debug("[PARSER] Обновляю current_path через /catalog/markdown/...")
        try:
            await self._get_html(self._catalog_url, params={})
        except Exception as exc:
            logger.debug("[PARSER] Ошибка при обновлении current_path: %s", exc)

        # DEBUG: логируем current_path куку
        current_path = self._sm._cookies.get('current_path', '')
        logger.debug("[PARSER] current_path кука: %s...", current_path[:80] if current_path else "(пусто)")

        try:
            # Фильтрация происходит через cookies (city_path, current_path)
            html = await self._get_html(
                self._filters_url,
                params={},
            )
        except CookiesExpiredError:
            raise
        except Exception as exc:
            logger.error("[PARSER] Ошибка получения категорий: %s", exc)
            return []

        categories: list[Category] = []

        # Парсим JSON
        try:
            data = json.loads(html)
            root = data if isinstance(data, dict) else {}

            # Ищем блок "Категории" в left blocks
            blocks = root.get("data", {}).get("blocks", {})
            left_blocks = blocks.get("left", [])

            for block in left_blocks:
                block_label = block.get("label", "").lower()
                # Ищем именно блок с категориями товаров
                if "категории" in block_label or "categories" in block_label:
                    for variant in block.get("variants", []):
                        cat_id = variant.get("id", "")
                        if cat_id:
                            categories.append(Category(
                                id=cat_id,
                                label=variant.get("label", ""),
                                count=int(variant.get("count", 0)),
                            ))
                    break  # Нашли блок категорий - выходим

            # Fallback: старая структура
            if not categories:
                filters_list: list = (
                    root.get("data", {}).get("filters")
                    or root.get("filters")
                    or []
                )

                for f in filters_list:
                    for variant in f.get("variants", []):
                        cat_id = variant.get("id", "")
                        if cat_id:
                            categories.append(Category(
                                id=cat_id,
                                label=variant.get("label", ""),
                                count=int(variant.get("count", 0)),
                            ))

        except json.JSONDecodeError:
            logger.debug("HTML не является JSON, извлекаем UUID и labels из разметки")
            # Fallback: парсим UUID из HTML если это HTML
            uuids = list(dict.fromkeys(
                m.group(0).lower() for m in _UUID_RE.finditer(html)
            ))
            if uuids:
                for i, uuid in enumerate(uuids[:10]):  # макс 10 категорий
                    categories.append(Category(
                        id=uuid,
                        label=f"Категория {i+1}",
                        count=0,
                    ))

        if not categories:
            logger.debug("Сырой ответ filters: %s", html[:500])

        logger.info("Категорий получено: %d", len(categories))
        return categories

    # -------------------------------------------------------------------
    # Шаг 2: UUID + hash + оригинальные контейнеры из JSON каталога
    # -------------------------------------------------------------------

    async def fetch_product_uuids(
        self, category_id: str, expected_count: int = None, status: Optional[int] = None
    ) -> tuple[list[str], str, list[CatalogBatch]]:
        """GET /catalog/markdown/?category=X → JSON → (uuids, hash, batches).

        Каждая страница каталога — self-contained batch:
            [
              {"type": "product-buy", "hash": "<hex>", "timeout": 10},
              [{"id": "as-X", "data": {"id": "UUID", "type": 4, ...}}, ...]
            ]

        batches — список (hash, [containers]) постранично.
        Контейнеры в batch — ОРИГИНАЛЬНЫЕ из ответа сервера (с серверными ID).
        Hash привязан к контейнерам — отправлять можно только парой.

        Args:
            category_id: ID категории
            expected_count: ожидаемое количество товаров (из API фильтров)
            status: фильтр по типу товара: 0 = Новый, 1 = Б/У
        """
        logger.debug("[PARSER] Получаю UUID товаров для категории %s (ожидаемо: %s, status: %s)",
                    category_id, expected_count or "?", status)

        _MAX_PAGES = 50

        try:
            base_params: dict = {"category": category_id}
            if status is not None:
                base_params["status"] = str(status)

            all_uuids: list[str] = []
            seen: set[str] = set()
            all_batches: list[CatalogBatch] = []
            product_hash = ""

            for page in range(1, _MAX_PAGES + 1):
                params = dict(base_params)
                if page > 1:
                    params["p"] = str(page)

                raw = await self._get_html(self._catalog_url, params=params)

                # Пытаемся парсить как JSON (основной путь)
                page_uuids, page_hash, page_containers = self._parse_catalog_json(raw)

                # Fallback на regex если ответ — HTML
                if not page_uuids:
                    page_uuids, page_hash = self._parse_catalog_regex(raw)
                    page_containers = []

                if page_hash and not product_hash:
                    product_hash = page_hash

                # Сохраняем batch если есть контейнеры
                if page_containers and page_hash:
                    all_batches.append((page_hash, page_containers))

                # Только UUID, которых ещё не видели
                new_uuids = [u for u in page_uuids if u not in seen]

                if not new_uuids:
                    logger.debug("[PARSER] Страница %d: новых UUID нет — пагинация завершена", page)
                    break

                seen.update(new_uuids)
                all_uuids.extend(new_uuids)

                logger.debug("[PARSER] Страница %d: +%d UUID (итого %d)", page, len(new_uuids), len(all_uuids))

                if expected_count is not None and len(all_uuids) >= expected_count:
                    break

                await asyncio.sleep(0.3)

            # Применяем ограничение по expected_count
            if expected_count is not None and len(all_uuids) > expected_count:
                logger.warning(
                    "[PARSER] Категория %s: найдено %d UUID, но API говорит %d. "
                    "Ограничиваем до %d (вероятно лишние из рекомендаций)",
                    category_id, len(all_uuids), expected_count, expected_count
                )
                all_uuids = all_uuids[:expected_count]

            logger.info("[PARSER] Категория %s: итого %d товаров, %d batches, hash=%s",
                       category_id, len(all_uuids), len(all_batches),
                       product_hash[:16] + "..." if product_hash else "(нет)")
            return all_uuids, product_hash, all_batches

        except CookiesExpiredError:
            raise
        except Exception as exc:
            logger.error("Ошибка получения UUID для %s: %s", category_id, exc)
            return [], "", []

    def _parse_catalog_json(self, raw: str) -> tuple[list[str], str, list[dict]]:
        """Парсит JSON-ответ каталога DNS.

        Два формата ответа:
        1. dict: {"result":true, "html":"...", "assets":{"inlineJs":{"nonce":"window.AjaxState.register([...])"...}}}
        2. list: [{"type":"product-buy","hash":"...","timeout":10}, [{containers}...]]

        Возвращает (uuids, hash, raw_containers).
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return [], "", []

        # Формат 1: dict с inlineJs (актуальный)
        if isinstance(data, dict):
            return self._parse_ajax_state_from_inline(data)

        # Формат 2: JSON array (legacy / Postman)
        if isinstance(data, list) and len(data) >= 2:
            config_obj = data[0] if isinstance(data[0], dict) else {}
            product_hash = config_obj.get("hash", "")
            raw_containers = data[1] if isinstance(data[1], list) else []
            uuids, valid = self._filter_product_containers(raw_containers)
            return uuids, product_hash, valid

        return [], "", []

    def _parse_ajax_state_from_inline(self, data: dict) -> tuple[list[str], str, list[dict]]:
        """Извлекает product-buy batch из assets.inlineJs → AjaxState.register."""
        inline = data.get("assets", {}).get("inlineJs", {})
        if not isinstance(inline, dict):
            return [], "", []

        for _nonce, js_code in inline.items():
            js_str = str(js_code)
            if "AjaxState.register" not in js_str:
                continue

            m = re.search(r'AjaxState\.register\((\[.*\])\)', js_str, re.DOTALL)
            if not m:
                continue

            try:
                batches = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                continue

            # Ищем batch с type=product-buy
            for batch in batches:
                if not isinstance(batch, list) or len(batch) < 2:
                    continue
                cfg = batch[0] if isinstance(batch[0], dict) else {}
                if cfg.get("type") != "product-buy":
                    continue
                product_hash = cfg.get("hash", "")
                containers = batch[1] if isinstance(batch[1], list) else []
                uuids, valid = self._filter_product_containers(containers)
                return uuids, product_hash, valid

        return [], "", []

    def _filter_product_containers(self, containers: list) -> tuple[list[str], list[dict]]:
        """Фильтрует контейнеры: оставляет только type=4 (товары)."""
        uuids = []
        valid = []
        for c in containers:
            if not isinstance(c, dict):
                continue
            inner = c.get("data", {})
            uuid = inner.get("id", "")
            prod_type = inner.get("type")
            if uuid and prod_type == 4:
                uuids.append(uuid.lower())
                valid.append(c)
        return uuids, valid

    def _parse_catalog_regex(self, raw: str) -> tuple[list[str], str]:
        """Fallback: извлекает UUID и hash из HTML/inlineJs через regex."""
        uuids = list(dict.fromkeys(
            m.group(1).lower() for m in _PRODUCT_UUID_RE.finditer(raw)
        ))
        hash_match = _PRODUCT_BUY_HASH_RE.search(raw)
        product_hash = hash_match.group(1) if hash_match else ""
        return uuids, product_hash

    # -------------------------------------------------------------------
    # Шаг 3: детали товаров
    # -------------------------------------------------------------------

    async def fetch_products_details(
        self,
        uuids: list[str],
        category_id: str = "",
        category_name: str = "",
        uuid_to_status: Optional[dict] = None,
        product_hash: str = "",
        catalog_batches: Optional[list[CatalogBatch]] = None,
    ) -> list[Product]:
        """POST ajax-state/product-buy.

        Если catalog_batches заданы — отправляет ОРИГИНАЛЬНЫЕ контейнеры
        из ответа каталога (с серверными ID и привязанным hash).
        Иначе — генерирует контейнеры из uuids (legacy fallback).
        """
        if catalog_batches:
            return await self._fetch_details_from_batches(
                catalog_batches, category_id, category_name, uuid_to_status,
            )
        # Legacy: генерируем контейнеры сами
        return await self._fetch_details_generated(
            uuids, category_id, category_name, uuid_to_status, product_hash,
        )

    async def _fetch_details_from_batches(
        self,
        batches: list[CatalogBatch],
        category_id: str,
        category_name: str,
        uuid_to_status: Optional[dict],
    ) -> list[Product]:
        """Отправляет оригинальные batches из каталога."""
        total_containers = sum(len(c) for _, c in batches)
        logger.info("[PARSER] Загружаю детали через %d catalog-batches (%d контейнеров)",
                    len(batches), total_containers)

        container_map: dict[str, str] = {}
        for _, containers in batches:
            for c in containers:
                cid = c.get("id", "")
                uuid = c.get("data", {}).get("id", "")
                if cid and uuid:
                    container_map[cid] = uuid.lower()

        all_products: list[Product] = []
        for batch_idx, (batch_hash, containers) in enumerate(batches, 1):
            payload_obj: dict[str, Any] = {
                "type": "product-buy",
                "hash": batch_hash,
                "containers": containers,
            }
            raw_data = "data=" + json.dumps(payload_obj, ensure_ascii=False)

            try:
                resp = await self._post_form(self._product_buy_url, raw_data)
            except Exception as exc:
                logger.warning("[PARSER] Batch %d/%d: ошибка product-buy: %s",
                             batch_idx, len(batches), exc)
                continue

            if not (isinstance(resp, dict) and resp.get("result")):
                logger.warning("[PARSER] Batch %d/%d: result=false: %s",
                             batch_idx, len(batches), str(resp)[:500])
                continue

            states = resp.get("data", {}).get("states", [])
            if not states:
                logger.warning("[PARSER] Batch %d/%d: result=true но states пуст. data=%s",
                             batch_idx, len(batches),
                             str(resp.get("data", {}))[:300])
            for state in states:
                p = self._parse_state(state, container_map, category_id, category_name, uuid_to_status)
                if p:
                    all_products.append(p)

        logger.info("[PARSER] Получено %d товаров из %d контейнеров",
                    len(all_products), total_containers)
        return all_products

    async def _fetch_details_generated(
        self,
        uuids: list[str],
        category_id: str,
        category_name: str,
        uuid_to_status: Optional[dict],
        product_hash: str,
    ) -> list[Product]:
        """Legacy: генерирует контейнеры из uuids и отправляет."""
        _BATCH_SIZE = 50
        logger.info("[PARSER] Загружаю детали %d товаров (generated containers, hash=%s)",
                    len(uuids),
                    product_hash[:16] + "..." if product_hash else "нет!")

        all_products: list[Product] = []
        for i in range(0, len(uuids), _BATCH_SIZE):
            batch = uuids[i:i + _BATCH_SIZE]

            container_map: dict[str, str] = {}
            containers = []
            for uuid in batch:
                cid = _random_container_id()
                container_map[cid] = uuid
                containers.append({
                    "id": cid,
                    "data": {
                        "id": uuid,
                        "type": 4,
                        "params": {"hideButtons": True},
                    },
                })

            payload_obj: dict[str, Any] = {"type": "product-buy", "containers": containers}
            if product_hash:
                payload_obj["hash"] = product_hash

            raw_data = "data=" + json.dumps(payload_obj, ensure_ascii=False)

            try:
                resp = await self._post_form(self._product_buy_url, raw_data)
            except Exception as exc:
                logger.warning("[PARSER] Батч %d–%d: ошибка product-buy: %s", i + 1, min(i + _BATCH_SIZE, len(uuids)), exc)
                continue

            if not (isinstance(resp, dict) and resp.get("result")):
                logger.warning("[PARSER] Батч %d–%d: product-buy result=false: %s",
                             i + 1, min(i + _BATCH_SIZE, len(uuids)), str(resp)[:500])
                continue

            states = resp.get("data", {}).get("states", [])
            for state in states:
                p = self._parse_state(state, container_map, category_id, category_name, uuid_to_status)
                if p:
                    all_products.append(p)

        logger.info("[PARSER] Получено %d товаров из %d", len(all_products), len(uuids))
        return all_products

    def _parse_state(
        self,
        state: dict,
        container_map: dict[str, str],
        category_id: str,
        category_name: str,
        uuid_to_status: Optional[dict] = None,
    ) -> Optional[Product]:
        try:
            container_id = state.get("id", "")  # "as-upHxKD"
            inner = state.get("data", {})

            uuid = inner.get("id") or container_map.get(container_id, "")  # UUID товара
            if not uuid:
                return None

            name = inner.get("name", "").strip()
            if not name:
                return None

            price_obj = inner.get("price", {}) or {}
            price_current = int(price_obj.get("current") or 0)
            price_previous = int(price_obj.get("previous") or 0)

            url = f"{config.api_base_url}/catalog/markdown/{uuid}/"

            status = uuid_to_status.get(uuid, "") if uuid_to_status else ""

            return Product(
                id=container_id,      # короткий ID (as-upHxKD)
                uuid=uuid,             # UUID товара
                title=name,
                price=price_current,
                price_old=price_previous,
                url=url,
                category_id=category_id,
                category_name=category_name,
                status=status,
                city_slug=self.city_slug,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning("Ошибка разбора state (%s): %s", type(exc).__name__, exc)
            return None
        except Exception as exc:
            logger.error("Неожиданная ошибка разбора state: %s", exc, exc_info=True)
            return None

    # -------------------------------------------------------------------
    # Комбинированный метод: шаги 2 + 3
    # -------------------------------------------------------------------

    async def fetch_products(
        self, category_id: str, category_name: str = ""
    ) -> list[Product]:
        """Шаги 2+3: JSON → UUID+hash+batches → Product list."""
        uuids, product_hash, batches = await self.fetch_product_uuids(category_id)
        if not uuids:
            return []

        products = await self.fetch_products_details(
            uuids, category_id, category_name,
            product_hash=product_hash, catalog_batches=batches,
        )
        logger.info(
            "Категория '%s': загружено %d товаров", category_name, len(products)
        )
        return products
