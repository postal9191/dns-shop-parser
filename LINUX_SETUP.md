# Установка и запуск DNS Parser на Linux

Этот скрипт автоматизирует всю процедуру установки и управления DNS парсером на Linux (Ubuntu, Debian, Fedora, CentOS и др.).

## 🚀 Быстрый старт

### 1. Подготовка скрипта

```bash
# Скачайте/скопируйте проект в нужную папку
cd /path/to/dns-parser

# Дайте скрипту права на исполнение
chmod +x dns-parser.sh
```

### 2. Запуск интерактивного меню

```bash
./dns-parser.sh
```

Вы увидите меню с опциями:

```
╔════════════════════════════════════════╗
║   DNS Shop Parser - Service Manager   ║
╚════════════════════════════════════════╝

Выберите действие:

  1 - Запустить приложение
  2 - Остановить приложение
  3 - Перезапустить приложение
  4 - Показать логи
  5 - Проверить статус
  6 - Добавить в systemd (автозагрузка)
  7 - Удалить из systemd
  0 - Выход
```

## 📋 Что делает скрипт

### Проверка и установка зависимостей

При первом запуске скрипт автоматически:

✓ **Проверяет Chromium** — если не установлен, автоматически устанавливает
✓ **Проверяет Python 3** — если нет, устанавливает Python 3 и pip
✓ **Создаёт виртуальное окружение** (`venv/`)
✓ **Устанавливает Python зависимости** из `requirements.txt`

Поддерживаемые дистрибутивы:
- Ubuntu / Debian
- Fedora
- CentOS / RHEL
- Arch Linux

### Опции меню

#### 1️⃣ Запустить приложение

```bash
./dns-parser.sh
# Выбираем пункт 1
```

Действия:
- Проверяет все зависимости
- Запускает приложение в фоне
- Выводит PID и путь к логам

Логи в реальном времени:
```bash
tail -f logs/app.log
```

#### 2️⃣ Остановить приложение

```bash
./dns-parser.sh
# Выбираем пункт 2
```

Остановит процесс парсера gracefully (SIGTERM).

#### 3️⃣ Перезапустить приложение

```bash
./dns-parser.sh
# Выбираем пункт 3
```

Остановит и снова запустит парсер.

#### 4️⃣ Показать логи

```bash
./dns-parser.sh
# Выбираем пункт 4
```

Выводит последние 50 строк логов в режиме follow (`tail -f`).

Выход: **Ctrl+C**

#### 5️⃣ Проверить статус

```bash
./dns-parser.sh
# Выбираем пункт 5
```

Показывает:
- Запущено ли приложение
- PID процесса
- Информацию о процессе

#### 6️⃣ Добавить в systemd (автозагрузка)

```bash
./dns-parser.sh
# Выбираем пункт 6
```

Действия:
- Создаёт systemd unit файл: `/etc/systemd/system/dns-parser.service`
- Активирует автозагрузку сервиса
- Запускает сервис
- Выводит полезные команды для управления

После этого вы сможете управлять сервисом командами:

```bash
# Запустить сервис
sudo systemctl start dns-parser

# Остановить сервис
sudo systemctl stop dns-parser

# Перезапустить сервис
sudo systemctl restart dns-parser

# Показать статус
sudo systemctl status dns-parser

# Логи в реальном времени
journalctl -u dns-parser -f

# Отключить автозагрузку
sudo systemctl disable dns-parser
```

#### 7️⃣ Удалить из systemd

```bash
./dns-parser.sh
# Выбираем пункт 7
```

Действия:
- Остановляет сервис
- Удаляет из автозагрузки
- Удаляет unit файл

#### 0️⃣ Выход

Выход из меню.

## 💻 Команды из командной строки (без меню)

Вы можете вызывать скрипт с параметрами, минуя интерактивное меню:

```bash
# Запустить
./dns-parser.sh start

# Остановить
./dns-parser.sh stop

# Перезапустить
./dns-parser.sh restart

# Показать логи (follow режим)
./dns-parser.sh logs

# Проверить статус
./dns-parser.sh status

# Добавить в systemd
./dns-parser.sh enable-systemd

# Удалить из systemd
./dns-parser.sh disable-systemd
```

## ⚙️ Конфигурация

Отредактируйте `.env` файл перед первым запуском:

```bash
cp .env.example .env
nano .env
```

**Ключевые переменные:**

```env
# Telegram уведомления (опционально)
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Город и региональные куки
CITY_COOKIE_PATH=moscow
CITY_COOKIE_CURRENT=c5f58b981d1ed0bad...

# Интервал парсинга (в секундах)
PARSE_INTERVAL=3600

# Логирование
LOG_LEVEL=INFO  # DEBUG для подробных логов
```

## 🐛 Troubleshooting

### Ошибка: "Permission denied"

```bash
chmod +x dns-parser.sh
```

### Ошибка при установке пакетов

Скрипт использует `sudo` для установки системных пакетов. Убедитесь что ваш пользователь может использовать `sudo` без пароля или у вас готов пароль.

### Playwright браузер не установлен

Если парсер не запускается с ошибкой про браузер:

```bash
# Установите Playwright браузер
npm install
npx playwright install chromium

# Или вручную для системы:
sudo apt-get install chromium-browser  # Ubuntu/Debian
sudo dnf install chromium              # Fedora
sudo yum install chromium              # CentOS/RHEL
sudo pacman -S chromium                # Arch Linux
```

### Python зависимости не устанавливаются

