# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DNS Shop Parser — автоматический монитор уценённых товаров на dns-shop.ru. Работает без постоянного браузера: Node.js + Playwright запускается один раз для обхода Qrator WAF, дальнейшие запросы через aiohttp.

**Версия:** 1.7 | **Python:** 3.10+ | **Node.js:** 14+

## Commands

### Development
```bash
python run.py                    # Основной режим (парсинг + Telegram бот + daily scheduler)
python parser.py                 # Однократный парсинг (без бота)
python bot_only.py              # Только Telegram polling (без парсинга)
node solve_qrator.js            # Тест обхода Qrator WAF
```

### Setup
```bash
pip install -r requirements.txt
npm install
npx playwright install chromium
cp .env.example .env           # затем TELEGRAM_TOKEN и TELEGRAM_CHAT_ADMIN
```

### Testing
```bash
pip install -r tests/requirements-test.txt
pytest -q                       # все тесты
pytest -q -k "db_manager"       # по названию
```

## Architecture

```
run.py (asyncio event loop, 3 concurrent tasks)
├── main_cycle()                   ← парсинг с поддержкой управления админом
│   └── parser.py                  ← subprocess (timeout 10 мин), всегда exit 0
│       ├── DNSMonitorBrowserless.run_once()
│       │   ├── qrator_resolver.py → solve_qrator.js (Playwright)
│       │   ├── session_manager.py → aiohttp сессия с куками города
│       │   ├── simple_dns_parser.py → HTTP → категории → UUID → детали
│       │   ├── db_manager.py    → SQLite (upsert, история цен, category_state)
│       │   └── telegram_notifier.py → send_digest / send_admin_alert
│       └── _process_category()  ← parallel с semaphore (PARSE_CONCURRENCY)
├── telegram_bot_polling()         ← Telegram polling (services/telegram_bot/)
│   ├── core.py                    ← TelegramBot class, polling_loop
│   ├── handlers/admin.py          ← /admin panel commands
│   ├── handlers/settings.py       ← user settings (city, categories, threshold)
│   ├── handlers/reports.py        ← report wizard (4 steps)
│   ├── keyboards.py               ← inline keyboard builders
│   └── state.py                   ← UserState, ReportState
├── daily_scheduler.run_forever()  ← каждые 5 мин: daily reports для free-подписчиков
└── ParserController               ← admin start/stop/restart/pause/resume/set_interval
```

**Key execution flow:**
1. `run.py` spawns `parser.py` as subprocess each cycle via `_run_subprocess()`
2. `parser.py` calls `session_manager._init_session()` → runs `solve_qrator.js`
3. `solve_qrator.js` opens headless Chromium, visits DNS, extracts cookies → stdout
4. `DNSMonitorBrowserless.parse_all()` fetches categories → per-category parallel UUID fetch (new/used) → product details → upsert to DB
5. `DBManager.upsert_products()` saves/changes, returns price deltas
6. `TelegramNotifier.send_digest()` sends personal notifications per subscriber settings

## Key Files

| File | Purpose |
|------|---------|
| `run.py` | Entry point: asyncio loop + 3 tasks (main_cycle, TG bot, daily_scheduler). Night mode schedule, cron sync, circuit breaker (5 errors → exponential backoff), single-instance lock via fcntl |
| `parser.py` | Single parse cycle as subprocess. Runs `DNSMonitorBrowserless.run_once()`. **Always exits 0** — don't change without architectural decision |
| `bot_only.py` | Standalone Telegram bot (no parsing). Useful for admin management while parser runs elsewhere |
| `config.py` | `Config` dataclass from `.env`. Module-level singleton `config`. Dataclass default `parse_concurrency=3`, env override defaults to `5` |
| `data/cities.py` | City metadata: `CITIES`, `CITY_COOKIES`, `SLUG_TO_CITY`, `DEFAULT_CITY_SLUG="krasnodar"`. User city selection maps to cookie overrides |
| `solve_qrator.js` | Node.js + Playwright for Qrator WAF bypass. Outputs cookies to stdout |
| `parser/qrator_resolver.py` | Runs `solve_qrator.js`, parses output, handles retries (3 attempts), preflight check |
| `parser/session_manager.py` | aiohttp session, headers, cookie override per city, proxy reset |
| `parser/simple_dns_parser.py` | HTTP fetcher: categories → UUID pagination (per status) → product details via POST |
| `parser/db_manager.py` | SQLite CRUD. Auto-backup on migrations, `upsert_products()` returns price changes, category_state tracking |
| `parser/models.py` | `Product` dataclass, `Category` model |
| `parser/exceptions.py` | Custom exceptions |
| `services/telegram_bot/` | Telegram bot package: core (polling), handlers/admin/settings/reports, keyboards, state machine |
| `services/telegram_notifier.py` | Digest formatting, admin alerts, daily report distribution |
| `services/admin_panel.py` | `ParserController`: start/stop/restart/pause/resume/set_interval |
| `services/daily_scheduler.py` | Scheduled daily reports for free subscribers (runs every 300s) |
| `utils/logger.py` | RotatingFileHandler (10MB × 5) + StreamHandler, named "dns_monitor" |

