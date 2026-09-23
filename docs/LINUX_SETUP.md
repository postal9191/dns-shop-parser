# Linux Setup

## Install and preflight

From the project root:

```bash
python3 -m venv venv
. venv/bin/activate
uv sync --extra test
npm ci
npx playwright install chromium --with-deps
cp .env.example .env
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
```

`preflight` exits `0` only when the local runtime prerequisites pass; failures are printed to stderr. It does not poll Telegram or contact DNS Shop.

## Run manually

```bash
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
```

The installed console equivalents are `dns-parser` and `dns-parser-once`. The bot-only command is `dns-parser-bot`.

## systemd helper

```bash
chmod +x scripts/dns-parser.sh
./scripts/dns-parser.sh enable-systemd
sudo systemctl status dns-parser
journalctl -u dns-parser -f
```

The helper resolves the project root and the generated unit runs the package from `src`. A second instance exits `75`; ordinary parse failure exits `1`.

## State, backups, and recovery

The default database is `dns_monitor.db`, logs are in `logs/`, and migration backups are in `backups/` beside the database. SQLite uses WAL, a 5000 ms busy timeout, foreign keys, and online backups validated with `PRAGMA integrity_check`. Stop the service before restoring a verified backup. Migration errors abort startup; retain the pre-migration backup. For scheduler failed-event retries, exponential backoff, pause/resume, upgrade, and rollback, follow [`OPERATIONS.md`](OPERATIONS.md).
