# DNS Shop Parser

Асинхронный мониторинг уцененных товаров DNS с Telegram-ботом, персональными настройками и планами подписки.

## Что изменилось (актуально на 2026-05-08)

- Город больше не задается через `.env` (`CITY_COOKIE_*` удалены).
- Региональные cookie хранятся в `data/cities.py`.
- `parser.py` поддерживает `--city-slug`.
- `run.py` запускает:
  - дневной парсинг для `krasnodar` с 07:00 до 20:00 МСК,
  - ночные запуски по другим городам в окне 00:00–06:00 МСК,
  - `DailyScheduler` для daily-ивентов free-плана.
- В БД добавлены `plan_type`, `report_limits`, `scheduled_events`.
- Дайджесты для `pro/super` фильтруются в `TelegramNotifier.send_digest(..., plan_types=...)`.

## Требования

- Python 3.10+
- Node.js 18+
- npm

## Быстрый старт

```bash
npm install
npx playwright install chromium
pip install -r requirements.txt
cp .env.example .env
python run.py
```

## Конфигурация (`.env`)

Обязательные:

- `TELEGRAM_TOKEN` — токен бота
- `TELEGRAM_CHAT_ADMIN` — Telegram user id администратора

Основные:

- `API_BASE_URL` (по умолчанию `https://www.dns-shop.ru`)
- `DB_PATH` (по умолчанию `dns_monitor.db`)
- `PARSE_INTERVAL` (по умолчанию `3600`)
- `PARSE_CONCURRENCY` (по умолчанию `5`)
- `MAX_RETRIES` (по умолчанию `4`)
- `RETRY_DELAY` (по умолчанию `5.0`)
- `LOG_LEVEL` (`DEBUG|INFO|WARNING|ERROR`)

Qrator/Node timeouts:

- `QRATOR_INIT_TIMEOUT` (Linux default `360`, прочие `330`)
- `QRATOR_NODE_TIMEOUT` (default `300`)
- `QRATOR_PROXY_CHECK_TIMEOUT` (default `20`)

User-Agent:

- `USE_PLATFORM_UA=true|false` (default `false`)

Proxy:

- `PROXY_HOST`
- `PROXY_PORT`
- `PROXY_USER`
- `PROXY_PASSWORD`

## Запуск

Один проход:

```bash
python parser.py --city-slug krasnodar
```

Основной сервис:

```bash
python run.py
```

## Поддерживаемые города

Сейчас в коде:

- `moscow`
- `spb`
- `krasnodar`

Источник: `data/cities.py`.

## Планы и отчеты

- `free`: дневной отчет через `DailyScheduler`, ограничения по категориям (`report_limits`).
- `pro`, `super`: получают основной парсерный дайджест (новинки + падения цен).

## База данных

Ключевые таблицы:

- `products`
- `price_history`
- `category_state`
- `telegram_subscribers`
- `user_settings` (`plan_type`, настройки уведомлений)
- `user_categories`
- `report_limits`
- `scheduled_events`

Миграции выполняются автоматически при старте `DBManager`.

## Тесты

```bash
pip install -r tests/requirements-test.txt
pytest -q
```

## Важно

- Не коммитьте `.env`.
- При изменении логики городов обновляйте `data/cities.py` и документацию одновременно.
## 2026-05-08: Category City Isolation

- `user_categories` now stores categories by `(user_id, city_slug, category_id)`.
- Category settings, report filters, and digest filtering use user's current `city_slug`.
- Category IDs can overlap between cities safely; categories are isolated per city.
- Empty category selection still means "all categories", but only inside current city.

## 2026-05-08: Test Logging Isolation

- Pytest no longer writes noisy admin callback/start-stop series into `logs/app.log`.
- Test run logging for `dns_monitor` is isolated in tests (`WARNING` level, file handler detached).
