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

## Important

- City config in `.env` is not needed: cities and city cookies live in `src/dns_shop_parser/data/cities.py`.
- Krasnodar runs during the day; Moscow and Saint Petersburg use the night window from `dns_shop_parser.entrypoints.run`.
- For one-off parses, use `PYTHONPATH=src python -m dns_shop_parser parse --city-slug <slug>`.
