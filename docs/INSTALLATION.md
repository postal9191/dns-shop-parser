# Installation

## 1. Install Dependencies

```bash
npm install
npx playwright install chromium
pip install -r requirements.txt
```

For test dependencies:

```bash
pip install -r tests/requirements-test.txt
```

## 2. Create Config

```bash
cp .env.example .env
```

Minimum required values:

```env
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ADMIN=...
```

> Shell environment variables take priority over `.env` file values.

Validation: `PARSE_INTERVAL` and `PARSE_CONCURRENCY` must be > 0. Invalid values will raise `ValueError` at startup.

## 3. Run The App

Git Bash / Linux / macOS:

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

After editable install:

```bash
pip install -e .
dns-parser
```

## Single Parse

```bash
PYTHONPATH=src python -m dns_shop_parser parse --city-slug krasnodar
```

After editable install:

```bash
dns-parser-once --city-slug krasnodar
```

Exit codes:
- `0` — success
- `1` — parse failure (default; use `--lenient-exit-code` for `0` on failure)
- `75` — another instance already running

## Telegram Bot Only

```bash
PYTHONPATH=src python -m dns_shop_parser bot
```

After editable install:

```bash
dns-parser-bot
```

## Qrator Solver Check

```bash
node scripts/solve_qrator.js
```

## Tests

```bash
pytest -q
pytest --cov=dns_shop_parser  # with coverage (~70% branch)
```

## Notes

- Source code lives only in `src/dns_shop_parser`.
- Root compatibility files (`run.py`, `parser.py`, `bot_only.py`, `config.py`) were removed.
- `scripts/solve_qrator.js` is the Node/Playwright Qrator helper.
- Supported cities are defined in `src/dns_shop_parser/data/cities.py`.
- Cities can be enabled/disabled via the Telegram admin panel without code changes.
- If you use proxy, fill `PROXY_*` variables in `.env`.
- SQLite uses WAL mode, `busy_timeout=5000`, and `foreign_keys=ON` automatically.
- Backups run `PRAGMA integrity_check` before publishing.
- Cookies, CSRF tokens, and auth headers are redacted from logs.
