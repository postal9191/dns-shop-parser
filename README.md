# DNS Shop Parser

Автоматический мониторинг скидок в DNS Shop с персонализированными уведомлениями через Telegram-бот.

## Возможности

- **Персонализация**: выбор города, категорий товаров, минимального порога скидки
- **Умные уведомления**: только о новых товарах или снижении цен по вашим критериям
- **Надежность**: автовосстановление после сбоев, circuit breaker при множественных ошибках
- **Эффективность**: гибридная архитектура Node.js + Python для обхода защиты и парсинга

## Установка

```bash
# Зависимости
npm install
npx playwright install chromium
pip install -r requirements.txt

# Конфигурация
cp .env.example .env
# Отредактируйте .env: добавьте TELEGRAM_TOKEN и TELEGRAM_CHAT_ADMIN

# Запуск
python run.py
```

## Использование

1. Найдите бота: `@dns_shop_parser_bot`
2. Запустите: `/start`
3. Настройте: город, категории, порог скидки, типы уведомлений

## Конфигурация

### Обязательные параметры (.env)
```env
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ADMIN=your_telegram_user_id
```

### Дополнительные настройки
```env
API_BASE_URL=https://www.dns-shop.ru
DB_PATH=dns_monitor.db
PARSE_INTERVAL=3600
PARSE_CONCURRENCY=5
LOG_LEVEL=INFO

# Прокси (опционально)
PROXY_HOST=proxy.example.com
PROXY_PORT=8080
PROXY_USER=username
PROXY_PASSWORD=password
```

## Поддерживаемые города

- **Краснодар**: парсинг каждый час (07:00-20:00 МСК)
- **Москва**: парсинг ночью (00:00-06:00 МСК)  
- **Санкт-Петербург**: парсинг ночью (00:00-06:00 МСК)

## Команды разработчика

```bash
# Основные режимы
python run.py                           # Полный режим (парсинг + бот)
python parser.py --city-slug krasnodar  # Однократный парсинг
python bot_only.py                      # Только Telegram бот
node solve_qrator.js                    # Тест обхода Qrator WAF

# Тестирование
pip install -r tests/requirements-test.txt
pytest -q
```

## Архитектура

```
run.py (asyncio event loop)
├── main_cycle()           ← парсинг в subprocess каждые N секунд
│   └── parser.py          ← subprocess (timeout 10 мин)
│       ├── qrator_resolver.py → solve_qrator.js (Playwright)
│       ├── session_manager.py → aiohttp сессия с куками
│       ├── simple_dns_parser.py → HTTP → категории → UUID → детали
│       ├── db_manager.py → SQLite (upsert, история цен)
│       └── telegram_notifier.py → персональный дайджест
└── telegram_bot_polling() ← Telegram polling (параллельно)
```

### Поток выполнения
1. `run.py` запускает `parser.py` как subprocess каждый цикл
2. `parser.py` вызывает `session_manager._init_session()` → запускает `solve_qrator.js`
3. `solve_qrator.js` открывает headless Chromium, извлекает cookies → stdout
4. `SimpleDNSParser` получает категории → UUID → детали товаров через POST
5. `DBManager.upsert_products()` сохраняет изменения, возвращает дельты цен
6. `TelegramNotifier.send_digest()` отправляет персональные уведомления

## База данных

SQLite (`dns_monitor.db`):
- `products` — товары с uuid, статусом, городом
- `price_history` — история изменений цен
- `category_state` — состояние категорий для детекции изменений
- `telegram_subscribers` — подписчики с настройками
- `user_settings` — персональные настройки пользователей
- `user_categories` — выбранные категории товаров

## Особенности

- **Qrator cookies**: переиспользуются между циклами через постоянный профиль Chromium
- **Расписание**: Краснодар парсится в рабочее время, другие города — ночью
- **Circuit breaker**: экспоненциальная задержка после серии ошибок
- **Graceful degradation**: `parser.py` всегда завершается с кодом 0

## Лицензия

Проект создан для личного использования и образовательных целей.