#!/usr/bin/env python3
"""Получить куки Краснодара - подставляем напрямую из config."""

import undetected_chromedriver as uc
import time
import pickle
from pathlib import Path
from config import config

print("\n[*] Открываю браузер...")

options = uc.ChromeOptions()
options.add_argument("--window-size=1920,1080")
options.add_argument("--lang=ru-RU")

# Headless режим (без окна браузера)
if config.chrome_headless:
    options.add_argument("--headless=new")
    print("    (headless режим)")

options.add_experimental_option("prefs", {
    "profile.managed_default_content_settings.geolocation": 2,
})

driver = uc.Chrome(options=options, use_subprocess=True)

try:
    # Открываем главную страницу
    print("[*] Переходу на dns-shop.ru...")
    driver.get("https://www.dns-shop.ru")
    time.sleep(1)

    # Добавляем куки Краснодара из конфига
    print("[*] Добавляю куки Краснодара...")

    driver.add_cookie({
        "name": "city_path",
        "value": config.city_cookie_path,
        "domain": ".dns-shop.ru",
        "path": "/"
    })

    driver.add_cookie({
        "name": "current_path",
        "value": config.city_cookie_current,
        "domain": ".dns-shop.ru",
        "path": "/"
    })

    print("[✓] Куки добавлены")

    # Загружаем markdown страницу с новыми куками
    print("[*] Загружаю markdown страницу...")
    driver.get("https://www.dns-shop.ru/catalog/markdown/")
    time.sleep(3)
    print("[✓] Страница загружена")

    # Получаем все куки браузера
    print("[*] Сохраняю куки...")
    cookies = driver.get_cookies()

    # Проверяем город
    city_path = next((c['value'] for c in cookies if c['name'] == 'city_path'), None)

    if city_path == config.city_cookie_path:
        with open("browser_cookies.pkl", "wb") as f:
            pickle.dump(cookies, f)
        print(f"\n✓ ГОТОВО! {len(cookies)} кук сохранены")
        print("  Следующий шаг: python parser.py\n")
    else:
        print(f"\n✗ ОШИБКА! city_path = {city_path}\n")

except Exception as e:
    print(f"\n✗ ОШИБКА: {e}\n")
    import traceback
    traceback.print_exc()

finally:
    driver.quit()
