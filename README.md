# DNS Shop Parser — Парсинг уценённых товаров

**Версия 1.2** — ✅ Стабильная версия, работает на Windows и Linux  
Автоматический парсер товаров с сайта DNS-shop.ru (уценённые товары)  
**Кроссплатформенный парсер без полного браузера! Работает на Windows/Linux/Docker 🪟 🐧 🐳**

## 🚀 Возможности

- ✅ **Решение Qrator WAF** через Node.js + Playwright (solve_qrator.js)
- ✅ **Получение куков** для работы с DNS Shop API
- ✅ **Парсинг товаров** через официальный API без блокировок
- ✅ **Telegram уведомления** о новых/удаленных товарах в реальном времени
- ✅ **Сохранение в БД** (SQLite) с историей цен
- ✅ **Админ-панель** для управления парсером и просмотра статистики
- ✅ **Telegram бот** для подписки на уведомления
- ✅ **Контроль интервала** обновления (настраивается в .env)
- ✅ **Логирование** всех операций и ошибок
- ✅ **Кроссплатформенность** — Linux, Windows, macOS, Docker

## 📋 Требования

- Python 3.8+
- Node.js 14+ и npm
- pip для установки Python зависимостей

## 🐧 Linux / Ubuntu / Docker

**Используй специальный скрипт для автоматизации всей установки и управления сервисом:**

```bash
chmod +x dns-parser.sh
./dns-parser.sh
```

Полная документация: **[LINUX_SETUP.md](LINUX_SETUP.md)**

Скрипт автоматически:
- ✅ Проверяет и устанавливает Node.js + npm
- ✅ Проверяет Python 3 и зависимости
- ✅ Устанавливает Playwright браузер (`npx playwright install`)
- ✅ Управляет запуском/остановкой
- ✅ Интегрирует с systemd (опционально)
- ✅ Показывает логи в реальном времени
- ✅ Работает в Docker контейнерах

## 🔧 Установка

### 1. Клонирование

```bash
git clone <repo>
cd dns-shop-parser
```

### 2. Установка Node.js и Playwright

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y nodejs npm

# Установка Playwright браузера
npm install
npx playwright install chromium
```

### 3. Установка Python зависимостей

```bash
pip install -r requirements.txt
```

### 4. Конфигурация

Скопируй `.env.example` в `.env` и отредактируй:

```bash
cp .env.example .env
```

**Ключевые переменные в `.env`:**

```env
# Telegram (опционально)
TELEGRAM_TOKEN=              # Токен Telegram бота
TELEGRAM_CHAT_ID=            # ID чата для уведомлений о товарах

# Город и его куки (определяют регион парсинга)
CITY_ID=884019c7-cf52-11de-b72b-00151716f9f5
CITY_NAME=Москва             # Название города (для справки)
CITY_COOKIE_PATH=moscow      # Название города в URL
CITY_COOKIE_CURRENT=c5f58b981d1...  # Хеш куки региона DNS Shop

# Интервал обновления (в секундах)
PARSE_INTERVAL=3600          # 1 час между циклами

# Переподключение при ошибках
MAX_RETRIES=4                # Кол-во попыток при ошибке
RETRY_DELAY=5.0              # Интервал между попытками (сек)
```

**⚠️ Важно:** Параметры `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` определяют, из какого города будут приходить товары. 
Измените их, чтобы парсить товары из другого региона.

## 🏃 Запуск

### Полностью автоматический режим (рекомендуется)

```bash
python run.py
```

Что происходит:
1. **Инициализация кук** (автоматически):
   - Запускает `solve_qrator.js` (Node.js) для решения Qrator WAF
   - Получает `qrator_jsid2` куку
   - Получает `PHPSESSID` через HTTP GET
   - Строит `city_path` и `current_path` программно
2. Парсит товары (parser.py)
3. Ждет PARSE_INTERVAL секунд
4. Повторяет бесконечно

### Однократный запуск парсера

```bash
python parser.py
# Инициализирует куки и парсит товары
# Сохраняет в БД + отправляет в ТГ
# Завершается (не цикл)
```

## 📊 Структура проекта

```
├── run.py                  # Главный скрипт (цикл + админ-панель + бот)
├── parser.py               # Парсинг товаров (одноразовый запуск)
├── config.py               # Конфигурация из .env
├── solve_qrator.js         # Node.js скрипт (решение Qrator WAF)
├── package.json            # Зависимости Node.js
├── requirements.txt        # Зависимости Python
├── .env                    # Переменные окружения
├── .env.example            # Шаблон .env
├── dns_monitor.db          # SQLite база (создаётся автоматически)
├── dns-parser.sh           # Скрипт управления для Linux
│
├── parser/
│   ├── db_manager.py       # Работа с SQLite БД
│   ├── session_manager.py  # HTTP сессия + куки
│   ├── qrator_resolver.py  # Интеграция с solve_qrator.js
│   ├── simple_dns_parser.py# Парсер API DNS Shop
│   ├── models.py           # Модели данных товаров
│   └── exceptions.py       # Пользовательские исключения
│
├── services/
│   ├── telegram_notifier.py# Отправка уведомлений в Telegram
│   ├── telegram_bot.py     # Telegram бот (подписка пользователей)
│   └── admin_panel.py      # Админ-панель управления парсером
│
├── utils/
│   └── logger.py           # Логирование в консоль и файл
│
└── logs/
    └── app.log             # Логи приложения
