"""
Менедджер HTTP-сессии для DNS.

Автоматически получает все необходимые куки:
1. GET главная → PHPSESSID, _csrf, auth_public_uid
2. Решаем Qrator → qrator_jsid2
3. Добавляем город → current_path, city_path
4. При 401/403 → полный цикл заново + логин
"""

import hashlib
import json
import re
from urllib.parse import quote

import aiohttp

from config import config
from parser.qrator_resolver import resolve_qrator_cookies
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

# Заголовки — максимально близко к реальному браузеру
_BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": f"{config.api_base_url}/catalog/markdown/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}


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


def _build_city_cookie() -> dict[str, str]:
    """Создаёт куки города в формате DNS.
    
    ВАЖНО: DNS использует JSON с ensure_ascii=True (Unicode escapes \u041a\u0440...)
    Реальная кука из браузера:
      current_path=<sha256_hash><urlencoded_php_serialized>
    
    Формат PHP сериализации:
      a:2:{i:0;s:12:"current_path";i:1;s:<len>:"<json>";}
    """
    cookies = {}

    cookies['city_path'] = 'krasnodar'

    # Дополнительные куки которые DNS может проверять
    # ВАЖНО: IsInterregionalPickupAllowed=true позволяет получать товары из других регионов
    cookies['IsInterregionalPickupAllowed'] = 'true'
    cookies['IsInterregionalCourierAllowed'] = 'false'

    # ВАЖНО: ensure_ascii=True для Unicode escapes (\u041a\u0440...)
    # separators=(',', ':') чтобы НЕ было пробелов после : и ,
    city_data = {
        "city": config.city_id,
        "cityName": config.city_name,
        "method": "manual"
    }
    city_json = json.dumps(city_data, ensure_ascii=True, separators=(',', ':'))  # <-- ИСПРАВЛЕНО!

    logger.info("[COOKIE] Строю current_path для города: %s (ID=%s)", config.city_name, config.city_id)
    logger.debug("[COOKIE] city_data JSON: %s", city_json)

    # PHP сериализация: a:2:{i:0;s:12:"current_path";i:1;s:<len>:"<json>";}
    php_serialized = f'a:2:{{i:0;s:12:"current_path";i:1;s:{len(city_json)}:"{city_json}";}}'

    # SHA256 хеш PHP сериализации
    sha256_hash = hashlib.sha256(php_serialized.encode('utf-8')).hexdigest()

    # URL-кодирование
    encoded = quote(php_serialized, safe='')

    # Формат: <hash><encoded_payload>
    cookies['current_path'] = f'{sha256_hash}{encoded}'

    logger.debug("[COOKIE] current_path сгенерирован: hash=%s, len=%d", sha256_hash[:16], len(cookies['current_path']))
    logger.debug("[COOKIE] full current_path: %s", cookies['current_path'][:100])

    return cookies


