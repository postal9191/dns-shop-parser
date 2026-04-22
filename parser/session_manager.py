"""
Менедджер HTTP-сессии для DNS.

Автоматически получает все необходимые куки:
1. GET главная → PHPSESSID, _csrf, auth_public_uid
2. Решаем Qrator → qrator_jsid2
3. Добавляем город → current_path, city_path
4. При 401/403 → полный цикл заново + логин
"""

import asyncio
import platform
import re

import aiohttp

from config import config
from parser.qrator_resolver import resolve_qrator_cookies, cleanup_chromium_profile
from utils.logger import logger


class HTTPLogger:
    """Логирует все HTTP-запросы и ответы для отладки."""

    @staticmethod
    async def log_request(method: str, url: str, headers: dict = None, 
                          data: dict | str | None = None, params: dict = None) -> None:
        """Логирует исходящий запрос."""
        logger.debug("=" * 80)
        logger.debug("[HTTP] → %s %s", method, url)
        if params:
            logger.debug("[HTTP]    Params: %s", params)
        if headers:
            # Скрываем чувствительные данные
            safe_headers = {k: (v[:50] + '...' if len(v) > 50 and k.lower() == 'cookie' else v) 
                           for k, v in headers.items()}
            logger.debug("[HTTP]    Headers: %s", safe_headers)
        if data:
            data_str = str(data)[:500]
            logger.debug("[HTTP]    Body: %s", data_str)

    @staticmethod
    async def log_response(status: int, url: str, content_type: str = None, 
                          content_length: int = None, cookies: dict = None) -> None:
        """Логирует ответ."""
        status_emoji = {200: "✅", 201: "✅", 400: "❌", 401: "⚠️", 403: "⚠️", 404: "❌", 429: "⚠️", 500: "❌"}
        emoji = status_emoji.get(status, "❓")
        
        logger.debug("[HTTP] %s ← %d %s", emoji, status, url)
        if content_type:
            logger.debug("[HTTP]    Content-Type: %s", content_type)
        if content_length:
            logger.debug("[HTTP]    Content-Length: %s", content_length)
        if cookies:
            logger.debug("[HTTP]    New Cookies: %s", list(cookies.keys()))

    @staticmethod
    async def log_cookies(cookies: dict, source: str = "") -> None:
        """Логирует текущие куки."""
        logger.debug("[COOKIES] %s: %d кук", source, len(cookies))
        for key, value in cookies.items():
            val_display = value[:30] + '...' if len(value) > 30 else value
            logger.debug("[COOKIES]   %s = %s", key, val_display)

def _get_platform_ua() -> tuple[str, str]:
    """Возвращает UserAgent и platform для текущей ОС.

    Если USE_PLATFORM_UA=true, генерирует для текущей платформы.
    Иначе всегда возвращает Windows (по умолчанию, для совместимости).
    """
    system = platform.system()

    if not config.use_platform_ua or system == "Windows":
        # По умолчанию Windows (работает везде)
        return (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36',
            '"Windows"'
        )
    elif system == "Darwin":
        # macOS
        return (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36',
            '"macOS"'
        )
    else:
        # Linux и остальное
        return (
            'Mozilla/5.0 (X11; Linux x86_64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36',
            '"Linux"'
        )


def _get_base_headers() -> dict[str, str]:
    """Возвращает базовые заголовки с поддержкой кроссплатформенности."""
    ua, platform_header = _get_platform_ua()

    return {
        "accept": "*/*",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": f"{config.api_base_url}/catalog/markdown/",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform_header,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": ua,
        "x-requested-with": "XMLHttpRequest",
    }


# Кэшируем базовые заголовки один раз при импорте
_BASE_HEADERS = _get_base_headers()


def _parse_cookie_str(raw: str) -> dict[str, str]:
    """Разбирает строку куки 'key=value; key2=value2' в словарь."""
    result: dict[str, str] = {}
    if not raw:
        return result
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
    return result


