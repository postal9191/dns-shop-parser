# DNS Shop Parser

Автоматический мониторинг скидок в DNS Shop с персонализированными уведомлениями через Telegram-бот.

## Структура

Проект приведен к стандартной Python-упаковке:

- `src/dns_shop_parser/` - единственный исходный код приложения
- `tests/` - тесты
- `scripts/` - shell/Node утилиты и Qrator solver
- `docs/` - инструкции по установке и Linux-запуску
- корень - только конфиги, README и файлы зависимостей

## Быстрый старт

```bash
npm ci
npx playwright install chromium
pip install -r requirements.txt
cp .env.example .env
```

Запуск из Git Bash / Linux / macOS:

```bash
PYTHONPATH=src python -m dns_shop_parser run
```

PowerShell:

```powershell
$env:PYTHONPATH="src"; python -m dns_shop_parser run
```

cmd.exe:

```cmd
set PYTHONPATH=src && python -m dns_shop_parser run
```

После editable install можно использовать console scripts без `PYTHONPATH`:

```bash
pip install -e .
dns-parser
dns-parser-once --city-slug krasnodar
dns-parser-bot
```

## Команды разработчика

```bash
PYTHONPATH=src python -m dns_shop_parser --help
PYTHONPATH=src python -m dns_shop_parser run
PYTHONPATH=src python -m dns_shop_parser parse --city-slug krasnodar
PYTHONPATH=src python -m dns_shop_parser bot
node scripts/solve_qrator.js
npm run collect:cities

uv sync --extra test
uv run pytest -q
```

## Структура проекта

```text
.
|-- docs/
|   |-- INSTALLATION.md
|   `-- LINUX_SETUP.md
|-- scripts/
|   |-- solve_qrator.js
|   |-- collect_cities.js
|   |-- cities_data.json
|   |-- dns-parser.sh
|   `-- QUICKSTART_LINUX.sh
|-- src/
|   `-- dns_shop_parser/
|       |-- __init__.py
|       |-- __main__.py
|       |-- config.py
|       |-- data/
|       |-- entrypoints/
|       |-- parser/
|       |-- services/
|       `-- utils/
|-- tests/
|-- pyproject.toml
|-- package.json
|-- requirements.txt
`-- README.md
```

## Архитектура

```text
dns_shop_parser.entrypoints.run
`-- main_cycle()
    `-- subprocess: python -m dns_shop_parser.entrypoints.parser
        |-- parser/qrator_resolver.py -> scripts/solve_qrator.js
        |-- parser/session_manager.py
        |-- parser/simple_dns_parser.py
        |-- parser/db_manager.py
        `-- services/telegram_notifier.py
```

## Конфигурация

Обязательные параметры `.env`:

```env
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ADMIN=your_telegram_user_id
```

Дополнительные настройки:

```env
API_BASE_URL=https://www.dns-shop.ru
DB_PATH=dns_monitor.db
PARSE_INTERVAL=3600        # секунды между циклами (> 0, обязательно)
PARSE_CONCURRENCY=5        # параллельных категорий (> 0, обязательно)
LOG_LEVEL=INFO             # DEBUG для подробных HTTP-логов
PROXY_HOST=
PROXY_PORT=0
PROXY_USER=
PROXY_PASSWORD=
```

> Shell-переменные окружения имеют приоритет над `.env` файлом.

## Поддерживаемые города

- Краснодар: парсинг каждый час с 07:00 до 20:00 МСК
- Москва: ночной парсинг с 00:00 до 06:00 МСК
- Санкт-Петербург: ночной парсинг с 00:00 до 06:00 МСК

Города можно включать/отключать через админ-панель бота без правки кода.

## База данных

SQLite (`dns_monitor.db`) с WAL-режимом и автоматическими бэкапами:

- `products` — товары с UUID и ценами
- `price_history` — история изменения цен
- `category_state` — состояние категорий
- `telegram_subscribers` — подписчики
- `user_settings` — настройки пользователей
- `user_categories` — категории пользователей
- `scheduled_events` — запланированные события (с claim/lease для защиты от дублей)
- `global_settings` — глобальные настройки (отключённые города и т.д.)

## Безопасность

- **Single-instance lock**: кроссплатформенный (Linux + Windows), предотвращает запуск двух экземпляров
- **Redaction секретов**: cookies, CSRF-токены, authorization headers и Telegram-токены не попадают в логи
- **SQLite integrity check**: каждый backup проходит `PRAGMA integrity_check` перед публикацией
- **WAL + busy_timeout**: соединения корректно закрываются, `foreign_keys=ON`
- **Config validation**: `PARSE_INTERVAL` и `PARSE_CONCURRENCY` должны быть > 0
- **HTML-fallback отключён**: Qrator/HTML ответ не парсится как категории (защита от false sold)

## Exit codes

- `0` — успешный парсинг
- `1` — ошибка парсинга (по умолчанию; используйте `--lenient-exit-code` для `0` при провале)
- `75` — уже запущен другой экземпляр (EX_TEMPFAIL)

## Тесты

```bash
uv sync --extra test
uv run pytest -q                    # быстрый прогон
uv run pytest --cov=dns_shop_parser # с покрытием
```

`pyproject.toml` — единственный источник Python-зависимостей для тестов;
`tests/requirements-test.txt` оставлен только как совместимая точка входа для `pip`.

Текущее покрытие: ~70% (branch coverage).

## Особенности

- Qrator cookies переиспользуются между циклами
- расписание разделено на дневной и ночной режимы
- scheduler использует atomic claim/lease для защиты от двойной обработки
- root runtime-файлы (`logs/`, `backups/`, `dns_monitor.db`, `coverage_html/`) игнорируются git
