# DNS Shop Parser — Краснодар

Автоматический парсер товаров с сайта DNS-shop.ru (категория уценка) для города Краснодар.

## 🚀 Возможности

- ✅ **Автоматическое обновление куков** через браузер (Chrome)
- ✅ **Парсинг товаров** через API без блокировок
- ✅ **Уведомления в Telegram** о новых товарах
- ✅ **Сохранение в БД** (SQLite)
- ✅ **Контроль интервала** обновления
- ✅ **Логирование** всех операций

## 📋 Требования

- Python 3.8+
- Chrome/Chromium браузер
- pip для установки зависимостей

## 🔧 Установка

### 1. Клонирование

```bash
git clone <repo>
cd dns-shop-parser
```

### 2. Зависимости

```bash
pip install -r requirements.txt
```

### 3. Конфигурация

Скопируй `.env.example` в `.env` и отредактируй:

```bash
cp .env.example .env
```

**Важные переменные в `.env`:**

```env
# Город
CITY_NAME=Краснодар
CITY_ID=884019c7-cf52-11de-b72b-00151716f9f5

# Куки Краснодара
CITY_COOKIE_PATH=krasnodar
CITY_COOKIE_CURRENT=<длинная кука>

# Интервал парсинга (в секундах)
PARSE_INTERVAL=3600  # 1 час

# Telegram (опционально)
TELEGRAM_TOKEN=<токен>
TELEGRAM_CHAT_ID=<ID чата>

# Chrome
CHROME_HEADLESS=false
```

## 🏃 Запуск

### Полностью автоматический режим (рекомендуется)

```bash
python run.py
```

Что происходит:
1. Обновляет куки браузером (get_cookies.py)
2. Парсит товары (parser.py)
3. Ждет PARSE_INTERVAL секунд
4. Повторяет бесконечно

### Ручной запуск

**Шаг 1: Получить куки**
```bash
python get_cookies.py
# Результат: browser_cookies.pkl
```

**Шаг 2: Парсить товары**
```bash
python parser.py
# Сохраняет в БД + отправляет в ТГ
```

## 📊 Структура проекта

```
├── run.py                  # Главный скрипт (автоматический цикл)
├── get_cookies.py          # Получение куков браузером
├── parser.py               # Парсинг товаров
├── config.py               # Конфигурация
├── requirements.txt        # Зависимости
├── .env                    # Переменные окружения
├── .env.example            # Пример .env
├── dns_monitor.db          # БД товаров (создается автоматически)
│
├── parser/
│   ├── db_manager.py       # Работа с БД
│   ├── session_manager.py  # HTTP сессия
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

## 🔄 Поток работы

```
Итерация 1:
  ├─ get_cookies.py → Браузер открывает сайт, добавляет куки
  ├─ parser.py      → Парсит товары (первый раз, ТГ молчит)
  └─ Ждет 3600 сек

Итерация 2:
  ├─ get_cookies.py → Обновляет куки
  ├─ parser.py      → Парсит товары (новые → ТГ уведомления)
  └─ Ждет 3600 сек

Итерация N:
  └─ (повторяется)
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

1. Получи ID города и куки через браузер
2. Обнови `.env`:
   ```env
   CITY_ID=<новый ID>
   CITY_NAME=<новое название>
   CITY_COOKIE_PATH=<новая кука>
   CITY_COOKIE_CURRENT=<новая кука>
   ```
3. Удали `dns_monitor.db` чтобы начать с чистой БД
4. Запусти `python run.py`

## ⚙️ Опции запуска

**Chrome в headless режиме** (без окна):
```env
CHROME_HEADLESS=true
```

**Изменить интервал** парсинга:
```env
PARSE_INTERVAL=1800  # 30 минут
```

**Telegram отключен:**
```env
TELEGRAM_TOKEN=     # Оставить пусто
```

## 📝 Логирование

Логи выводятся в консоль и сохраняются в папку `logs/`.

Уровни логирования:
- `INFO` — основные события
- `WARNING` — предупреждения (например, куки отсутствуют)
- `ERROR` — ошибки (парсинг, ТГ)
- `DEBUG` — детальная информация

## 🐛 Troubleshooting

### Браузер не открывается
- Убедись что Chrome установлен
- Попробуй `CHROME_HEADLESS=false`

### Город неправильный
- Проверь `CITY_COOKIE_PATH` и `CITY_COOKIE_CURRENT` в `.env`
- Запусти `python get_cookies.py` заново

### Telegram не отправляет
- Проверь `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ID`
- Убедись что бот добавлен в чат

### solve_qrator.js не найден
- Это предупреждение можно игнорировать
- Куки получаются через браузер, файл не нужен

## 📄 Лицензия

MIT

## 👤 Автор

DNS Shop Parser — автоматизация парсинга товаров Краснодара
