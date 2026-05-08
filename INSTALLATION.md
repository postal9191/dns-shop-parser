# INSTALLATION

## Windows / Linux / macOS

1. Установите зависимости:

```bash
npm install
npx playwright install chromium
pip install -r requirements.txt
```

2. Создайте конфиг:

```bash
cp .env.example .env
```

3. Заполните минимум:

```env
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ADMIN=...
```

4. Запустите сервис:

```bash
python run.py
```

## Проверка

```bash
python parser.py --city-slug krasnodar
```

## Примечания

- `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` больше не используются в `.env`.
- Набор поддерживаемых городов задается в `data/cities.py`.
- Если используете proxy, заполните `PROXY_*` переменные.
