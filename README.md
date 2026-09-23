# DNS Shop Parser

Автоматический мониторинг DNS Shop с уведомлениями через Telegram.

## Быстрый старт из исходников

```bash
uv sync --extra test
npm ci
npx playwright install chromium
cp .env.example .env
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
uv run python -m dns_shop_parser run
```

Python >=3.10, Node/npm, Playwright and Chromium are required. On Linux, use `npx playwright install chromium --with-deps` if browser libraries are missing. The safe preflight returns `0` when Python/config/directories/SQLite/Node/Playwright/Chromium and the packaged Qrator resource are available; otherwise it returns nonzero and names the failed check. It does not start polling or contact production services.

For a complete installation, state, backup, scheduler, restore, rollback, and monitoring procedure see [`docs/OPERATIONS.md`](docs/OPERATIONS.md). Linux-specific service setup is in [`docs/LINUX_SETUP.md`](docs/LINUX_SETUP.md).

## Wheel installation

Build with `uv build`, then from outside the checkout install the wheel and check its commands:

```bash
uv pip install dist/dns_shop_parser-*.whl
preflight --help
dns-parser --help
dns-parser-once --help
dns-parser-bot --help
```

## Commands

```bash
uv run python -m dns_shop_parser --help
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
uv run python -m dns_shop_parser bot
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
```

After installation the equivalent console scripts are `dns-parser`, `dns-parser-once`, `dns-parser-bot`, and `preflight`. The parser uses exit code `75` when another instance owns the lock and `1` for an ordinary parse failure.

## Configuration and runtime state

Copy `.env.example` to `.env`; shell variables override it. Required Telegram settings are `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ADMIN`. Common settings include `DB_PATH`, `PARSE_INTERVAL`, `PARSE_CONCURRENCY`, `LOG_LEVEL`, `QRATOR_*`, and `PROXY_*`. State defaults to `dns_monitor.db`, logs to `logs/`, and migration backups to `backups/` beside the database. Secrets, cookies, CSRF tokens, and authorization headers are redacted from logs. SQLite uses WAL, `busy_timeout=5000`, and foreign keys.

## Tests and CI-equivalent verification

```bash
uv sync --extra test --locked
uv run pytest -q
uv run python -m compileall -q src
uv build
npm ci
```

## Project layout

- `src/dns_shop_parser/` — application code and packaged `resources/solve_qrator.js`
- `scripts/` — Node and Linux helpers
- `docs/` — installation, Linux, and operations procedures
- `tests/` — automated tests
