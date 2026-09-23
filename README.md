# Парсер уценённых товаров DNS

Автоматический мониторинг уценённых товаров DNS с уведомлениями в Telegram.

## Быстрый запуск из исходников

```bash
uv sync --extra test
npm ci
npx playwright install chromium
cp .env.example .env
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
uv run python -m dns_shop_parser run
```

Нужны Python версии 3.10 или новее, Node.js, npm, Playwright и Chromium. В Linux, если не хватает системных библиотек браузера, выполните `npx playwright install chromium --with-deps`. Команда `preflight` проверяет Python, настройки, каталоги, SQLite, Node.js, Playwright, Chromium и файл Qrator внутри пакета. Она возвращает код `0` при успехе, а при ошибке сообщает, какая проверка не прошла. Telegram и DNS при этом не вызываются.

**Не обновляйте Playwright без проверки Qrator на сервере.** Зафиксированная версия `1.59.0` с Chromium build `1217` позволила получить товары; после обновления до `1.63.0` / build `1243` Qrator стал отвечать `403`. Подробности и порядок проверки перед обновлением — в [руководстве по эксплуатации](docs/OPERATIONS.md#совместимость-с-qrator).

Полная инструкция по установке, состоянию, резервным копиям, планировщику, восстановлению и откату — в [`docs/OPERATIONS.md`](docs/OPERATIONS.md). Настройка службы Linux — в [`docs/LINUX_SETUP.md`](docs/LINUX_SETUP.md).

## Установка из wheel-пакета

Соберите пакет командой `uv build`. Затем вне каталога исходников установите его и проверьте доступные команды:

```bash
uv pip install dist/dns_shop_parser-*.whl
preflight --help
dns-parser --help
dns-parser-once --help
dns-parser-bot --help
```

## Команды

```bash
uv run python -m dns_shop_parser --help
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
uv run python -m dns_shop_parser bot
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
```

После установки доступны также `dns-parser`, `dns-parser-once`, `dns-parser-bot` и `preflight`. Если другой экземпляр удерживает блокировку, парсер возвращает код `75`; при обычной ошибке парсинга — `1`.

## Настройки и рабочие файлы

Скопируйте `.env.example` в `.env`; переменные окружения имеют приоритет над значениями файла. Для Telegram нужны `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ADMIN`. Часто используемые настройки: `DB_PATH`, `PARSE_INTERVAL`, `PARSE_CONCURRENCY`, `LOG_LEVEL`, `QRATOR_*`, `PROXY_*`. По умолчанию база находится в `dns_monitor.db`, журналы — в `logs/`, а резервные копии после миграций — в `backups/` рядом с базой. Секреты, значения cookies, CSRF-токены и заголовки авторизации скрываются в журналах. SQLite работает с WAL, `busy_timeout=5000` и внешними ключами.

## Тесты и проверки, аналогичные CI

```bash
uv sync --extra test --locked
uv run pytest -q
uv run python -m compileall -q src
uv build
npm ci
```

## Структура проекта

- `src/dns_shop_parser/` — код приложения и файл `resources/solve_qrator.js` внутри пакета;
- `scripts/` — скрипты Node.js и Linux;
- `docs/` — инструкции по установке и эксплуатации;
- `tests/` — автоматические тесты.
