# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DNS Shop Parser — автоматический монитор уценённых товаров на dns-shop.ru. Работает без постоянного браузера: Node.js + Playwright запускается один раз для обхода Qrator WAF, дальнейшие запросы через aiohttp.

**Версия:** 1.7 | **Python:** 3.10+ | **Node.js:** 14+

## Commands

### Development
```bash
python run.py                    # Основной режим (парсинг + Telegram бот)
python parser.py                 # Однократный парсинг (без бота)
node solve_qrator.js            # Тест обхода Qrator WAF
```

### Setup
```bash
pip install -r requirements.txt
npm install
npx playwright install chromium
```

### Telegram Bot Only
```bash
python bot_only.py              # Только Telegram polling (без парсинга)
```

## Architecture

```
run.py (asyncio event loop)
├── main_cycle()           ← парсинг в subprocess каждые N секунд
│   └── parser.py          ← subprocess (timeout 10 мин)
│       ├── qrator_resolver.py → solve_qrator.js (Playwright)
│       ├── session_manager.py → aiohttp сессия с куками
│       ├── simple_dns_parser.py → HTTP → категории → UUID → детали
│       ├── db_manager.py → SQLite (upsert, история цен)
│       └── telegram_notifier.py → персональный дайджест
└── telegram_bot_polling() ← Telegram polling (параллельно)
```

**Key execution flow:**
1. `run.py` spawns `parser.py` as subprocess each cycle
2. `parser.py` calls `session_manager._init_session()` → runs `solve_qrator.js`
3. `solve_qrator.js` opens headless Chromium, visits DNS, extracts cookies → stdout
4. `SimpleDNSParser` fetches categories → UUIDs via HTML regex → product details via POST
5. `DBManager.upsert_products()` saves/changes, returns price deltas
6. `TelegramNotifier.send_digest()` sends personal notifications per subscriber settings

## Key Files

| File | Purpose |
|------|---------|
| `run.py` | Entry point: asyncio loop + TG bot. Handles night mode, cron sync, circuit breaker (5 errors → exponential backoff) |
| `parser.py` | Single parse cycle. Runs as subprocess from run.py, always exits 0 (don't change) |
| `config.py` | `Config` dataclass, loads from `.env`. Proxy support via `PROXY_HOST`, `PROXY_PORT` |
| `solve_qrator.js` | Node.js + Playwright for Qrator bypass. Outputs cookies to stdout |
| `parser/qrator_resolver.py` | Runs `solve_qrator.js`, parses output, handles retries (3 attempts) |
| `parser/session_manager.py` | aiohttp session, headers, cookie override for city |
| `parser/simple_dns_parser.py` | HTTP fetcher: categories → UUID pagination → product details |
| `parser/db_manager.py` | SQLite CRUD. Auto-backup on migrations, `upsert_products()` returns price changes |
| `services/telegram_bot.py` | Bot polling, commands, inline menus, report wizard (4 steps) |
| `services/telegram_notifier.py` | Digest formatting and distribution to subscribers |
| `services/admin_panel.py` | `ParserController`: start/stop/restart/pause/resume/set_interval |
| `utils/logger.py` | RotatingFileHandler (10MB × 5) + StreamHandler |

## Database Schema

SQLite `dns_monitor.db` (configurable via `DB_PATH`):
- `products` — товары с `uuid`, `status` (Новый/Б/У), `is_sold`, `city_slug`
- `price_history` — история цен при изменении
- `category_state` — `(category_id, city_slug)` composite PK, `uuid_hash` for change detection
- `telegram_subscribers` — подписчики с soft delete (`is_active`)
- `user_settings` — персональные настройки (город, порог скидки, фильтр категорий)
- `user_categories` — выбранные категории (пусто = все)

## Configuration (.env)

Required:
- `TELEGRAM_TOKEN` — bot token
- `TELEGRAM_CHAT_ADMIN` — admin user ID (enables `/admin` panel)
- `CITY_COOKIE_PATH` — city slug (e.g., `moscow`, `spb`)
- `CITY_COOKIE_CURRENT` — SHA256 hash for regional override

Optional:
- `PARSE_INTERVAL` — seconds between cycles (default: 3600)
- `PARSE_CONCURRENCY` — parallel category processing (default: 5)
- `LOG_LEVEL` — DEBUG/INFO/WARNING/ERROR
- `PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, `PROXY_PASSWORD` — proxy support

## Important Behaviors

- **Qrator cookies**: Reused across cycles via persistent Chromium profile. On Windows/macOS: `~/.dns-parser-chromium/`. On Linux: temporary profile per run.
- **Schedule**: Krasnodar parses 07:00–20:00 MSK; other cities parse once in 00:00–06:00 MSK
- **Cron sync**: Sleeps to align with hour boundaries (interval 3600 → :00, :60; 1800 → :00, :30)
- **Circuit breaker**: After 5 consecutive errors → exponential backoff (up to 60 min), alert to admin
- **parser.py exits 0**: Intentionally — temporary DNS/Qrator/Node/network failures shouldn't stop the service. Don't change without architectural decision.

## Proxy Support

Pool proxy: `pool.proxy.market:10000`. Config via `PROXY_HOST`/`PROXY_PORT` in `.env`. Parallelism is controlled only by `PARSE_CONCURRENCY`.

## Dependencies

Python: `aiohttp==3.9.1`, `tenacity==8.2.3`, `python-dotenv==1.0.0`
Node.js: `playwright-extra`, `playwright@^1.40.0`
