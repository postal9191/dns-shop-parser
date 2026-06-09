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
```

## Notes

- Source code lives only in `src/dns_shop_parser`.
- Root compatibility files (`run.py`, `parser.py`, `bot_only.py`, `config.py`) were removed.
- `scripts/solve_qrator.js` is the Node/Playwright Qrator helper.
- Supported cities are defined in `src/dns_shop_parser/data/cities.py`.
- If you use proxy, fill `PROXY_*` variables in `.env`.
