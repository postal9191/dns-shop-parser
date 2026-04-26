---

## Список изменений README

**Исправлено:**
- Версия обновлена с v1.5 до актуальной v1.6
- Требование Python 3.8+ → скорректировано до 3.10+ (код использует `str | None`, `ZoneInfo`, `dict[str, str]` без `__future__`)
- Структура БД: добавлены таблицы `user_settings` и `user_categories`, которые отсутствовали
- Зависимость Node.js: в коде используется `playwright-extra`, а не стандартный `playwright`
- Убран `TELEGRAM_CHAT_ID` из обязательных — notifier рассылает всем подписчикам; значение в коде не активно

**Добавлено:**
- `TELEGRAM_CHAT_ADMIN` — переменная окружения для ID администратора (не была задокументирована)
- `PARSE_CONCURRENCY` — переменная окружения параллелизма (не была задокументирована)
- Полное описание Telegram бота: все команды, inline-меню, 4-шаговый мастер отчётов
- Описание Circuit Breaker: 5 ошибок подряд → экспоненциальный backoff до 60 мин
- Описание механизма автоматического бэкапа БД
- Таблица поддерживаемых городов (15 городов)
- Описание персональных настроек пользователя (фильтр категорий, город, порог скидки)
- Поведение Chromium-профиля: Windows = постоянный, Linux = временный
- Ротация логов: 10 MB × 5 файлов
- Раздел "Поток данных" с реальными вызовами и таймаутами

**Удалено:**
- Секция "История версий" (деградирует быстро, принадлежит CHANGELOG)
- Неактуальные упоминания `LINUX_SETUP.md` (файл отсутствует в репозитории)

---

# DNS Shop Parser

