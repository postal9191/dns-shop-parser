# Operations

This document is the runtime contract for operators. Run commands from the repository root (or use absolute paths in a service unit). Do not put tokens, databases, logs, or backups in source control.

## Install and verify

### Source checkout

```bash
git clone <repository-url> dns-shop-parser
cd dns-shop-parser
uv sync --extra test
npm ci
npx playwright install chromium
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
uv run python -m compileall -q src
```

`uv sync --extra test` creates the locked development environment. `npm ci` installs the exact Node dependencies from `package-lock.json`; Chromium is installed by Playwright. Node/npm, Python >=3.10, and a Chromium browser are required. For Linux hosts, use `npx playwright install chromium --with-deps` when system libraries are absent.

### Wheel installation

From a directory outside the checkout, after building with `uv build`:

```bash
uv pip install dist/dns_shop_parser-*.whl
preflight --help
dns-parser --help
dns-parser-once --help
dns-parser-bot --help
```

The wheel includes `resources/solve_qrator.js`. The preflight command is local and does not start Telegram, contact DNS Shop, or launch a Qrator challenge. Exit code `0` means all checks passed; nonzero means inspect stderr and fix the named prerequisite.

## Configuration and runtime files

Copy `.env.example` to `.env`. Required values for Telegram operation are `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ADMIN`; `TELEGRAM_CHAT_ID` may be used for notifications. Shell variables override `.env`. Other supported settings include `API_BASE_URL`, `DB_PATH`, `PARSE_INTERVAL`, `PARSE_CONCURRENCY`, `MAX_RETRIES`, `RETRY_DELAY`, `LOG_LEVEL`, `QRATOR_*`, `PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, `PROXY_PASSWORD`, and `USE_PLATFORM_UA`. Secrets are redacted from safe config output and logs.

By default the SQLite state is `dns_monitor.db`, logs are under `logs/`, and migration backups are under `backups/` beside the database. Set `DB_PATH` to relocate the database; the backup directory remains the `backups/` directory beside that database. Ensure all three locations are writable. Runtime files are intentionally git-ignored.

Start the long-running service with `dns-parser` (or `uv run python -m dns_shop_parser run` from a checkout). Run one city with `dns-parser-once --city-slug krasnodar`; run bot polling only with `dns-parser-bot`. A second instance exits with code 75 (exit code 75). Parse failures return 1 unless the entrypoint's lenient option is selected.

## Migrations, backups, and restore

On opening an existing database, schema migrations run before normal work. A migration backup is created first; if migration fails, initialization raises an error and the original database is not treated as successfully upgraded. Do not delete the backup until the upgraded database has been exercised. Backups use SQLite online backup and are published only after `PRAGMA integrity_check` returns `ok`; invalid copies are removed. Retention is limited by the configured DB manager policy (10 recent backups and 30 days by default).

Before restoring, stop every parser/bot process. Verify a candidate without modifying live state:

```bash
python - <<'PY'
import sys
sys.path.insert(0, "src")
from dns_shop_parser.parser.db_manager import DBManager
import os
print(DBManager(os.environ.get("DB_PATH", "dns_monitor.db")).verify_backup("backups/<verified-backup>.db"))
PY
```

The command must print `True`. Copy the verified backup to a separate staging path, preserve the current database, then replace the live DB atomically where practical. Run preflight and a one-off parse before resuming the service. Never restore while SQLite is open by the application.

## Scheduler and failure behavior

The scheduler claims events atomically, leaves failed events in `failed` state for retry up to the configured maximum attempts, and records the last error. Unknown event types are left untouched. The main loop resets its failure counter after a successful iteration. Repeated loop failures use exponential backoff capped at 3600 seconds; cancellation stops the loop. A parser/circuit-breaker failure is logged and delays the next attempt rather than starting overlapping work. An operator may pause/resume parsing through the admin controls; a paused parser must be resumed explicitly.

Monitor `logs/` and service-manager output. Investigate repeated `failed`, `Circuit breaker`, or preflight errors before deleting state.

## Upgrade and rollback

1. Stop the service and record the current Git commit or wheel version.
2. Copy the database and current `backups/` directory to protected storage.
3. Update the checkout, run `uv sync --extra test`, `npm ci`, and browser installation as needed.
4. Run preflight, tests, and compile verification before starting.
5. Start the service and confirm logs show a healthy cycle; retain the migration backup.

To roll back, stop the service, check out the recorded commit (or reinstall the prior wheel), restore the last verified compatible database backup if the migration is not backward-compatible, then run preflight and a one-off parse. Restart only after verification. Keep the failed upgrade's database copy and logs for diagnosis; do not overwrite the only backup.

## CI-equivalent check

```bash
uv sync --extra test --locked
uv run pytest -q
uv run python -m compileall -q src
uv build
npm ci
```
