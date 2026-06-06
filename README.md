# DNS Shop Parser

Автоматический мониторинг скидок в DNS Shop с персонализированными уведомлениями через Telegram-бот.

## Что изменено в структуре

Проект переведён на более стандартную Python-структуру:

- основной пакет расположен в `src/dns_shop_parser`
- добавлен `pyproject.toml`
- сохранена обратная совместимость через корневые entrypoint-файлы
- добавлен shim-пакет `dns_shop_parser/` для работы `python -m dns_shop_parser` из корня проекта

## Возможности

- персонализация по городу, категориям и порогу скидки
- уведомления только по релевантным новым товарам и снижению цен
- автовосстановление после ошибок и circuit breaker
- гибридная архитектура Node.js + Python для обхода Qrator и парсинга

## Быстрый старт

```bash
npm install
npx playwright install chromium
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Альтернативный запуск:

```bash
python -m dns_shop_parser
```

## Структура проекта

```text
.
├── dns_shop_parser/           # shim-пакет для запуска из корня
├── src/
│   └── dns_shop_parser/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── data/
│       ├── parser/
│       ├── services/
│       ├── utils/
│       └── entrypoints/
├── run.py                     # legacy entrypoint
├── parser.py                  # legacy entrypoint
├── bot_only.py                # legacy entrypoint
└── config.py                  # legacy compatibility import
```

## Совместимость

Старые точки входа и импорты сохранены:

- `python run.py`
- `python parser.py --city-slug krasnodar`
- `python bot_only.py`
- `from config import config`
- `from parser.db_manager import DBManager`

Это сделано специально, чтобы рефакторинг не ломал существующие скрипты и тесты.

## Конфигурация

### Обязательные параметры `.env`

```env
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ADMIN=your_telegram_user_id
```

### Дополнительные настройки

```env
API_BASE_URL=https://www.dns-shop.ru
DB_PATH=dns_monitor.db
PARSE_INTERVAL=3600
PARSE_CONCURRENCY=5
LOG_LEVEL=INFO
PROXY_HOST=
PROXY_PORT=0
PROXY_USER=
PROXY_PASSWORD=
```

## Команды разработчика

```bash
python run.py
python parser.py --city-slug krasnodar
python bot_only.py
python -m dns_shop_parser
node solve_qrator.js

pip install -r tests/requirements-test.txt
pytest -q
```

## Архитектура

```text
run.py / dns_shop_parser.entrypoints.run
└── main_cycle()
    └── parser.py / dns_shop_parser.entrypoints.parser
        ├── parser/qrator_resolver.py -> solve_qrator.js
        ├── parser/session_manager.py
        ├── parser/simple_dns_parser.py
        ├── parser/db_manager.py
        └── services/telegram_notifier.py
```

## Поддерживаемые города

- Краснодар: парсинг каждый час с 07:00 до 20:00 МСК
- Москва: ночной парсинг с 00:00 до 06:00 МСК
- Санкт-Петербург: ночной парсинг с 00:00 до 06:00 МСК

## База данных

SQLite (`dns_monitor.db`):

- `products`
- `price_history`
- `category_state`
- `telegram_subscribers`
- `user_settings`
- `user_categories`

## Особенности

- `parser.py` намеренно завершается с кодом `0`
- Qrator cookies переиспользуются между циклами
- расписание разделено на дневной и ночной режимы
- пакет импортируется и через `src` layout, и через запуск из корня проекта

## Лицензия

Проект создан для личного использования и образовательных целей.
