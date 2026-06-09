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
npm install
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

pip install -r tests/requirements-test.txt
pytest -q
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
PARSE_INTERVAL=3600
PARSE_CONCURRENCY=5
LOG_LEVEL=INFO
PROXY_HOST=
PROXY_PORT=0
PROXY_USER=
PROXY_PASSWORD=
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

- single-run parser намеренно завершает процесс с кодом `0`
- Qrator cookies переиспользуются между циклами
- расписание разделено на дневной и ночной режимы
- root runtime-файлы (`logs/`, `backups/`, `dns_monitor.db`, `coverage_html/`) игнорируются git
