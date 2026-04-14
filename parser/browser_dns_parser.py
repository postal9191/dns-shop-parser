"""
Парсер на реальном Chrome браузере через undetected-chromedriver.
Маскируется под живого пользователя, обходит Qrator WAF.
"""

import asyncio
import re
import time
import random
from typing import Optional

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from config import config
from parser.models import Product
from utils.logger import logger


class BrowserDNSParser:
    """Браузерный парсер DNS-shop.ru с поддержкой умной категоризации."""

    TARGET_URL = "https://www.dns-shop.ru/catalog/markdown/"

    def __init__(self) -> None:
        self._driver: Optional[uc.Chrome] = None
        self._city_name = config.city_name

    def _start_browser(self) -> None:
        """Запускает Chrome с anti-detection опциями."""
        logger.info("[BROWSER] Запускаем Chrome...")
        options = uc.ChromeOptions()
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=ru-RU")
        options.add_argument("--disable-blink-features=AutomationControlled")

        if config.chrome_headless:
            options.add_argument("--headless=new")

        if config.chrome_profile_dir:
            options.add_argument(f"--user-data-dir={config.chrome_profile_dir}")

        self._driver = uc.Chrome(options=options, use_subprocess=True)
        self._driver.implicitly_wait(10)
        logger.info("[BROWSER] Chrome запущен")

    def close(self) -> None:
        """Закрывает браузер."""
        if self._driver:
            try:
                self._driver.quit()
                logger.debug("[BROWSER] Браузер закрыт")
            except Exception as exc:
                logger.warning("[BROWSER] Ошибка при закрытии браузера: %s", exc)
            self._driver = None

    async def close_async(self) -> None:
        """Async обёртка для close()."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.close)

    def _select_city(self) -> bool:
        """Выбирает город через UI. Возвращает True если успешно."""
        logger.info("[BROWSER] Выбираем город: %s", self._city_name)
        try:
            # Ищем кнопку города по тексту или атрибутам (селекторы могут быть минифицированы)
            # Используем XPath для большей гибкости
            city_buttons = self._driver.find_elements(
                By.XPATH,
                "//*[contains(@class, 'city') and contains(text(), 'Краснодар')] | "
                "//*[@class and contains(text(), 'Краснодар')] | "
                "//button[contains(., 'Краснодар')]"
            )

            if not city_buttons:
                logger.debug("[BROWSER] Кнопка города не найдена, пропускаем смену города")
                return False

            city_buttons[0].click()
            time.sleep(random.uniform(0.3, 0.7))
            logger.info("[BROWSER] Город успешно выбран (или уже установлен)")
            return True

        except Exception as exc:
            logger.debug("[BROWSER] Город не менялся (уже выбран): %s", str(exc)[:100])
            # Это не критичная ошибка — браузер может быть уже в нужном городе
            return True

    def _get_category_counts_from_sidebar(self) -> dict[str, tuple[str, int]]:
        """Читает счётчики категорий из боковой панели (без скролла)."""
        result = {}
        try:
            items = self._driver.find_elements(
                By.CSS_SELECTOR,
                ".catalog-filter__item, .filter-items__item, [data-category-id]"
            )
            for item in items:
                try:
                    # Название категории
                    name_el = item.find_element(
                        By.CSS_SELECTOR,
                        ".catalog-filter__item-label, .filter-items__label, span"
                    )
                    name = name_el.text.strip()

                    # Количество товаров
                    count_el = item.find_element(
                        By.CSS_SELECTOR,
                        ".catalog-filter__item-count, .filter-items__count, em"
                    )
                    count_text = re.sub(r"\D", "", count_el.text) or "0"
                    count = int(count_text)

                    # ID категории из href
                    link = item.find_element(
                        By.CSS_SELECTOR, "a[href*='category'], a[href*='cat=']"
                    )
                    href = link.get_attribute("href") or ""
                    m = re.search(r"[?&](?:category|cat)=([^&]+)", href)
                    if not m:
                        continue

                    cat_id = m.group(1)
                    result[cat_id] = (name, count)
                    logger.debug("[BROWSER] Категория: %s = %d товаров", name, count)

                except Exception:
                    continue
        except Exception as exc:
            logger.warning("[BROWSER] Не удалось прочитать боковые фильтры: %s", exc)

        return result

    def _scroll_to_load_all(self) -> None:
        """Скролл до конца страницы с реалистичными паузами."""
        logger.info("[BROWSER] Начинаем скролл...")
        SCROLL_PAUSE = (1.2, 2.5)
        MAX_STALL = 2  # Если 2 скролла подряд не добавили товаров - конец
        MAX_SCROLLS = 15  # Макс 15 скроллов чтобы избежать краша Chrome при загрузке слишком много товаров

        last_count = 0
        stall = 0

        for scroll_num in range(1, MAX_SCROLLS + 1):
            self._driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Ждём спиннер загрузки
            try:
                WebDriverWait(self._driver, 3).until(
                    EC.invisibility_of_element_located(
                        (By.CSS_SELECTOR, ".products-list__preloader, .spinner")
                    )
                )
            except TimeoutException:
                pass

            time.sleep(random.uniform(*SCROLL_PAUSE))

            current_count = len(
                self._driver.find_elements(By.CSS_SELECTOR, ".catalog-product, .product-card")
            )

            if current_count == last_count:
                stall += 1
            else:
                stall = 0
                last_count = current_count

            logger.debug("[BROWSER] Scroll %d: %d товаров (stall=%d)",
                        scroll_num, current_count, stall)

            if stall >= MAX_STALL:
                logger.info("[BROWSER] Скролл завершён: %d товаров после %d скроллов",
                           current_count, scroll_num)
                break

        self._driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)

    def _parse_products_from_dom(self) -> list[Product]:
        """Парсит карточки товаров из DOM."""
        products = []
        cards = self._driver.find_elements(By.CSS_SELECTOR, ".catalog-product, .product-card")

        for i, card in enumerate(cards, 1):
            try:
                # Название и ссылка
                name_el = card.find_element(
                    By.CSS_SELECTOR, "a.catalog-product__name, .catalog-product__name a"
                )
                title = name_el.text.strip()
                href = name_el.get_attribute("href") or ""

                # UUID из URL
                uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,35}", href)
                if not uuid_match:
                    continue
                product_id = uuid_match.group(0).lower()

                # Текущая цена
                price = 0
                try:
                    price_el = card.find_element(
                        By.CSS_SELECTOR,
                        ".catalog-product__price-current, [class*='price-current']"
                    )
                    price = self._parse_price(price_el.text)
                except NoSuchElementException:
                    pass

                # Старая цена
                price_old = 0
                try:
                    old_el = card.find_element(
                        By.CSS_SELECTOR,
                        ".catalog-product__price-old, [class*='price-old']"
                    )
                    price_old = self._parse_price(old_el.text)
                except NoSuchElementException:
                    pass

                if not title or not product_id:
                    continue

                products.append(Product(
                    id=product_id,
                    title=title,
                    price=price,
                    price_old=price_old,
                    url=href if href.startswith("http") else config.api_base_url + href,
                    category_id="markdown",
                    category_name="Уценка",
                ))

            except Exception as exc:
                logger.debug("[BROWSER] Ошибка при парсинге карточки %d: %s", i, exc)
                continue

        logger.info("[BROWSER] Спарсено товаров: %d", len(products))
        return products

    def _parse_price(self, text: str) -> int:
        """Извлекает цену из строки типа '12 990 ₽'."""
        digits = "".join(re.findall(r"\d", text))
        return int(digits) if digits else 0

    def _scrape_category(self, cat_id: str, cat_name: str) -> list[Product]:
        """Скролл и парс конкретной категории."""
        url = f"{config.api_base_url}/catalog/markdown/?category={cat_id}"
        self._driver.get(url)

        WebDriverWait(self._driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".catalog-product, .product-card")
            )
        )
        time.sleep(random.uniform(1.5, 2.5))

        self._scroll_to_load_all()
        products = self._parse_products_from_dom()

        # Проставляем правильную категорию
        for p in products:
            p.category_id = cat_id
            p.category_name = cat_name

        return products

    def _scrape_sync(self, db_total: int, db_states: dict[str, int]) -> dict:
        """Полный синхронный цикл парсинга с умной логикой."""
        try:
            self._start_browser()
            self._driver.get(self.TARGET_URL)

            # Ждём загрузки каталога
            WebDriverWait(self._driver, 30).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".catalog-product, .product-card")
                )
            )
            time.sleep(random.uniform(2.0, 3.5))

            # Выбираем город
            self._select_city()
            WebDriverWait(self._driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".catalog-product, .product-card")
                )
            )
            time.sleep(random.uniform(1.5, 2.5))

            # Читаем счётчики из боковой панели
            sidebar_counts = self._get_category_counts_from_sidebar()

            # Логика выбора режима
            if db_total == 0 or not sidebar_counts:
                logger.info("[BROWSER] Первый запуск или нет данных в sidebar → полный скан")
                self._scroll_to_load_all()
                products = self._parse_products_from_dom()
                for p in products:
                    p.category_id = "markdown"
                    p.category_name = "Уценка"
                self.close()
                return {"mode": "full", "products": products, "categories": {}}

            # Сравниваем со сохранёнными состояниями
            changed = {
                cat_id: (name, count)
                for cat_id, (name, count) in sidebar_counts.items()
                if db_states.get(cat_id, -1) != count
            }

            if not changed:
                logger.info("[BROWSER] Все категории без изменений, пропускаем")
                self.close()
                return {"mode": "skip", "products": [], "categories": {}}

            # Грузим только изменившиеся категории
            logger.info("[BROWSER] Изменённых категорий: %d", len(changed))
            all_products = []
            for cat_id, (cat_name, new_count) in changed.items():
                old_count = db_states.get(cat_id, 0)
                logger.info("[BROWSER] Категория '%s': %d → %d",
                           cat_name, old_count, new_count)
                products = self._scrape_category(cat_id, cat_name)
                all_products.extend(products)

            self.close()
            return {"mode": "partial", "products": all_products, "categories": changed}

        except Exception as exc:
            logger.error("[BROWSER] Критическая ошибка: %s", exc)
            self.close()
            return {"mode": "error", "products": [], "categories": {}}

    async def fetch_products(self, db_total: int, db_states: dict[str, int]) -> dict:
        """Async обёртка для браузерного парсинга."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._scrape_sync, db_total, db_states
        )
