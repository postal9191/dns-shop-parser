"""
DNS парсер без Playwright.

Вместо headless браузера используем:
- aiohttp для запросов
- Автоматический логин при CookiesExpiredError (401/403)
- Простой регэксп для UUID товаров
"""

import asyncio
import json
import random
import re
import string
from typing import Any, Optional

import aiohttp
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import config
from parser.exceptions import CookiesExpiredError
from parser.models import Category, Product
from parser.session_manager import SessionManager, HTTPLogger
from utils.logger import logger


_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
# Только UUID товаров (type:4 = product-buy), без рекомендаций (type:3).
# В сыром JSON кавычки внутри inlineJs экранированы: \"id\":\"<UUID>\",\"type\":4
_PRODUCT_UUID_RE = re.compile(
    r'\\"id\\":\\"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\\",\\"type\\":4',
    re.IGNORECASE,
)

_QRATOR_MARKER = "qauth_handle_validate_success"


def _random_container_id() -> str:
    """Генерирует случайный id контейнера вида 'as-AbCdEf'."""
    chars = string.ascii_letters + string.digits
    suffix = "".join(random.choices(chars, k=6))
    return f"as-{suffix}"


def _is_qrator_challenge(html: str) -> bool:
    return _QRATOR_MARKER in html


class SimpleDNSParser:
    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager
        self._filters_url = config.api_base_url + config.filters_path
        self._catalog_url = config.api_base_url + "/catalog/markdown/"
        self._product_buy_url = config.api_base_url + "/ajax-state/product-buy/"
        # ID магазина (Уценка Индустр-льный) — фильтр товаров по городу
        self._shop_id = "b6588e3c-c5b1-11ee-913e-00155d7dfe09"

    async def close(self) -> None:
        pass

    @retry(
        stop=stop_after_attempt(config.max_retries),
        wait=wait_exponential(multiplier=1, min=config.retry_delay, max=60),
        retry=retry_if_exception_type(
            (aiohttp.ClientError, asyncio.TimeoutError)
        ),
        reraise=True,
    )
    async def _post_json(self, url: str, payload: dict) -> Any:
        session = await self._sm.get_session()
        headers = self._sm._build_headers()

        await HTTPLogger.log_request("POST", url, data=payload)

        async with session.post(url, json=payload, headers=headers, timeout=_TIMEOUT) as resp:
            await HTTPLogger.log_response(
                resp.status, url,
                content_type=resp.content_type,
                content_length=resp.content_length
            )

            self._check_status(resp, url)
            self._sm._extract_cookies_from_response(resp)
            try:
                return await resp.json(content_type=None)
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                text = await resp.text()
                logger.debug("Не-JSON от %s: %s", url, text[:300])
                return {}

    @retry(
        stop=stop_after_attempt(config.max_retries),
        wait=wait_exponential(multiplier=1, min=config.retry_delay, max=60),
        retry=retry_if_exception_type(
            (aiohttp.ClientError, asyncio.TimeoutError)
        ),
        reraise=True,
    )
    async def _post_form(self, url: str, raw_data: str) -> Any:
        """POST с application/x-www-form-urlencoded телом."""
        session = await self._sm.get_session()
        headers = self._sm._build_headers({"content-type": "application/x-www-form-urlencoded"})

        await HTTPLogger.log_request("POST", url, headers=headers, data=raw_data[:300])

        async with session.post(
            url, data=raw_data, headers=headers, timeout=_TIMEOUT
        ) as resp:
            await HTTPLogger.log_response(
                resp.status, url,
                content_type=resp.content_type,
                content_length=resp.content_length
            )

            self._check_status(resp, url)
            self._sm._extract_cookies_from_response(resp)
            try:
                return await resp.json(content_type=None)
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                text = await resp.text()
                logger.debug("Не-JSON от %s: %s", url, text[:300])
                return {}

    @retry(
        stop=stop_after_attempt(config.max_retries),
        wait=wait_exponential(multiplier=1, min=config.retry_delay, max=60),
        retry=retry_if_exception_type(
            (aiohttp.ClientError, asyncio.TimeoutError)
        ),
        reraise=True,
    )
    async def _get_html(self, url: str, params: dict | None = None) -> str:
        session = await self._sm.get_session()
        headers = self._sm._build_headers()

        await HTTPLogger.log_request("GET", url, params=params)

        async with session.get(url, params=params, headers=headers, timeout=_TIMEOUT) as resp:
            await HTTPLogger.log_response(
                resp.status, url,
                content_type=resp.content_type,
                content_length=resp.content_length
            )

            self._check_status(resp, url)
            # Сохраняем куки из ответа (включая current_path)
            self._sm._extract_cookies_from_response(resp)
            return await resp.text()

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
        logger.info("[PARSER] Получаю категории товаров уценки для города: %s", config.city_name)

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
    # Шаг 2: UUID товаров из HTML категории
    # -------------------------------------------------------------------

    async def fetch_product_uuids(self, category_id: str, expected_count: int = None, status: Optional[int] = None) -> list[str]:
        """Простой HTTP GET с пагинацией → список UUID товаров из HTML.

        Args:
            category_id: ID категории
            expected_count: ожидаемое количество товаров (из API фильтров)
            status: фильтр по типу товара: 0 = Новый, 1 = Б/У
        """
        logger.debug("[PARSER] Получаю UUID товаров для категории %s (город: %s, ожидаемо: %s, status: %s)",
                    category_id, config.city_name, expected_count or "?", status)

        _MAX_PAGES = 50

        try:
            base_params: dict = {"category": category_id}
            if status is not None:
                base_params["status"] = str(status)

            all_uuids: list[str] = []
            seen: set[str] = set()

            for page in range(1, _MAX_PAGES + 1):
                params = dict(base_params)
                if page > 1:
                    params["p"] = str(page)

                html = await self._get_html(self._catalog_url, params=params)

                page_uuids = list(dict.fromkeys(
                    m.group(1).lower() for m in _PRODUCT_UUID_RE.finditer(html)
                ))

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

            logger.info("[PARSER] Категория %s: итого %d товаров", category_id, len(all_uuids))
            return all_uuids

        except CookiesExpiredError:
            raise
        except Exception as exc:
            logger.error("Ошибка получения UUID для %s: %s", category_id, exc)
            return []

    # -------------------------------------------------------------------
    # Шаг 3: детали товаров
    # -------------------------------------------------------------------

    async def fetch_products_details(
        self,
        uuids: list[str],
        category_id: str = "",
        category_name: str = "",
        uuid_to_status: Optional[dict] = None,
    ) -> list[Product]:
        """POST ajax-state/product-buy одним запросом для всех UUID."""
        logger.info("[PARSER] Загружаю детали %d товаров одним запросом", len(uuids))

        container_map: dict[str, str] = {}
        containers = []
        for uuid in uuids:
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

        payload_obj = {"type": "product-buy", "containers": containers}
        raw_data = "data=" + json.dumps(payload_obj, ensure_ascii=False)

        try:
            resp = await self._post_form(self._product_buy_url, raw_data)
        except (RetryError, Exception) as exc:
            logger.error("[PARSER] Ошибка product-buy: %s", exc)
            return []

        if not (isinstance(resp, dict) and resp.get("result")):
            logger.warning("[PARSER] product-buy вернул result=false: %s", str(resp)[:200])
            return []

        products: list[Product] = []
        for state in resp.get("data", {}).get("states", []):
            p = self._parse_state(state, container_map, category_id, category_name, uuid_to_status)
            if p:
                products.append(p)

        logger.info("[PARSER] Получено %d товаров", len(products))
        return products

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
            )
        except Exception as exc:
            logger.warning("Ошибка разбора state: %s | %s", exc, state)
            return None

    # -------------------------------------------------------------------
    # Комбинированный метод: шаги 2 + 3
    # -------------------------------------------------------------------

    async def fetch_products(
        self, category_id: str, category_name: str = ""
    ) -> list[Product]:
        """Шаги 2+3: HTML → UUID → Product list."""
        uuids = await self.fetch_product_uuids(category_id)
        if not uuids:
            return []

        products = await self.fetch_products_details(
            uuids, category_id, category_name
        )
        logger.info(
            "Категория '%s': загружено %d товаров", category_name, len(products)
        )
        return products