## Database Schema

SQLite `dns_monitor.db` (configurable via `DB_PATH`):
- `products` — товары с `uuid`, `status` (Новый/Б/У), `is_sold`, `city_slug`
- `price_history` — история цен при изменении
- `category_state` — `(category_id, city_slug)` composite PK, `uuid_hash` for change detection
- `telegram_subscribers` — подписчики с soft delete (`is_active`)
- `user_settings` — персональные настройки (город, порог скидки, фильтр категорий)
- `user_categories` — выбранные категории `(user_id, city_slug, category_id)` — per-city selection
- `scheduled_events` — для daily reports и schedule maintenance events

## Configuration (.env)

Required for basic operation:
- `TELEGRAM_TOKEN` — bot token (validation: length ≥ 10 if set)
- `TELEGRAM_CHAT_ADMIN` — admin user ID (enables `/admin` panel and alerts)

Optional:
- `TELEGRAM_CHAT_ID` — secondary chat target for notifications
- `TELEGRAM_ADMIN_TOKEN` — separate admin bot token (optional)
- `API_BASE_URL` — DNS API base (default: `https://www.dns-shop.ru`)
- `DB_PATH` — SQLite path (default: `dns_monitor.db`)
- `PARSE_INTERVAL` — seconds between parse cycles (default: 3600)
- `PARSE_CONCURRENCY` — parallel category processing (dataclass default: 3, env override: 5)
- `MAX_RETRIES` — HTTP retry count (default: 4)
- `RETRY_DELAY` — delay between retries in seconds (default: 5.0)
- `LOG_LEVEL` — DEBUG/INFO/WARNING/ERROR (default: INFO)
- `QRATOR_INIT_TIMEOUT` — browser init timeout, sec (Linux default: 360, others: 330)
- `QRATOR_NODE_TIMEOUT` — Node.js execution timeout (default: 300)
- `QRATOR_PROXY_CHECK_TIMEOUT` — proxy health check timeout (default: 20)
- `USE_PLATFORM_UA` — real OS User-Agent vs Windows compatibility UA (default: false)

Proxy (optional):
- `PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, `PROXY_PASSWORD` — pool.proxy.market:10000–10999

## Important Behaviors

- **Qrator cookies**: Reused across cycles via persistent Chromium profile. On Windows/macOS: `~/.dns-parser-chromium/`. On Linux: temporary profile per run.
- **Schedule**: Krasnodar parses 07:00–20:00 MSK; Moscow/SPB parse once in 00:00–06:00 MSK with staggered scheduling via `scheduled_events` table
- **Cron sync**: Sleeps to align with hour boundaries (interval 3600 → :00, :60; 1800 → :00, :30)
- **Circuit breaker**: After 5 consecutive errors → exponential backoff (up to 60 min), alert to admin
- **parser.py exits 0**: Intentionally — temporary DNS/Qrator/Node/network failures shouldn't stop the service. Don't change without architectural decision.
- **City selection per city**: User category filters are scoped by `(user_id, city_slug)` — switching cities shows different category selections

## Proxy Support

Pool proxy: `pool.proxy.market:10000–10999`. Config via `PROXY_HOST`/`PROXY_PORT` in `.env`. Parallelism is controlled only by `PARSE_CONCURRENCY`. Proxy pool is reset between parse cycles.

## Dependencies

Python: `aiohttp==3.9.1`, `tenacity==8.2.3`, `python-dotenv==1.0.0`
Node.js: `playwright-extra`, `playwright@^1.40.0`
