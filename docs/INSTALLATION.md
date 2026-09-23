# Installation

## Prerequisites

Python >=3.10, Node/npm, and Chromium managed by Playwright are required. From a source checkout:

```bash
uv sync --extra test
npm ci
npx playwright install chromium
```

On Linux hosts with missing browser libraries use `npx playwright install chromium --with-deps`. Copy `.env.example` to `.env`; shell variables override file values.

## Preflight and tests

Run the safe local prerequisite check before starting. It never starts Telegram polling or a live Qrator challenge.

```bash
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
uv run python -m compileall -q src
```

Exit code `0` means all checks pass; nonzero names the missing or invalid prerequisite. The test command does not require production credentials and runtime files are ignored by git.

## Run

```bash
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
uv run python -m dns_shop_parser bot
```

After editable installation (`uv pip install -e .`), use `dns-parser`, `dns-parser-once --city-slug krasnodar`, and `dns-parser-bot`. A wheel built with `uv build` includes the packaged Qrator resource; install it outside the checkout with `uv pip install dist/dns_shop_parser-*.whl`.

## Configuration

Required Telegram values are `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ADMIN`; optional values include `TELEGRAM_CHAT_ID`, `DB_PATH`, `PARSE_INTERVAL`, `PARSE_CONCURRENCY`, `MAX_RETRIES`, `RETRY_DELAY`, `LOG_LEVEL`, `QRATOR_*`, and `PROXY_*`. Invalid non-positive parse intervals/concurrency fail startup without revealing secrets.

## Runtime behavior

SQLite defaults to `dns_monitor.db`; logs use `logs/`; migration backups use `backups/` beside the database. Backups pass `PRAGMA integrity_check` before publication. A migration failure aborts initialization; keep and verify the pre-migration backup before retrying. The parser prevents duplicate instances with exit code `75`.

For restore, scheduler retry/backoff, monitoring, upgrade, and rollback instructions see [`OPERATIONS.md`](OPERATIONS.md).
