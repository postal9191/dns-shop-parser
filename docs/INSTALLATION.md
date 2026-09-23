# Установка

## Требования

Нужны Python версии 3.10 или новее, Node.js с npm и Chromium, устанавливаемый через Playwright. Из каталога исходников выполните:

```bash
uv sync --extra test
npm ci
npx playwright install chromium
```

В Linux при отсутствии системных библиотек браузера используйте `npx playwright install chromium --with-deps`. Скопируйте `.env.example` в `.env`; переменные окружения имеют приоритет над значениями файла. **Playwright закреплён на версии `1.59.0`: не обновляйте его без живой проверки Qrator и загрузки товаров на сервере.** См. [раздел о совместимости](OPERATIONS.md#совместимость-с-qrator).

## Предварительная проверка и тесты

Перед запуском выполните безопасную локальную проверку зависимостей. Она не запускает опрос Telegram и не обращается к живой проверке Qrator.

```bash
uv run preflight --db dns_monitor.db --state-dir . --log-dir logs --backup-dir backups
uv run pytest -q
uv run python -m compileall -q src
```

Код возврата `0` означает успех; при ошибке выводится название отсутствующего или некорректного компонента. Для тестов не нужны рабочие учётные данные; рабочие файлы исключены из Git.

## Запуск

```bash
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
uv run python -m dns_shop_parser bot
```

После установки в режиме редактирования (`uv pip install -e .`) доступны команды `dns-parser`, `dns-parser-once --city-slug krasnodar` и `dns-parser-bot`. Собранный через `uv build` wheel-пакет содержит файл Qrator. Устанавливайте его вне каталога исходников командой `uv pip install dist/dns_shop_parser-*.whl`.

## Настройки

Для Telegram нужны `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ADMIN`. Дополнительные параметры: `TELEGRAM_CHAT_ID`, `DB_PATH`, `PARSE_INTERVAL`, `PARSE_CONCURRENCY`, `MAX_RETRIES`, `RETRY_DELAY`, `LOG_LEVEL`, `QRATOR_*`, `PROXY_*`. Неположительные интервалы и значения параллелизма вызывают ошибку запуска без раскрытия секретов.

## Рабочие данные

По умолчанию SQLite использует `dns_monitor.db`, журналы — `logs/`, а резервные копии миграций — `backups/` рядом с базой. Перед публикацией резервная копия проходит проверку `PRAGMA integrity_check`. Ошибка миграции прерывает запуск: сохраните и проверьте копию базы, созданную до миграции. При попытке запустить второй экземпляр парсер возвращает код `75`.

Восстановление, повторы и задержки планировщика, мониторинг, обновление и откат описаны в [`OPERATIONS.md`](OPERATIONS.md).