```bash
# Установите вручную
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Процесс не запускается

1. Проверьте логи:
```bash
./dns-parser.sh logs
```

2. Попробуйте запустить напрямую:
```bash
source venv/bin/activate
python3 run.py
```

3. Проверьте `.env` файл — все ли переменные заполнены корректно

### systemd сервис не запускается

```bash
# Проверьте статус
sudo systemctl status dns-parser

# Смотрите логи systemd
journalctl -u dns-parser -n 50 -e

# Обновите unit файл и перезагрузитесь
./dns-parser.sh disable-systemd
./dns-parser.sh enable-systemd
```

## 📊 Структура файлов

```
dns-parser/
├── dns-parser.sh                   # Скрипт управления для Linux
├── run.py                          # Главный скрипт (цикл + админ-панель)
├── parser.py                       # Парсинг товаров (одноразово)
├── config.py                       # Конфигурация из .env
├── solve_qrator.js                 # Node.js скрипт (решение WAF)
├── .env                            # Переменные окружения
├── .env.example                    # Шаблон .env
├── requirements.txt                # Python зависимости
├── package.json                    # Node.js зависимости
├── logs/
│   └── app.log                    # Логи приложения
├── dns_monitor.db                 # SQLite база данных (создаётся автоматически)
│
├── parser/                         # Модуль парсера
│   ├── db_manager.py              # Работа с БД
│   ├── session_manager.py         # HTTP сессии + куки
│   ├── qrator_resolver.py         # Интеграция с solve_qrator.js
│   └── simple_dns_parser.py       # Парсер API DNS Shop
│
├── services/                       # Сервисы
│   ├── telegram_notifier.py       # Отправка уведомлений
│   ├── telegram_bot.py            # Telegram бот для подписки
│   └── admin_panel.py             # Админ-панель управления
│
└── utils/
    └── logger.py                   # Логирование
```

## 🔐 Безопасность

- `.env` файл с чувствительными данными исключён из git (см. `.gitignore`)
- systemd сервис запускается от пользователя (не от root)
- Логи содержат чувствительную информацию — ограничьте доступ к папке `logs/`

## 📝 Примеры использования

### Сценарий 1: Простой запуск на основную машину

```bash
cd /path/to/dns-parser
./dns-parser.sh
# Выбираем пункт 1 - Запустить
```

### Сценарий 2: Запуск как системный сервис (автозагрузка)

```bash
cd /path/to/dns-parser
./dns-parser.sh enable-systemd
```

После этого парсер будет:
- Запускаться при загрузке системы
- Автоматически перезапускаться при крахе
- Управляться через `systemctl`

Просмотр логов в реальном времени:
```bash
journalctl -u dns-parser -f
```

### Сценарий 3: Развёртывание на сервер (без GUI)

На сервере без X11 используйте `Xvfb` (виртуальный X сервер):

```bash
# Установка Xvfb
sudo apt-get install xvfb

# Запуск парсера с Xvfb
DISPLAY=:99 ./dns-parser.sh start
```

Или модифицируйте переменную в `.env`:
```env
CHROME_HEADLESS=true
```

### Сценарий 4: Мониторинг в реальном времени

```bash
# Terminal 1: Запуск приложения
./dns-parser.sh start

# Terminal 2: Следить за логами
./dns-parser.sh logs

# Terminal 3: Периодическая проверка статуса
watch -n 10 ./dns-parser.sh status
```

## 🎯 Полезные команды

```bash
# Основной скрипт
./dns-parser.sh                    # Интерактивное меню
./dns-parser.sh start              # Запустить
./dns-parser.sh stop               # Остановить
./dns-parser.sh status             # Статус

# Работа с логами
tail -f logs/app.log               # Логи в реальном времени
grep ERROR logs/app.log            # Ошибки в логах
head -100 logs/app.log             # Первые 100 строк

# Работа с systemd (если добавлен в systemd)
sudo systemctl status dns-parser   # Статус сервиса
journalctl -u dns-parser -f        # Логи systemd
sudo systemctl restart dns-parser  # Перезапуск

# Работа с базой данных
sqlite3 dns_monitor.db             # Откроет SQLite CLI
sqlite3 dns_monitor.db "SELECT COUNT(*) FROM products;"  # Кол-во товаров

# Проверка процесса
ps aux | grep dns-parser           # Все процессы python
pgrep -f run.py                    # PID основного процесса
```

## ✅ Контрольный список первого запуска

- [ ] Скопировать проект на Linux машину
- [ ] `chmod +x dns-parser.sh`
- [ ] Отредактировать `.env` с корректными токенами и настройками
- [ ] Запустить `./dns-parser.sh` и выбрать пункт 1
- [ ] Проверить логи `tail -f logs/app.log`
- [ ] Убедиться что парсер работает и данные сохраняются в БД
- [ ] (Опционально) Добавить в systemd: `./dns-parser.sh enable-systemd`

## 📚 Дополнительные материалы

- **[README.md](README.md)** — основная документация проекта
- **[INSTALLATION.md](INSTALLATION.md)** — детальная инструкция установки
- Логи приложения: `tail -f logs/app.log`
- Статус БД: `sqlite3 dns_monitor.db ".tables"`

---

**Версия:** 1.5 (2026-04-22)  
**Лицензия:** MIT  
**Поддерживаемые ОС:** Ubuntu 20.04+, Debian 11+, Fedora 35+, CentOS 8+, Arch Linux  
**Требования:** Python 3.8+, Node.js 14+
