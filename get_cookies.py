#!/usr/bin/env python3
"""Получить куки Краснодара - подставляем напрямую из config."""

import sys
import os
from pathlib import Path

# Добавляем директорию проекта в sys.path для импорта модулей
PROJECT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

import undetected_chromedriver as uc
import time
import pickle
import platform
import shutil
from config import config

print("\n[*] Открываю браузер Chrome...")

# Определяем ОС для поиска Chrome
system = platform.system()
browser_executable = None

if system == "Windows":
    print("    Режим: Windows")
    chrome_paths = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        str(Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"),
    ]
    for path in chrome_paths:
        if Path(path).exists():
            browser_executable = path
            break

elif system == "Linux":
    print("    Режим: Linux")
    chrome_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
        "/snap/bin/google-chrome",
    ]
    for path in chrome_paths:
        if Path(path).exists():
            browser_executable = path
            break

# Опции Chrome (одинаковые для всех платформ)
options = uc.ChromeOptions()
options.add_argument("--window-size=1920,1080")
options.add_argument("--lang=ru-RU")

if browser_executable:
    options.binary_location = browser_executable
    print(f"    ✓ Найден Chrome: {browser_executable}")

# Headless режим (без окна браузера)
if config.chrome_headless:
    options.add_argument("--headless=new")
    print("    (headless режим)")

options.add_experimental_option("prefs", {
    "profile.managed_default_content_settings.geolocation": 2,
})

# Запускаем Chrome
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
