# Linux Setup

## Quick Start

Run from the project root:

```bash
chmod +x scripts/dns-parser.sh
./scripts/dns-parser.sh
```

Or use the quick-start helper:

```bash
bash scripts/QUICKSTART_LINUX.sh
```

`scripts/dns-parser.sh` resolves the project root automatically, even though the script itself lives in `scripts/`.

## Manual Run

```bash
npm install
npx playwright install chromium --with-deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src python -m dns_shop_parser run
```

## Single Parse

```bash
PYTHONPATH=src python -m dns_shop_parser parse --city-slug krasnodar
```

Exit codes: `0` = success, `1` = failure, `75` = another instance already running.

## systemd

```bash
./scripts/dns-parser.sh enable-systemd
sudo systemctl status dns-parser
journalctl -u dns-parser -f
```

The generated systemd unit runs:

```bash
PYTHONPATH="$PROJECT_DIR/src" python -m dns_shop_parser run
```

## Single-Instance Lock

The parser uses a cross-platform file lock (`fcntl` on Linux, `msvcrt` on Windows) to prevent running two instances of the same project. If another instance is already running, the process exits with code `75`.

The lock is acquired in `main()`, so it works for all entrypoints: `python -m dns_shop_parser run`, `dns-parser`, and direct script execution.

## SQLite

The database uses:
- **WAL mode** for concurrent reads during writes
- **busy_timeout=5000ms** to retry on lock contention
- **foreign_keys=ON** for referential integrity
- **Online backup** via `sqlite3.Connection.backup()` with `PRAGMA integrity_check`

## Important

- City config in `.env` is not needed: cities and city cookies live in `src/dns_shop_parser/data/cities.py`.
- Cities can be enabled/disabled via the Telegram admin panel.
- Krasnodar runs during the day; Moscow and Saint Petersburg use the night window from `dns_shop_parser.entrypoints.run`.
- For one-off parses, use `PYTHONPATH=src python -m dns_shop_parser parse --city-slug <slug>`.
- Cookies, CSRF tokens, and auth headers are automatically redacted from log files.
- Scheduler uses atomic claim/lease to prevent duplicate event processing.
