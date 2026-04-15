# DNS Shop Parser — Краснодар

Автоматический парсер товаров с сайта DNS-shop.ru (категория уценка) для города Краснодар.  
**Без браузера — работает на Linux/Docker! 🐧**

## 🚀 Возможности

- ✅ **Получение куков** через Node.js + Playwright (без полного Chrome)
- ✅ **Решение Qrator WAF** через headless браузер (solve_qrator.js)
- ✅ **Парсинг товаров** через API без блокировок
- ✅ **Уведомления в Telegram** о новых товарах
- ✅ **Сохранение в БД** (SQLite)
- ✅ **Контроль интервала** обновления
- ✅ **Логирование** всех операций
- ✅ **Работает на Linux/Windows/Docker** без GUI

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

**Важные переменные в `.env`:**

```env
# Город (для Краснодара эти значения уже установлены)
CITY_NAME=Краснодар
CITY_ID=884019c7-cf52-11de-b72b-00151716f9f5

# Интервал парсинга (в секундах)
PARSE_INTERVAL=3600  # 1 час

# Telegram (опционально)
TELEGRAM_TOKEN=<токен>
TELEGRAM_CHAT_ID=<ID чата>
```

**Примечание:** куки для города строятся программно, вручную указывать не нужно.

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
├── run.py                  # Главный скрипт (автоматический цикл)
├── parser.py               # Парсинг товаров (инициализирует куки)
├── config.py               # Конфигурация
├── solve_qrator.js         # Node.js скрипт для решения Qrator WAF
├── package.json            # Зависимости Node.js
├── requirements.txt        # Зависимости Python
├── .env                    # Переменные окружения
├── .env.example            # Пример .env
├── dns_monitor.db          # БД товаров (создается автоматически)
│
├── parser/
│   ├── db_manager.py       # Работа с БД
│   ├── session_manager.py  # HTTP сессия + получение кук (Node.js)
│   ├── qrator_resolver.py  # Мост к solve_qrator.js
│   ├── simple_dns_parser.py# API парсер
│   ├── models.py           # Модели данных
│   └── exceptions.py       # Исключения
│
├── services/
│   ├── telegram_notifier.py# Отправка в ТГ
│   └── telegram_bot.py     # ТГ бот для подписки
│
└── utils/
    └── logger.py           # Логирование
```

## 🔄 Поток работы (новый — без браузера)

```
Итерация 1:
  ├─ solve_qrator.js (Node.js) → Решает Qrator challenge → получает qrator_jsid2
  ├─ parser.py инициализирует куки:
  │  ├─ HTTP GET с qrator_jsid2 → получает PHPSESSID
  │  ├─ _build_city_cookie() → строит current_path и city_path программно
  │  └─ Проверяет REST API для города
  ├─ Парсит товары (первый раз, ТГ молчит)
  └─ Ждет 3600 сек

Итерация 2:
  ├─ Используются сохраненные куки (Qrator токен живет долго)
  ├─ Парсит товары (новые → ТГ уведомления)
  └─ Ждет 3600 сек

Итерация N:
  └─ (повторяется, Qrator решается только если токен протух)
```

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

## 🛠 Конфигурация для других городов

Для парсинга других городов:

1. Найти ID города (например, через браузер на dns-shop.ru)
2. Обнови `.env`:
   ```env
   CITY_ID=<новый ID>
   CITY_NAME=<новое название>
   ```
3. Куки строятся программно автоматически (`_build_city_cookie()`)
4. Удали `dns_monitor.db` чтобы начать с чистой БД
5. Запусти `python run.py`

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

## 📝 Логирование

Логи выводятся в консоль и сохраняются в папку `logs/`.

Уровни логирования:
- `INFO` — основные события
- `WARNING` — предупреждения (например, куки отсутствуют)
- `ERROR` — ошибки (парсинг, ТГ)
- `DEBUG` — детальная информация

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

### Город неправильный
- `_build_city_cookie()` автоматически строит куки для города из `CITY_ID` и `CITY_NAME`
- Проверь что `CITY_ID` правильный в `.env`
- Если нужен другой город, обнови `.env` и удали `dns_monitor.db`

### Telegram не отправляет
- Проверь `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`
- Убедись что бот добавлен в чат и имеет права
- Попробуй запустить в debug режиме: `LOG_LEVEL=DEBUG python run.py`

### Ошибка 401/403 от dns-shop.ru
- Вероятно, `qrator_jsid2` протухла (живет несколько часов)
- Попробуй запустить `python parser.py` — будет переполучена новая кука
- Если ошибка повторяется, возможна блокировка по IP

## 📄 Лицензия

MIT

## 👤 Автор

DNS Shop Parser — автоматизация парсинга товаров Краснодара