class SessionManager:
    """Управляет HTTP-сессией: куки, CSRF-токен."""

    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}
        self._session: aiohttp.ClientSession | None = None
        self._csrf_token: str = ""
        self._initialized = False

    def _extract_cookies_from_response(self, resp: aiohttp.ClientResponse) -> None:
        """Извлекает куки из Set-Cookie заголовков ответа и добавляет в self._cookies."""
        # Извлекаем куки из resp.cookies (если есть)
        if resp.cookies:
            for cookie in resp.cookies.values():
                self._cookies[cookie.key] = cookie.value

        # Также проверяем Set-Cookie заголовки напрямую
        set_cookies = resp.headers.getall('Set-Cookie', [])
        for sc in set_cookies:
            # Парсим "name=value; Path=/; ..."
            pair = sc.split(';')[0].strip()
            if '=' in pair:
                key, _, value = pair.partition('=')
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

    async def _fetch_base_cookies(self) -> bool:
        """
        Получает PHPSESSID через каталог (там нет Qrator если есть qrator_jsid2).
        """
        logger.debug("[SESSION] Получаю базовые куки через каталог...")

        connector = aiohttp.TCPConnector(ssl=True, limit=5)
        temp_session = aiohttp.ClientSession(connector=connector)

        try:
            qrator_id2 = self._cookies.get('qrator_jsid2', '')

            headers = {
                "User-Agent": _BASE_HEADERS["user-agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Cookie": f"qrator_jsid2={qrator_id2}; city_path=krasnodar",
            }

            # Пробуем каталог — он меньше защищён
            urls_to_try = [
                f"{config.api_base_url}/catalog/markdown/",
                f"{config.api_base_url}/",
            ]

            for url in urls_to_try:
                await HTTPLogger.log_request("GET", url, headers=headers)
                
                async with temp_session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                ) as resp:
                    set_cookies = resp.headers.getall('Set-Cookie', [])
                    new_cookies = {}
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

                    if resp.status == 200:
                        logger.debug("[SESSION] Успешный GET %s: %d кук", url, len(self._cookies))
                        break
            
            # Сервер уже отправил current_path в ответе, не перезаписываем
            # Добавляем city_path и важные куки для региональной фильтрации
            if 'city_path' not in self._cookies:
                self._cookies['city_path'] = 'krasnodar'

            self._cookies['IsInterregionalPickupAllowed'] = 'true'
            self._cookies['IsInterregionalCourierAllowed'] = 'false'

            logger.debug(
                "[SESSION] Получено %d кук: %s",
                len(self._cookies),
                list(self._cookies.keys())[:12],
            )
            
            return 'PHPSESSID' in self._cookies or len(self._cookies) > 3
                
        except Exception as exc:
            logger.error("[SESSION] Ошибка при получении базовых кук: %s", exc)
            return False
        finally:
            await temp_session.close()

    async def _resolve_qrator(self) -> bool:
        """Решает Qrator challenge и добавляет qrator_jsid2."""
        logger.debug("[SESSION] Решаю Qrator challenge...")
        
        qrator_cookies = await resolve_qrator_cookies()
        if qrator_cookies and 'qrator_jsid2' in qrator_cookies:
            self._cookies['qrator_jsid2'] = qrator_cookies['qrator_jsid2']
            logger.info("[SESSION] ✅ Qrator challenge решен, jsid2 добавлена")
            return True
        
        logger.error("[SESSION] ❌ Не удалось решить Qrator challenge")
        return False

    async def _init_session(self) -> bool:
        """Полная инициализация: Qrator → базовые куки → город через REST API."""
        logger.info("[SESSION] Инициализация сессии...")
        
        # 1. Сначала решаем Qrator challenge (иначе главная страница вернет 401)
        await self._resolve_qrator()
        
        # 2. Теперь с qrator_jsid2 получаем базовые куки (PHPSESSID, _csrf и т.д.)
        if not await self._fetch_base_cookies():
            logger.warning("[SESSION] Не удалось получить базовые куки, продолжаем...")

        # 3. Убеждаемся что city_path установлен правильно (current_path приходит от сервера)
        if 'city_path' not in self._cookies:
            self._cookies['city_path'] = 'krasnodar'

        # 4. Вызываем REST API для установки города (если нужно)
        if not await self._set_city_via_rest():
            logger.warning("[SESSION] Не удалось установить город через REST API")
        
        logger.info(
            "[SESSION] Сессия инициализирована, всего кук: %d (%s)",
            len(self._cookies),
            ", ".join(list(self._cookies.keys())[:10]),
        )
        self._initialized = True
        return True

    async def _init_session_with_cookies(self, browser_cookies: list[dict]) -> bool:
        """Загружает куки полученные из браузера (где уже выбран правильный город)."""
        logger.info("[SESSION] Загружаю куки из браузера...")

        # Конвертируем куки из формата браузера в наш формат
        for cookie in browser_cookies:
            self._cookies[cookie["name"]] = cookie["value"]

        logger.info(
            "[SESSION] Загружено %d кук из браузера: %s",
            len(self._cookies),
            ", ".join(list(self._cookies.keys())[:10]),
        )

        # Убеждаемся что есть основные куки
        required_cookies = ["PHPSESSID", "city_path"]
        missing = [c for c in required_cookies if c not in self._cookies]
        if missing:
            logger.warning("[SESSION] Отсутствуют куки: %s", missing)
            return False

        self._initialized = True
        return True

    async def _set_city_via_rest(self) -> bool:
        """Вызывает REST API DNS для установки города."""
        logger.debug("[SESSION] Устанавливаю город через REST API: %s", config.city_name)

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
                "cityid": config.city_id,
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
            # Инициализируем только если еще не инициализированы И у нас нет кук браузера
            if not self._initialized and not self._cookies:
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

    async def login_and_refresh_cookies(self) -> bool:
        """
        Полный цикл обновления кук:
        1. Переинициализация сессии (базовые куки + Qrator + город)
        2. Логин для получения PHPSESSID и auth_*
        """
        if not config.dns_login or not config.dns_password:
            logger.error("[SESSION] DNS_LOGIN и DNS_PASSWORD не установлены в .env")
            return False

        logger.info("[SESSION] Обновляю куки через логин...")
        
        # Закрываем старую сессию
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._initialized = False
        
        # 1. Полная переинициализация
        if not await self._init_session():
            logger.error("[SESSION] Не удалось переинициализировать сессию")
            return False
        
        # 2. Получаем CSRF
        csrf_token = await self._get_csrf_token()
        if not csrf_token:
            logger.error("[SESSION] Не удалось получить CSRF токен")
            return False

        # 3. Логин
        session = await self.get_session()
        url = f"{config.api_base_url}/auth/auth/login-password-authorization/"

        try:
            headers = self._build_headers()
            headers["x-csrf-token"] = csrf_token
            headers["origin"] = config.api_base_url

            data = aiohttp.FormData()
            data.add_field("LoginPasswordAuthorizationLoadForm[login]", config.dns_login)
            data.add_field("LoginPasswordAuthorizationLoadForm[password]", config.dns_password)
            data.add_field("LoginPasswordAuthorizationLoadForm[token]", "")

            await HTTPLogger.log_request("POST", url, headers=headers, data="LoginForm[login], LoginForm[password]")

            new_cookies = {}
            
            async with session.post(
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,  # Не следовать редиректам автоматически
            ) as resp:
                logger.debug("[SESSION] Логин ответ: %d", resp.status)
                logger.debug("[SESSION] Location: %s", resp.headers.get('Location', 'N/A'))
                
                # Проверим тело ответа для отладки
                response_text = await resp.text()
                logger.debug("[SESSION] Response body length: %d chars", len(response_text))
                
                # Если редирект - значит логин успешен
                if resp.status in (301, 302, 303, 307, 308):
                    logger.info("[SESSION] ✅ Логин успешен (редирект)!")
                    # Следим за редиректом
                    location = resp.headers.get('Location', '')
                    logger.debug("[SESSION] Redirect to: %s", location)
                    
                    # Выполняем редирект вручную
                    if location.startswith('/'):
                        location = config.api_base_url + location
                    
                    async with session.get(
                        location,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp_final:
                        logger.debug("[SESSION] Финальный ответ: %d", resp_final.status)
                        
                        # Собираем куки из финального ответа
                        if resp_final.cookies:
                            for cookie in resp_final.cookies.values():
                                new_cookies[cookie.key] = cookie.value
                        
                        set_cookies = resp_final.headers.getall('Set-Cookie', [])
                        for sc in set_cookies:
                            pair = sc.split(';')[0].strip()
                            if '=' in pair:
                                k, _, v = pair.partition('=')
                                new_cookies[k.strip()] = v.strip()
                        
                        await HTTPLogger.log_response(
                            resp_final.status, location,
                            content_type=resp_final.content_type,
                            cookies=new_cookies if new_cookies else None
                        )
                
                # Если 200 - собираем куки всё равно
                if resp.status == 200:
                    logger.debug("[SESSION] Логин вернул 200, проверяем куки...")

                # Извлекаем куки из ответа (и из редиректа, и из 200)
                if resp.cookies:
                    for cookie in resp.cookies.values():
                        new_cookies[cookie.key] = cookie.value

                # Также из Set-Cookie
                set_cookies = resp.headers.getall('Set-Cookie', [])
                for sc in set_cookies:
                    pair = sc.split(';')[0].strip()
                    if '=' in pair:
                        k, _, v = pair.partition('=')
                        new_cookies[k.strip()] = v.strip()

                await HTTPLogger.log_response(
                    resp.status, url,
                    content_type=resp.content_type,
                    cookies=new_cookies if new_cookies else None
                )

                logger.debug("[SESSION] Новых кук из логина: %d", len(new_cookies))
                
                if new_cookies:
                    # Сохраняем qrator_jsid2 и город, остальное обновляем
                    old_jsid2 = self._cookies.get('qrator_jsid2')
                    self._cookies.update(new_cookies)
                    if old_jsid2:
                        self._cookies['qrator_jsid2'] = old_jsid2
                    
                    logger.info("[SESSION] ✅ Логин успешен! Всего кук: %d", len(self._cookies))

                    # Пересоздаём сессию
                    if self._session and not self._session.closed:
                        await self._session.close()
                    self._session = None
                    await self.get_session()

                    return True
                else:
                    logger.warning("[SESSION] Логин не вернул куки (статус %d)", resp.status)
                    return False

        except Exception as exc:
            logger.error("[SESSION] Ошибка при логине: %s", exc)
            return False

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[SESSION] HTTP-сессия закрыта")
