# 📖 Руководство по установке DNS Shop Parser v1.0

## 🪟 Windows

### Быстрая установка

```bash
# 1. Клонируй репозиторий
git clone https://github.com/postal9191/dns-shop-parser.git
cd dns-shop-parser

# 2. Установи зависимости
npm install
npx playwright install chromium

# 3. Установи Python зависимости
pip install -r requirements.txt

# 4. Конфигурация
cp .env.example .env
# Отредактируй .env если нужно (токены Telegram и т.д.)

# 5. Запуск
python run.py
```

### Детальные шаги

#### 1. Требования
- **Node.js 14+**: https://nodejs.org/
- **Python 3.8+**: https://www.python.org/
- **Git**: https://git-scm.com/

Проверь установку:
```bash
node --version
npm --version
python --version
```

#### 2. Клонирование
```bash
git clone https://github.com/postal9191/dns-shop-parser.git
cd dns-shop-parser
```

#### 3. Node.js зависимости
```bash
npm install
```

#### 4. Playwright браузер
```bash
# Установка Chromium
npx playwright install chromium
```

Проверка:
```bash
npx playwright list
```

#### 5. Python зависимости
```bash
# Вариант A: Система Python
pip install -r requirements.txt

# Вариант B: Virtual Environment (рекомендуется)
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

#### 6. Конфигурация
```bash
# Копируем пример конфига
copy .env.example .env

# Отредактируй .env в текстовом редакторе
# Основные параметры:
# - TELEGRAM_TOKEN и TELEGRAM_CHAT_ID (опционально)
# - CITY_ID и CITY_NAME если другой город
# - LOG_LEVEL=DEBUG для отладки
```

#### 7. Запуск

**Однократный запуск:**
```bash
python parser.py
```

**Автоматический цикл:**
```bash
python run.py
```

---

## 🐧 Linux (Ubuntu/Debian)

### Быстрая установка

```bash
# 1. Клонируй репозиторий
git clone https://github.com/postal9191/dns-shop-parser.git
cd dns-shop-parser

# 2. Исправь кодировку скрипта (если скопировано с Windows)
sed -i 's/\r$//' dns-parser.sh
chmod +x dns-parser.sh

# 3. Запусти автоматический скрипт установки
./dns-parser.sh

# Выбери пункт "1" для запуска (установит все необходимое)
```

### Или ручная установка

#### 1. Требования
```bash
# Node.js и npm
sudo apt-get update
sudo apt-get install -y nodejs npm

# Python 3
sudo apt-get install -y python3 python3-pip python3-venv

# Git (если не установлен)
sudo apt-get install -y git

# Проверка версий
node --version
npm --version
python3 --version
```

#### 2. Клонирование
```bash
git clone https://github.com/postal9191/dns-shop-parser.git
cd dns-shop-parser
```

#### 3. Node.js зависимости
```bash
npm install
```

#### 4. Playwright браузер
```bash
# Важно! Нужны дополнительные системные зависимости для Linux
npx playwright install chromium --with-deps
```

Если есть ошибки, установи зависимости вручную:
```bash
# Ubuntu/Debian
sudo apt-get install -y \
  libgbm-dev \
  libxdamage1 \
  libxrandr2 \
  libxcomposite1 \
  libxcursor1 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libcups2 \
  libcurl3-gnutls \
  libdrm2 \
  libgconf-2-4 \
  libgdk-pixbuf2.0-0 \
  libxss1 \
  libxt6 \
  libxext6
```

#### 5. Python зависимости
```bash
# Создай virtual environment
python3 -m venv venv
source venv/bin/activate

# Установи зависимости
pip install -r requirements.txt
```

#### 6. Конфигурация
```bash
# Копируем пример конфига
cp .env.example .env

# Отредактируй .env
nano .env
# или vim .env
```

#### 7. Запуск

**Однократный запуск:**
```bash
source venv/bin/activate
python3 parser.py
```

**Автоматический цикл:**
```bash
source venv/bin/activate
LOG_LEVEL=DEBUG python3 run.py
```

### Запуск как systemd сервис (рекомендуется)

```bash
# Используй интерактивное меню скрипта
./dns-parser.sh

# Выбери пункт "6" - Управление systemd сервисом
# Затем "5" - Установить сервис в systemd

# После установки, управлять сервисом можно командами:
sudo systemctl start dns-parser      # Запустить
sudo systemctl stop dns-parser       # Остановить
sudo systemctl restart dns-parser    # Перезапустить
sudo systemctl status dns-parser     # Статус
journalctl -u dns-parser -f          # Логи
```

---

## 🐳 Docker (опционально)

```bash
# Сборка образа
docker build -t dns-parser .

# Запуск контейнера
docker run -v $(pwd):/app --env-file .env dns-parser
```

---

## 🔧 Конфигурация

### Основные параметры .env

```env
# Город
CITY_ID=884019c7-cf52-11de-b72b-00151716f9f5  # Краснодар
CITY_NAME=Краснодар

# Интервал парсинга (секунды)
PARSE_INTERVAL=3600  # 1 час

# Telegram (опционально)
TELEGRAM_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Логирование
LOG_LEVEL=INFO  # или DEBUG для подробных логов

# Кроссплатформенность
USE_PLATFORM_UA=false  # false = Windows UA везде (совместимость)
                       # true = реальный UA вашей платформы
```

---

## 🐛 Troubleshooting

### Node.js не найден
```bash
# Проверь что node в PATH
which node
# или на Windows
where node

# Если не найден, переустанови Node.js
# https://nodejs.org/
```

### Playwright браузер не установлен
```bash
# Переустанови Playwright
npm install
npx playwright install chromium --with-deps  # Linux
npx playwright install chromium              # Windows
```

### Python зависимости не установлены
```bash
# Переустанови зависимости
pip install -r requirements.txt --upgrade
```

### DNS блокирует по IP
- Это не вина парсера
- Попробуй использовать VPN или прокси
- Или установи более длинный PARSE_INTERVAL чтобы избежать частых запросов

---

## ✅ Проверка установки

```bash
# 1. Проверь Node.js
node -v
npm -v

# 2. Проверь Python
python -v
# или python3 -v

# 3. Проверь Playwright
npx playwright list

# 4. Проверь что solve_qrator.js существует
ls -la solve_qrator.js

# 5. Проверь что requirements.txt установлен
pip list | grep -E "aiohttp|python-dotenv|playwright"
```

---

## 📝 Логирование

Логи сохраняются в `logs/app.log`

```bash
# Просмотр логов
tail -f logs/app.log

# Последние 50 строк
tail -50 logs/app.log

# Поиск ошибок
grep ERROR logs/app.log
```

---

## 🆘 Если что-то не работает

1. **Включи DEBUG логирование:**
   ```bash
   LOG_LEVEL=DEBUG python parser.py
   ```

2. **Посмотри логи:**
   ```bash
   tail -100 logs/app.log
   ```

3. **Проверь конфиг:**
   ```bash
   cat .env
   ```

4. **Переинициализируй куки:**
   ```bash
   rm dns_monitor.db
   python parser.py
   ```

5. **Откройте Issue на GitHub:**
   https://github.com/postal9191/dns-shop-parser/issues
   
   Приложи логи из `logs/app.log`