Автоматический монитор уценённых товаров на [dns-shop.ru](https://www.dns-shop.ru/catalog/markdown/).

Парсер работает без постоянного браузера: Node.js + Playwright запускается один раз для обхода Qrator WAF и получения сессионных куков, все дальнейшие запросы делаются через `aiohttp`. Telegram бот рассылает персональные дайджесты всем подписчикам.

**Версия:** 1.6 | **Платформы:** Windows, Linux, macOS

---

## Возможности

- **Обход Qrator WAF** — `solve_qrator.js` запускает headless Chromium через Playwright, получает `qrator_jsid2` и сопутствующие куки
- **Безбраузерный парсинг** — после получения куков все запросы к DNS API выполняются через `aiohttp` без браузера
- **Параллельная обработка категорий** — настраиваемый семафор (`PARSE_CONCURRENCY`), по умолчанию 5 параллельных категорий
- **Ночной режим** — парсер не запускается в 22:00–6:00 МСК
- **Cron-синхронизация** — запуски выравниваются по часам (при интервале 3600 → 16:00, 17:00; при 1800 → :00, :30)
- **Circuit Breaker** — после 5 ошибок подряд парсер уходит в экспоненциальный backoff (до 60 минут), отправляет алерт администратору
- **Персональные уведомления** — каждый подписчик получает дайджест с учётом своих настроек (тип товара, порог скидки, фильтр категорий)
- **Мастер отчётов** — 4-шаговый inline-мастер в Telegram для формирования отчёта по товарам с скидкой
- **Полнотекстовый поиск категорий** в inline-меню
- **Telegram админ-панель** — запуск/остановка/перезапуск парсера, просмотр логов, изменение интервала в реальном времени
- **SQLite** с историей цен и автоматическим бэкапом при миграциях
- **Ротация логов** — файл `logs/app.log`, 10 MB × 5 файлов

---

## Архитектура

```
run.py  (asyncio event loop)
  ├── main_cycle()          ← основной цикл парсинга
  │     └── parser.py       ← запускается как subprocess каждую итерацию
  │           ├── qrator_resolver.py  → solve_qrator.js (Node.js + Playwright)
  │           ├── session_manager.py  → aiohttp сессия с куками
  │           ├── simple_dns_parser.py → HTTP запросы к DNS API
  │           ├── db_manager.py       → SQLite (upsert, история цен)
  │           └── telegram_notifier.py → персональный дайджест
  └── telegram_bot_polling() ← TelegramBot polling (параллельная задача)
```

**Поток данных при каждой итерации:**

1. `run.py` запускает `parser.py` как отдельный процесс (таймаут 10 минут)
2. `parser.py` вызывает `session_manager._init_session()` → запускает `solve_qrator.js`
3. `solve_qrator.js` открывает headless Chromium, переходит на `dns-shop.ru/catalog/markdown/`, собирает все куки и выводит их в stdout в формате `__QRATOR_COOKIES__...__END_COOKIES__`
4. Python разбирает куки, накладывает региональный override (`CITY_COOKIE_PATH`, `CITY_COOKIE_CURRENT`)
5. `SimpleDNSParser` запрашивает категории (GET `/catalogMarkdown/markdown/products-filters/`), затем UUID товаров по страницам (HTML-парсинг regex), затем детали одним POST `/ajax-state/product-buy/`
6. `DBManager.upsert_products()` → сохраняет/обновляет, возвращает список изменений цен
7. `TelegramNotifier.send_digest()` → персональная рассылка каждому подписчику с учётом его настроек

**Профиль Chromium:**
- **Windows/macOS**: постоянный профиль `~/.dns-parser-chromium` — Qrator видит "знакомого" пользователя
- **Linux**: временный профиль `$TMPDIR/.dns-parser-chromium-{timestamp}` — каждый раз новый визитор

---

## Установка

### Требования

| Компонент | Версия |
|-----------|--------|
| Python    | 3.10+  |
| Node.js   | 14+    |
| npm       | 7+     |

### Шаг 1. Клонирование

```bash
git clone <repo-url>
cd dns-shop-parser
```

### Шаг 2. Python-зависимости

```bash
pip install -r requirements.txt
```

Устанавливаются: `aiohttp==3.9.1`, `tenacity==8.2.3`, `python-dotenv==1.0.0`

### Шаг 3. Node.js-зависимости и браузер

```bash
npm install
npx playwright install chromium
```

> На Ubuntu/Debian может потребоваться установить системные зависимости Chromium:
> ```bash
> npx playwright install-deps chromium
> ```

### Шаг 4. Конфигурация

```bash
cp .env.example .env
# Откройте .env и заполните нужные поля
```

---

## Конфигурация

Все настройки задаются в файле `.env`. Файл загружается при каждом старте через `python-dotenv`.

### Переменные окружения

| Переменная            | По умолчанию              | Обязательность | Описание |
|-----------------------|---------------------------|----------------|----------|
| `TELEGRAM_TOKEN`      | —                         | Нет            | Токен Telegram бота (от @BotFather). Без него уведомления отключены |
| `TELEGRAM_CHAT_ADMIN` | —                         | Нет            | Telegram ID администратора. Открывает доступ к `/admin` и получает критические алерты |
| `TELEGRAM_CHAT_ID`    | —                         | Нет            | Оставлен для совместимости; рассылка идёт всем подписчикам через БД |
| `API_BASE_URL`        | `https://www.dns-shop.ru` | Нет            | Базовый URL DNS Shop API |
| `CITY_COOKIE_PATH`    | —                         | Да             | Slug города в URL (см. таблицу ниже) |
| `CITY_COOKIE_CURRENT` | —                         | Да             | SHA256-хеш данных города (региональная кука DNS Shop) |
| `DB_PATH`             | `dns_monitor.db`          | Нет            | Путь к SQLite БД |
| `PARSE_INTERVAL`      | `3600`                    | Нет            | Интервал между циклами парсинга, секунды |
| `PARSE_CONCURRENCY`   | `5`                       | Нет            | Число параллельно обрабатываемых категорий |
| `MAX_RETRIES`         | `4`                       | Нет            | Число попыток при HTTP-ошибке (tenacity) |
| `RETRY_DELAY`         | `5.0`                     | Нет            | Начальная задержка между попытками, секунды |
| `LOG_LEVEL`           | `INFO`                    | Нет            | Уровень логирования: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `USE_PLATFORM_UA`     | `false`                   | Нет            | `true` — Python-сессия использует User-Agent текущей ОС |

### Минимальный `.env`

```env
TELEGRAM_TOKEN=1234567890:AAxxxxxx
TELEGRAM_CHAT_ADMIN=123456789

CITY_COOKIE_PATH=moscow
CITY_COOKIE_CURRENT=c5f58b981d1ed0bad05ae63f54072ea9dcdf57ac...

PARSE_INTERVAL=3600
LOG_LEVEL=INFO
```

### Поддерживаемые города

| Город             | `CITY_COOKIE_PATH`  |
|-------------------|---------------------|
| Москва            | `moscow`            |
| Санкт-Петербург   | `spb`               |
| Новосибирск       | `novosibirsk`       |
| Екатеринбург      | `ekaterinburg`      |
| Нижний Новгород   | `nizhny-novgorod`   |
| Казань            | `kazan`             |
| Краснодар         | `krasnodar`         |
| Самара            | `samara`            |
| Уфа               | `ufa`               |
| Ростов-на-Дону    | `rostov-na-donu`    |
| Красноярск        | `krasnoyarsk`       |
| Воронеж           | `voronezh`          |
| Пермь             | `perm`              |
| Волгоград         | `volgograd`         |
| Омск              | `omsk`              |

`CITY_COOKIE_CURRENT` — SHA256-хеш, специфичный для каждого города. Получается из DNS Shop API.

---

## Запуск

### Основной режим (рекомендуется)

```bash
python run.py
```

Запускает два параллельных asyncio-таска:
1. **main_cycle** — цикл парсинга с ночным режимом и cron-синхронизацией
2. **telegram_bot_polling** — бесконечный polling Telegram Bot API

Остановка: `Ctrl+C`

### Однократный парсинг (для тестирования)

```bash
python parser.py
```

Инициализирует сессию, парсит все категории, отправляет уведомления, завершается. Polling бота не запускается.

### Управление через Telegram

После запуска `run.py` и подключения бота: отправьте `/admin` администратору (задаётся через `TELEGRAM_CHAT_ADMIN`).

---

## Примеры работы

### Дайджест новых товаров (Telegram)

```
📊 Дайджест DNS — 14:35

🆕 Новые товары (3)

• Принтер Canon PIXMA TS5340
  💰 4 999 ₽ ~~6 999 ₽~~ 🆕

• Видеокарта NVIDIA GeForce RTX ...
  💰 28 500 ₽ ~~35 000 ₽~~ ♻️
```

### Уведомление о снижении цен

```
🏷 Снижение цен (2)

• Смартфон Samsung Galaxy A35
  🔽 19 990 ₽ ~~24 990 ₽~~ (−20%) 🆕

• Телевизор LG 43UP77006LA
  🔽 27 000 ₽ ~~32 000 ₽~~ (−16%) ♻️
```

### Мастер отчётов (4 шага)

```
Шаг 1: выбрать состояние товара  → [✅ Новые] [✅ Б/У]
Шаг 2: минимальная скидка        → [10%] [20%] [30%] ...
Шаг 3: категории                 → с поиском и пагинацией
Шаг 4: период                    → [1 день] [3 дня] [Неделя] [Месяц] [Весь срок]
```

### Логи при запуске

```
14:00:05 | INFO     | [RUN] Запущен автоматический парсер DNS Shop
14:00:05 | INFO     | [RUN] Интервал обновления: 3600 сек
14:00:06 | INFO     | [QRATOR] Node.js доступен: v20.11.0
14:00:08 | INFO     | [QRATOR] ✅ Qrator решён, импортировано кук: 8
14:00:09 | INFO     | [PARSER] Получено 12 категорий
14:00:11 | INFO     | [PARSE] Категория 1/12: 3D принтеры (было: 5, сейчас: 7, состав изменился)
14:00:12 | INFO     | [PARSE]   OK Загружено и сохранено 7 товаров
14:00:12 | INFO     | [PARSE]   NEW Новых товаров: 2
```

---

## Telegram бот — команды и меню

### Команды

| Команда       | Доступ              | Описание |
|---------------|---------------------|----------|
| `/start`      | Все                 | Подписка на уведомления |
| `/stop`       | Подписчики          | Отписка |
| `/settings`   | Подписчики          | Настройки уведомлений (тип, порог скидки) |
| `/city`       | Подписчики          | Выбор города (сохраняется, для будущих функций) |
| `/categories` | Подписчики          | Фильтр категорий с поиском и пагинацией |
| `/status`     | Подписчики          | Просмотр текущих настроек |
| `/admin`      | Администратор       | Управление парсером |

### Inline-меню главная

```
[⚙️ Настройки]  [📊 Отчет]
[🎛️ Админ-панель]   ← только для TELEGRAM_CHAT_ADMIN
```

### Настройки уведомлений

- Вкл/откл новые товары
- Вкл/откл снижение цен
- Порог скидки: любое / >5% / >10% / >20%
- Мастер уведомлений вкл/откл

### Админ-панель (только для `TELEGRAM_CHAT_ADMIN`)

```
[▶️ Запустить]    [⏹ Остановить]
[🔄 Перезапустить] [⏱ Интервал]
[📄 Логи]
[📊 Статус]
```

- **Логи** — последние 100 строк `logs/app.log` с разбивкой на чанки по 4096 символов
- **Интервал** — принимает число секунд (60–86400), применяется после текущей итерации

---

## База данных

SQLite-файл `dns_monitor.db` (путь настраивается через `DB_PATH`).

### Схема

```sql
products              -- товары
  id TEXT PRIMARY KEY      -- короткий ID (as-AbCdEf)
  uuid TEXT                -- UUID товара (9514e56e-...)
  title TEXT
  url TEXT
  category_id TEXT
  category_name TEXT
  current_price INTEGER
  previous_price INTEGER
  status TEXT              -- "Новый" или "Б/У"
  updated_at TEXT
  created_at TEXT

price_history         -- история цен при изменении
  product_id TEXT → products.uuid
  price INTEGER
  timestamp TEXT

category_state        -- состояние категории
  category_id TEXT PRIMARY KEY
  category_name TEXT
  last_product_count INTEGER
  uuid_hash TEXT           -- SHA256 набора UUID (для детектирования изменений состава)
  last_checked_at TEXT

telegram_subscribers  -- подписчики бота
  user_id TEXT PRIMARY KEY
  first_name, last_name, username, language_code TEXT
  is_active INTEGER        -- 0 = soft delete, 1 = активен
  subscribed_at TEXT
  updated_at TEXT

user_settings         -- персональные настройки подписчика
  user_id TEXT PRIMARY KEY
  city_slug TEXT           -- выбранный город
  notify_new INTEGER       -- уведомления о новых товарах
  notify_price_drop INTEGER
  min_price_drop_pct INTEGER  -- минимальный % снижения для уведомления
  notifications_on INTEGER

user_categories       -- фильтр категорий для подписчика (пусто = все)
  user_id TEXT
  category_id TEXT
  category_name TEXT
```

### Бэкап

При каждой структурной миграции (добавление столбца) автоматически создаётся копия в `backups/dns_monitor_backup_YYYYMMDD_HHMMSS.db`.

### Переключение города

```bash
# 1. Обновите .env
CITY_COOKIE_PATH=spb
CITY_COOKIE_CURRENT=<новый_хеш>

# 2. Удалите старую БД
rm dns_monitor.db

# 3. Тестовый прогон
python parser.py

# 4. Основной режим
python run.py
```

---

## Логирование и обработка ошибок

### Файлы логов

```
logs/app.log        ← основной файл, всегда DEBUG
  - ротация: 10 MB × 5 файлов
  - формат: YYYY-MM-DD HH:MM:SS | LEVEL | module | func:line | message

консоль             ← уровень контролируется LOG_LEVEL
  - формат: HH:MM:SS | LEVEL | message
```

### Уровни логирования

| `LOG_LEVEL` | Консоль | Описание |
|-------------|---------|----------|
| `DEBUG`     | Всё     | HTTP-запросы/ответы, UUID-пагинация, куки |
| `INFO`      | Основное | Запуск итераций, новые товары, отправка уведомлений |
| `WARNING`   | Проблемы | Неполный fetch, rate limit, протухшие куки |
| `ERROR`     | Ошибки  | Недоступность API, сбой парсинга категории |

### Circuit Breaker

При 5 ошибках парсинга подряд:
1. Отправляется алерт администратору в Telegram
2. Парсер уходит в паузу с экспоненциальным backoff: `min(60 × 2^(N-5), 3600)` секунд

---

## Структура проекта

```
dns-shop-parser/
├── run.py                    # Точка входа: asyncio-цикл + TG бот
├── parser.py                 # Однократный парсинг (запускается из run.py subprocess)
├── config.py                 # Dataclass Config, загрузка из .env
├── solve_qrator.js           # Node.js: Playwright + обход Qrator WAF
├── package.json              # Node.js зависимости (playwright-extra)
├── requirements.txt          # Python зависимости
├── .env                      # Локальная конфигурация (не в git)
├── .env.example              # Шаблон
├── QUICKSTART_LINUX.sh       # Скрипт быстрой установки для Linux
│
├── parser/
│   ├── models.py             # Dataclass Category, Product
│   ├── exceptions.py         # CookiesExpiredError
│   ├── session_manager.py    # aiohttp сессия, сборка headers, cookie override
│   ├── qrator_resolver.py    # Запуск solve_qrator.js, парсинг куков
│   ├── simple_dns_parser.py  # HTTP-парсер: категории → UUID → детали товаров
│   └── db_manager.py         # SQLite: CRUD, миграции, бэкап
│
├── services/
│   ├── telegram_notifier.py  # Форматирование и рассылка дайджестов
│   ├── telegram_bot.py       # TelegramBot: polling, inline-меню, мастер отчётов
│   └── admin_panel.py        # ParserController: start/stop/restart/interval
│
├── utils/
│   └── logger.py             # RotatingFileHandler + StreamHandler
│
├── data/
│   └── cities.py             # Словарь поддерживаемых городов (15 штук)
│
├── logs/
│   └── app.log               # Создаётся автоматически
│
└── backups/                  # Автоматические бэкапы БД при миграциях
```

---

## Зависимости

### Python (`requirements.txt`)

| Библиотека       | Версия   | Назначение |
|------------------|----------|------------|
| `aiohttp`        | 3.9.1    | Асинхронные HTTP-запросы к DNS API и Telegram Bot API |
| `tenacity`       | 8.2.3    | Retry с exponential backoff для HTTP-запросов |
| `python-dotenv`  | 1.0.0    | Загрузка переменных окружения из `.env` |

Стандартная библиотека: `asyncio`, `sqlite3`, `hashlib`, `json`, `re`, `subprocess`, `zoneinfo` (Python 3.9+)

### Node.js (`package.json`)

| Пакет              | Версия   | Назначение |
|--------------------|----------|------------|
| `playwright-extra` | —        | Фреймворк над Playwright для обхода Qrator WAF |
| `playwright`       | ^1.40.0  | Управление headless Chromium |

---

## Безопасность

### Хранение секретов

- **Никогда не коммитьте `.env`** — добавьте его в `.gitignore`
- Токен бота `TELEGRAM_TOKEN` и ID администратора `TELEGRAM_CHAT_ADMIN` хранятся только в `.env`
- Куки города (`CITY_COOKIE_CURRENT`) — чувствительные данные, не публикуйте их

### Доступ к Telegram Admin

- Команды управления парсером доступны только `user_id == TELEGRAM_CHAT_ADMIN`
- При попытке доступа от другого пользователя выводится `❌ Нет доступа` и пишется WARNING в лог

### Rate limiting

- Рассылка Telegram: пауза 1.1 сек между сообщениями (соблюдение лимита ~1 msg/sec на чат)
- Пагинация UUID: пауза 0.3 сек между страницами
- Между категориями: пауза 0.5 сек

### SQL-инъекции

Все SQL-запросы используют параметризованные плейсхолдеры `?`. Динамически формируются только плейсхолдеры вида `?,?,?` через `",".join("?" * len(ids))`.

---

## Ограничения и известные проблемы

- **Один город в конфигурации** — парсер работает с одним регионом (задан в `.env`). Настройка города в боте сохраняется для будущих возможностей многогородского режима
- **Qrator кука живёт несколько часов** — при ошибке 401/403 нужно подождать следующей итерации (куки переполучаются автоматически)
- **Linux + блокировка по IP** — если IP заблокирован Qrator, парсинг не будет работать независимо от настроек
- **Не поддерживается webhook-режим** — бот работает только в polling-режиме
- **Максимум 50 страниц пагинации** — захардкожено в `simple_dns_parser.py` (`_MAX_PAGES = 50`)
- **Аутентификация DNS Shop** — отсутствует. Парсер работает только с публичным разделом уценённых товаров

---

## TODO (выявлено из кода)

- Многогородской режим (структура в `data/cities.py` и `user_settings.city_slug` уже готова)
- Поддержка `TELEGRAM_CHAT_ID` как fallback-канала для уведомлений
- Вебхук-режим для Telegram бота
- Webhook health-check endpoint
- Экспорт отчётов в CSV/Excel

---

## Troubleshooting

### `Error: browserType.launch: Executable doesn't exist`
```bash
npx playwright install chromium
```

### `[QRATOR] Node.js не найден`
Убедитесь что Node.js установлен и доступен в PATH:
```bash
node --version
```

### Товары из неправильного города
Проверьте `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` в `.env`. При смене города удалите `dns_monitor.db`.

### Telegram не отправляет
1. Проверьте `TELEGRAM_TOKEN`
2. Убедитесь что пользователь отправил `/start` боту
3. Включите `LOG_LEVEL=DEBUG` для диагностики

### Ошибка 401/403 от dns-shop.ru
Куки `qrator_jsid2` устарели. Подождите следующей итерации — парсер получит новые куки автоматически. Если повторяется — возможна блокировка по IP.

### `409 Conflict` в polling
Запущен второй экземпляр бота с тем же токеном. Остановите дубликат.

---

## Лицензия

MIT

---

*Что ещё стоит добавить вручную:*
- `CITY_COOKIE_CURRENT` для каждого города — значения специфичны для вашего аккаунта/региона и не могут быть указаны в документации
- Инструкция по получению `CITY_COOKIE_CURRENT` (требует ручного анализа сетевых запросов в браузере)
- Описание `QUICKSTART_LINUX.sh` — если скрипт актуален, добавьте его содержимое или инструкцию
- Раздел Docker (если планируется контейнеризация)
- Примеры значений `CITY_COOKIE_CURRENT` или способ их автоматического получения