class SessionManager:
    """Управляет HTTP-сессией: куки, CSRF-токен."""

    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}
        self._session: aiohttp.ClientSession | None = None
        self._csrf_token: str = ""
        self._initialized = False

    def _extract_cookies_from_response(self, resp: aiohttp.ClientResponse) -> None:
        """Извлекает куки из Set-Cookie заголовков ответа и добавляет в self._cookies.

        ВАЖНО: НЕ перезаписываем куки города (current_path, city_path) — они строятся программно!
        """
        # Кुки города НЕ должны перезаписываться сервером
        protected_cookies = {'current_path', 'city_path'}

        # Извлекаем куки из resp.cookies (если есть)
        if resp.cookies:
            for cookie in resp.cookies.values():
                if cookie.key not in protected_cookies:
                    self._cookies[cookie.key] = cookie.value

        # Также проверяем Set-Cookie заголовки напрямую
        set_cookies = resp.headers.getall('Set-Cookie', [])
        for sc in set_cookies:
            # Парсим "name=value; Path=/; ..."
            pair = sc.split(';')[0].strip()
            if '=' in pair:
                key, _, value = pair.partition('=')
                if key.strip() not in protected_cookies:
                    self._cookies[key.strip()] = value.strip()

        if self._cookies:
            logger.debug("[SESSION] Извлечены куки из ответа: %s", list(self._cookies.keys())[:5])

            # DEBUG: логируем город куки
            if 'city_path' in self._cookies:
                logger.debug("[SESSION] city_path из ответа: %s", self._cookies['city_path'])

            # DEBUG: логируем current_path если присутствует
            if 'current_path' in self._cookies:
                cp = self._cookies['current_path']
                logger.debug("[SESSION] current_path из ответа: %s...", cp[:100])

    def set_csrf(self, token: str) -> None:
        self._csrf_token = token
        logger.debug("CSRF token обновлён")

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(_BASE_HEADERS)
        if self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token
        if extra:
            headers.update(extra)
        if self._cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            headers["cookie"] = cookie_str
        return headers

    async def _resolve_qrator(self) -> bool:
        """Решает Qrator challenge и импортирует ВСЕ куки dns-shop.ru из браузера.

        UA синхронизируется с Python-сессией — Qrator инвалидирует jsid2,
        если UA в браузере не совпадает с UA последующих HTTP-запросов.
        """
        logger.debug("[SESSION] Решаю Qrator challenge (UA синхронизирован с HTTP)...")
        ua = _BASE_HEADERS["user-agent"]
        qrator_cookies = await resolve_qrator_cookies(user_agent=ua)

        if not qrator_cookies or 'qrator_jsid2' not in qrator_cookies:
            logger.error("[SESSION] ❌ Не удалось решить Qrator challenge")
            return False

        # Защищённые куки строим программно для нужного города —
        # не позволяем браузеру их перезаписать (он может выбрать Москву).
        protected = {'city_path', 'current_path'}
        imported = 0
        for key, value in qrator_cookies.items():
            if key not in protected:
                self._cookies[key] = value
                imported += 1

        logger.info(
            "[SESSION] ✅ Qrator решён, импортировано кук: %d (%s)",
            imported,
            ", ".join(list(qrator_cookies.keys())[:10]),
        )
        return True

    async def _init_session(self, force_qrator: bool = False, _retry_count: int = 0) -> bool:
        """Полная инициализация: чистим состояние → Qrator → город куки из .env.

        force_qrator=True означает, что API вернул 401/403 — предыдущая сессия
        мертва. Чистим Chromium profile, чтобы resolve_qrator не использовал
        протухшую сессию.
        """
        logger.info("[SESSION] Инициализация сессии...")

        # Всегда стартуем с пустыми куками — исключает «протухшие» jsid2
        # от прошлой итерации, из-за которых Qrator мог ругаться.
        self._cookies.clear()

        # Если API явно сказал, что куки протухли — чистим Chromium profile,
        # иначе solve_qrator будет переиспользовать мёртвую сессию.
        if force_qrator and _retry_count == 0:
            logger.info("[SESSION] force_qrator=True → чищу Chromium profile")
            cleanup_chromium_profile()

        # 1. Решаем Qrator challenge (браузер получает все куки: qrator_jsid2, qrator_jsr, qrator_ssid2, PHPSESSID, _csrf и т.д.)
        qrator_success = await self._resolve_qrator()
        if not qrator_success:
            # Если первая попытка не удалась и это не повтор — повторяем
            # (профиль уже очищен в resolve_qrator_cookies на каждый вызов)
            if _retry_count == 0:
                logger.warning("[SESSION] ⚠️ Первая попытка Qrator не удалась, повторяю...")
                await asyncio.sleep(2)
                return await self._init_session(force_qrator=force_qrator, _retry_count=1)
            else:
                logger.error("[SESSION] ❌ КРИТИЧНО: Qrator challenge не решён даже после повтора")
                logger.error("[SESSION] Возможные причины: IP забанен, DNS-Shop усилил защиту, solve_qrator.js неработающий")
                return False

        # 2. Переписываем куки города из .env (браузер может выбрать иной регион, но мы выбираем нужный)
        if not config.city_cookie_current:
            logger.warning("[SESSION] ⚠️ CITY_COOKIE_CURRENT не задан в .env — кука current_path будет пустой")
        self._cookies['city_path'] = config.city_cookie_path
        self._cookies['current_path'] = config.city_cookie_current
        self._cookies['IsInterregionalPickupAllowed'] = 'true'
        self._cookies['IsInterregionalCourierAllowed'] = 'false'
        logger.info("[SESSION] Куки города установлены из .env")

        logger.info(
            "[SESSION] ✅ Сессия инициализирована, всего кук: %d (%s)",
            len(self._cookies),
            ", ".join(list(self._cookies.keys())[:10]),
        )
        self._initialized = True
        return True

    async def _set_city_via_rest(self) -> bool:
        """Вызывает REST API DNS для установки города."""
        logger.debug("[SESSION] Устанавливаю город через REST API")

        connector = aiohttp.TCPConnector(ssl=True, limit=5)
        temp_session = aiohttp.ClientSession(connector=connector)

        try:
            all_cookies = dict(self._cookies)
            cookie_header = "; ".join(f"{k}={v}" for k, v in all_cookies.items())

            headers = {
                "User-Agent": _BASE_HEADERS["user-agent"],
                "Accept": "*/*",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Origin": config.api_base_url,
                "Referer": f"{config.api_base_url}/",
                "Cookie": cookie_header,
            }

            url = "https://restapi.dns-shop.ru/v2/get-city"
            await HTTPLogger.log_request("GET", url, headers=headers)

            async with temp_session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                # Собираем куки из ответа (PHPSESSID может обновиться)
                new_cookies = {}
                if resp.cookies:
                    for cookie in resp.cookies.values():
                        new_cookies[cookie.key] = cookie.value
                        self._cookies[cookie.key] = cookie.value

                set_cookies = resp.headers.getall('Set-Cookie', [])
                for sc in set_cookies:
                    pair = sc.split(';')[0].strip()
                    if '=' in pair:
                        k, _, v = pair.partition('=')
                        new_cookies[k.strip()] = v.strip()
                        self._cookies[k.strip()] = v.strip()

                await HTTPLogger.log_response(
                    resp.status, url,
                    content_type=resp.content_type,
                    cookies=new_cookies if new_cookies else None
                )

                logger.debug("[SESSION] REST API город: статус=%d, куки=%d", resp.status, len(self._cookies))

                return resp.status == 200
                
        except Exception as exc:
            logger.error("[SESSION] Ошибка при установке города через REST: %s", exc)
            return False
        finally:
            await temp_session.close()

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            if not self._initialized:
                await self._init_session()
            
            connector = aiohttp.TCPConnector(ssl=True, limit=5)
            # ВАЖНО: DummyCookieJar — aiohttp НЕ должен управлять куками за нас.
            # Куки отправляем вручную через Cookie header.
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers=self._build_headers(),
                cookie_jar=aiohttp.DummyCookieJar(),
            )
            logger.debug(
                "[SESSION] HTTP-сессия создана, куки: %d", len(self._cookies)
            )
        return self._session

    async def _get_csrf_token(self) -> str | None:
        """Получает CSRF токен из кук или со страницы логина."""
        try:
            # Сначала пробуем из кук (если есть _csrf)
            if '_csrf' in self._cookies:
                csrf = self._cookies['_csrf']
                logger.debug("[SESSION] CSRF токен взят из кук: %s", csrf[:30] if len(csrf) > 30 else csrf)
                return csrf

            session = await self.get_session()
            url = f"{config.api_base_url}/auth/"

            logger.debug("[SESSION] Запрос CSRF токена из HTML: %s", url)
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                logger.debug("[SESSION] Ответ CSRF: статус=%d, content-type=%s", 
                           resp.status, resp.content_type)
                
                if resp.status in (401, 403):
                    logger.warning("[SESSION] Страница логина защищена Qrator (%d)", resp.status)
                    return None

                html = await resp.text()
                logger.debug("[SESSION] HTML страницы логина: %d символов", len(html))

                # Ищем CSRF токен в форме
                match = re.search(r'name="dnsauth_csrf"\s+value="([^"]+)"', html)
                if match:
                    csrf = match.group(1)
                    logger.debug("[SESSION] CSRF токен получен из формы")
                    return csrf

                # Fallback: ищем в скрытых полях
                match = re.search(r'value="([a-f0-9]{32,})"', html)
                if match:
                    csrf = match.group(1)
                    logger.debug("[SESSION] CSRF токен получен (fallback): %s", csrf[:30])
                    return csrf
                
                # Попробуем другие паттерны
                match = re.search(r'csrf[_-]?token["\s]*[:=]["\s]*["\']([^"\']+)["\']', html, re.IGNORECASE)
                if match:
                    csrf = match.group(1)
                    logger.debug("[SESSION] CSRF токен получен (pattern 3): %s", csrf[:30])
                    return csrf

                logger.warning("[SESSION] CSRF токен не найден в HTML")
                logger.debug("[SESSION] HTML превью: %s", html[:500])
                return None

        except Exception as exc:
            logger.error("[SESSION] Ошибка при получении CSRF токена: %s", exc)
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[SESSION] HTTP-сессия закрыта")