```

## 🔄 Поток работы (новый — без браузера)

```
Итерация 1:
  ├─ solve_qrator.js (Node.js) → Решает Qrator challenge → получает qrator_jsid2
  ├─ parser.py инициализирует куки:
  │  ├─ HTTP GET с qrator_jsid2 → получает PHPSESSID
  │  ├─ _build_city_cookie() → использует предвычисленный current_path из .env
  │  │   (current_path = SHA256(php_serialized_city_data) для региона)
  │  └─ Защищает куки города от перезаписи сервером
  ├─ Парсит товары города (первый раз, ТГ молчит)
  └─ Ждет 3600 сек

Итерация 2:
  ├─ Используются сохраненные куки (Qrator токен живет долго)
  ├─ Парсит товары (новые → ТГ уведомления)
  └─ Ждет 3600 сек

Итерация N:
  └─ (повторяется, Qrator решается только если токен протух)
```

## 🔑 Куки города (Region Cookies)

**Важно:** DNS Shop использует региональные куки. Два параметра определяют, из какого города приходят товары:

| Параметр | Описание |
|----------|---------|
| `CITY_COOKIE_PATH` | Название города в URL (например, `moscow`, `spb`, `ekaterinburg`) |
| `CITY_COOKIE_CURRENT` | Хеш SHA256 данных о городе (устанавливает регион в API DNS Shop) |

Эти куки загружаются из `.env` при каждом запросе к API:
```env
CITY_COOKIE_PATH=moscow
CITY_COOKIE_CURRENT=c5f58b981d1ed0bad...  # Хеш региона
```

Куки защищены от перезаписи сервером — это позволяет парсить данные одного региона, не переключаясь на другой.

## 📱 Telegram уведомления

Формат уведомления:

```
Новые товары в 3D принтеры!

Добавлено: 2 шт

Название товара - 11899 руб. прайс 15999
https://www.dns-shop.ru/catalog/markdown/9514e56e-1c8c-11f1-9373-0050569d8ba5/

