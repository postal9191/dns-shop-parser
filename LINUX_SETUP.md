# LINUX_SETUP

## Быстрый запуск

```bash
chmod +x dns-parser.sh
./dns-parser.sh
```

Скрипт ставит зависимости и запускает `run.py`.

## Ручной запуск

```bash
npm install
npx playwright install chromium --with-deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 run.py
```

## systemd (опционально)

```bash
./dns-parser.sh enable-systemd
sudo systemctl status dns-parser
journalctl -u dns-parser -f
```

## Важно

- Конфиг города в `.env` не нужен: города и cookie в `data/cities.py`.
- Ночной режим в `run.py`: окно 22:00–05:30 МСК для ночных городских запусков.
- Для разовых запусков используйте `python3 parser.py --city-slug <slug>`.
