# Установка в Linux

## Установка и предварительная проверка

Из корня проекта:

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

`preflight` возвращает код `0`, только если локальные компоненты готовы. При ошибке описание выводится в stderr. Эта проверка не обращается к DNS Shop и не запускает Telegram. **Не обновляйте Playwright `1.59.0` без живого испытания Qrator и загрузки товаров на сервере.** Playwright `1.63.0` с Chromium build `1243` получал `403` на `/__qrator/validate`, в том числе с `xvfb-run`; версия `1.59.0` с build `1217` работала. Подробнее — в [разделе о совместимости с Qrator](OPERATIONS.md#совместимость-с-qrator).

## Ручной запуск

```bash
uv run python -m dns_shop_parser run
uv run python -m dns_shop_parser parse --city-slug krasnodar
```

После установки доступны `dns-parser` и `dns-parser-once`; для запуска только Telegram-бота используйте `dns-parser-bot`.

## Управление службой systemd

```bash
chmod +x scripts/dns-parser.sh
./scripts/dns-parser.sh enable-systemd
sudo systemctl status dns-parser
journalctl -u dns-parser -f
```

Скрипт определяет корень проекта и запускает пакет из `src`. Если второй экземпляр уже запущен, он возвращает код `75`; при обычной ошибке парсинга — `1`.

## Состояние, резервные копии и восстановление

По умолчанию база данных находится в `dns_monitor.db`, журналы — в `logs/`, резервные копии миграций — в `backups/` рядом с базой. SQLite использует WAL, тайм-аут ожидания блокировки 5000 мс и внешние ключи. Резервные копии создаются через механизм SQLite и проверяются командой `PRAGMA integrity_check`. Перед восстановлением проверенной копии остановите службу. Ошибка миграции прерывает запуск: сохраните копию, созданную до миграции. Повторы задач, задержки планировщика, пауза и возобновление, обновление и откат описаны в [`OPERATIONS.md`](OPERATIONS.md).