Название товара 2 - 8999 руб. прайс 12999
https://www.dns-shop.ru/catalog/markdown/uuid2/
```

## 💾 База данных

SQLite база `dns_monitor.db` содержит:

```sql
products           -- Товары (id, uuid, title, price, price_old, url, category, ...)
price_history      -- История цен
category_state     -- Состояние категорий (счётчики товаров)
telegram_subscribers-- Подписчики ТГ бота
```

## 🛠 Переключение между городами

Для парсинга товаров из другого города обновите региональные куки в `.env`:

1. Найдите `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` для нужного города
   - `CITY_COOKIE_PATH` — название города в URL (например, `moscow`, `spb`, `ekaterinburg`)
   - `CITY_COOKIE_CURRENT` — хеш SHA256, получается запросом к API DNS Shop
2. Обновите `.env`:
   ```env
   CITY_COOKIE_PATH=moscow
   CITY_COOKIE_CURRENT=<новый_хеш>
   
   # Опционально:
   CITY_ID=<ID города>
   CITY_NAME=Москва
   ```
3. Удалите `dns_monitor.db` чтобы начать с чистой БД нового города
4. Запустите `python parser.py` для проверки новых кук и товаров
5. Запустите `python run.py` для начала автоматического парсинга

## ⚙️ Опции запуска

**Изменить интервал** парсинга:
```env
PARSE_INTERVAL=1800  # 30 минут
```

**Telegram отключен:**
```env
TELEGRAM_TOKEN=     # Оставить пусто
```

**Debug режим** (подробные логи):
```env
LOG_LEVEL=DEBUG
```
Выведет в консоль все HTTP запросы/ответы, логи парсинга и т.д.

**Кроссплатформенность** (Linux, Windows, macOS):
```env
# По умолчанию используется Windows UserAgent везде (для совместимости)
# Если хотите использовать реальный UA вашей платформы:
USE_PLATFORM_UA=true
```

## 📝 Логирование

Логи выводятся в консоль и сохраняются в файл `logs/app.log`.

Уровни логирования (в `.env`):
```env
LOG_LEVEL=INFO    # INFO, DEBUG, WARNING, ERROR
```

- `DEBUG` — детальная информация (HTTP запросы, работа с БД)
- `INFO` — основные события (парсинг, уведомления)
- `WARNING` — предупреждения (ошибки куки, таймауты)
- `ERROR` — ошибки (критические сбои)

## 🐛 Troubleshooting

### solve_qrator.js не найден
- Убедись что установлены Node.js зависимости: `npm install`
- Убедись что файл `solve_qrator.js` существует в корне проекта
- Проверь права на исполнение: `chmod +x solve_qrator.js`

### Ошибка при запуске Node.js скрипта
```
Error: browserType.launch: Executable doesn't exist
```
- Установи Playwright браузер: `npx playwright install chromium`

### Товары из неправильного города
**Проверьте региональные куки:**
- `CITY_COOKIE_PATH` — название города в URL (например, `moscow`, `spb`)
- `CITY_COOKIE_CURRENT` — хеш SHA256 для установки региона в API

**Решение:**
1. Проверьте что `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` соответствуют нужному городу
2. Обновите `.env` с корректными параметрами города
3. Удалите `dns_monitor.db` чтобы начать с чистой БД
4. Запустите `python parser.py` для проверки новых параметров

### Telegram не отправляет
- Проверь `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`
- Убедись что бот добавлен в чат и имеет права
- Попробуй запустить в debug режиме: `LOG_LEVEL=DEBUG python run.py`

### Ошибка 401/403 от dns-shop.ru
- Вероятно, `qrator_jsid2` протухла (живет несколько часов)
- Попробуй запустить `python parser.py` — будет переполучена новая кука
- Если ошибка повторяется, возможна блокировка по IP

### На Linux парсинг не работает
- Убедись что установлен Playwright: `npx playwright install chromium`
- Попробуй включить DEBUG режим: `LOG_LEVEL=DEBUG python parser.py`
- Если сайт блокирует Linux, попробуй: `USE_PLATFORM_UA=false` (по умолчанию) или явно укажи `USE_PLATFORM_UA=true` для использования реального UA Linux
- Проверь что node найден в PATH: `which node`
- Посмотри логи в `logs/app.log`

### Сайт детектирует отладку/бота
- **Режим отладки не влияет** на внешнее поведение парсера — только выводит подробные логи
- LOG_LEVEL=DEBUG это ТОЛЬКО для логирования, не меняет UserAgent или поведение
- DNS хорошо детектирует режимы через Qrator WAF — это нормально и учтено в коде

## 📦 История версий

### v1.2 (2026-04-20) — ✅ Стабильный релиз
**Полная функциональность с админ-панелью, telegram ботом и retry логикой**

#### Ключевые особенности v1.0:
- ✅ **Админ-панель** для управления парсером (запуск/остановка/статус)
- ✅ **Telegram бот** для подписки пользователей на уведомления
- ✅ **Retry логика** с exponential backoff для решения Qrator
- ✅ **Persistent Chromium профиль** для сохранения куков между циклами
- ✅ **Кроссплатформенность**: Windows, Linux, macOS, Docker
- ✅ **Управляемое логирование**: `LOG_LEVEL=DEBUG` для детальных логов
- ✅ **Comprehensive тесты** (100+ юнит-тестов)

#### Протестировано и подтверждено:
- Windows 10/11 ✅
- Linux (Ubuntu 20.04+, Debian 11+) ✅
- Python 3.8+ ✅
- Node.js 14+ ✅

## 📄 Лицензия

MIT

## 👤 Автор

DNS Shop Parser — автоматизация парсинга товаров
