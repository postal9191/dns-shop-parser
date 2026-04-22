#!/bin/bash

################################################################################
# DNS Parser Linux Service Manager
# Автоматическое управление DNS парсером с проверкой зависимостей и systemd
################################################################################

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Переменные
SERVICE_NAME="dns-parser"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD="python3"
LOG_FILE="$PROJECT_DIR/logs/app.log"
PID_FILE="/tmp/${SERVICE_NAME}.pid"
VENV_DIR="$PROJECT_DIR/venv"
DEPS_CHECK_FILE="$PROJECT_DIR/.deps-checked"
DEPS_CHECK_INTERVAL=86400  # 24 часа в секундах

################################################################################
# Функции вывода
################################################################################

print_header() {
    echo -e "\n${BLUE}=====================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=====================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

################################################################################
# Проверка и установка зависимостей
################################################################################

check_nodejs() {
    print_info "Проверка Node.js и npm..."

    if ! command -v node &> /dev/null; then
        print_warning "Node.js не найден, установка..."

        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$ID
        fi

        case $OS in
            ubuntu|debian)
                sudo apt-get update -qq
                sudo apt-get install -y nodejs npm
                ;;
            fedora)
                sudo dnf install -y nodejs npm
                ;;
            centos|rhel)
                sudo yum install -y nodejs npm
                ;;
            *)
                print_error "Неподдерживаемый дистрибутив: $OS"
                return 1
                ;;
        esac
    fi

    if command -v node &> /dev/null && command -v npm &> /dev/null; then
        NODE_VERSION=$(node --version)
        NPM_VERSION=$(npm --version)
        print_success "Node.js $NODE_VERSION и npm $NPM_VERSION установлены"
        return 0
    else
        print_error "Не удалось установить Node.js/npm"
        return 1
    fi
}

check_playwright() {
    print_info "Проверка Playwright браузера..."

    cd "$PROJECT_DIR"

    # Проверяем что npm зависимости установлены.
    # Смотрим не только на факт наличия node_modules, но и на ключевые пакеты —
    # иначе после обновления package.json новые deps не подтянутся.
    local NEED_NPM_INSTALL=0
    if [ ! -d "$PROJECT_DIR/node_modules" ]; then
        NEED_NPM_INSTALL=1
        print_warning "Node.js модули не установлены, установка..."
    else
        for pkg in playwright playwright-extra puppeteer-extra-plugin-stealth; do
            if [ ! -d "$PROJECT_DIR/node_modules/$pkg" ]; then
                NEED_NPM_INSTALL=1
                print_warning "Пакет '$pkg' отсутствует в node_modules — переустановка..."
                break
            fi
        done
    fi

    if [ $NEED_NPM_INSTALL -eq 1 ]; then
        npm install --quiet 2>&1 | grep -v "npm warn\|npm notice" || true
    fi

    # Пересобираем native модули
    print_info "Пересборка native модулей..."
    npm rebuild 2>&1 | grep -v "npm warn\|npm notice\|gyp info" || true

    # Устанавливаем bundled Playwright браузер
    npx playwright install chromium --with-deps 2>&1 | tail -5

    if [ $? -eq 0 ]; then
        print_success "Playwright браузер установлен"
        return 0
    else
        print_error "Не удалось установить Playwright браузер"
        return 1
    fi
}


check_python() {
    print_info "Проверка Python 3..."

    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 не установлен"
        print_info "Установка Python 3..."

        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$ID
        fi

        case $OS in
            ubuntu|debian)
                sudo apt-get update -qq
                sudo apt-get install -y python3 python3-pip python3-venv
                ;;
            fedora)
                sudo dnf install -y python3 python3-pip python3-venv
                ;;
            centos|rhel)
                sudo yum install -y python3 python3-pip python3-venv
                ;;
            arch)
                sudo pacman -S --noconfirm python python-pip
                ;;
        esac
    else
        # Python установлен, но может не быть python3-venv
        # Просто пробуем установить его для Debian/Ubuntu (не повредит если уже установлен)
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            if [[ "$ID" == "ubuntu" ]] || [[ "$ID" == "debian" ]]; then
                print_info "Проверка python3-venv..."
                # Получаем точную версию Python (например 3.10)
                local PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
                # Просто устанавливаем для конкретной версии
                sudo apt-get update -qq 2>/dev/null || true
                sudo apt-get install -y "python${PYTHON_VERSION}-venv" 2>/dev/null || sudo apt-get install -y python3-venv 2>/dev/null || true
            fi
        fi
    fi

    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    print_success "Python $PYTHON_VERSION установлен"
}

check_pip_dependencies() {
    print_info "Проверка Python зависимостей..."

    # Создаём venv если его нет
    if [ ! -d "$VENV_DIR" ]; then
        print_info "Создание виртуального окружения..."

        # Используем --upgrade-deps чтобы pip был установлен автоматически
        $PYTHON_CMD -m venv "$VENV_DIR" --upgrade-deps 2>&1 | grep -v "WARNING\|created" || true

        # Проверяем что venv создался
        if [ ! -f "$VENV_DIR/bin/python" ] && [ ! -f "$VENV_DIR/bin/python3" ]; then
            print_error "Не удалось создать виртуальное окружение"
            return 1
        fi

        print_success "Виртуальное окружение создано"
    fi

    # Находим python в venv
    local VENV_PYTHON="$VENV_DIR/bin/python3"
    if [ ! -f "$VENV_PYTHON" ]; then
        VENV_PYTHON="$VENV_DIR/bin/python"
    fi

    if [ ! -f "$VENV_PYTHON" ]; then
        print_error "Python в venv не найден"
        return 1
    fi

    # Проверяем что pip работает, если нет - устанавливаем его
    if ! "$VENV_PYTHON" -m pip --version &> /dev/null; then
        print_warning "pip не найден в venv, устанавливаю..."
        "$VENV_PYTHON" -m ensurepip --upgrade 2>&1 | grep -v "WARNING" || true
    fi

    # Обновляем pip используя venv python напрямую (скрываем verbose вывод)
    print_info "Обновление pip..."
    "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel --quiet 2>&1 | grep -v "WARNING\|Collecting\|Downloading\|Installing\|Preparing" || true

    # Устанавливаем зависимости
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        print_info "Установка зависимостей из requirements.txt..."
        "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>&1 | grep -v "WARNING\|Collecting\|Downloading\|Installing\|Preparing" || true
        print_success "Зависимости установлены"
    else
        print_warning "requirements.txt не найден"
    fi
}

check_all_dependencies() {
    # Проверяем нужна ли перепроверка зависимостей
    local need_check=1
    if [ -f "$DEPS_CHECK_FILE" ]; then
        local last_check=$(stat -c %Y "$DEPS_CHECK_FILE" 2>/dev/null || echo 0)
        local current_time=$(date +%s)
        local time_diff=$((current_time - last_check))

        if [ $time_diff -lt $DEPS_CHECK_INTERVAL ]; then
            print_info "Зависимости проверены недавно, пропускаю полную проверку"
            return 0
        fi
    fi

    print_header "Проверка всех зависимостей"

    check_nodejs || return 1
    check_python || return 1
    check_playwright || return 1
    check_pip_dependencies || return 1

    # Сохраняем время последней проверки
    touch "$DEPS_CHECK_FILE"

    print_success "Все зависимости проверены и установлены!"
}

################################################################################
# Управление сервисом
################################################################################

start_service() {
    print_header "Запуск парсера (однократно)"

    check_all_dependencies || return 1

    # Создаём папку для логов
    print_info "Создание папки для логов..."
    mkdir -p "$PROJECT_DIR/logs"

    # Находим python в venv
    local VENV_PYTHON="$VENV_DIR/bin/python3"
    if [ ! -f "$VENV_PYTHON" ]; then
        VENV_PYTHON="$VENV_DIR/bin/python"
    fi

    if [ ! -f "$VENV_PYTHON" ]; then
        print_error "Python в venv не найден"
        return 1
    fi

    print_info "Запуск парсера (в фоне)..."
    print_info "Режим: Node.js + Playwright (безбраузерный)"

    # Запускаем parser.py в фоне
    nohup "$VENV_PYTHON" "$PROJECT_DIR/parser.py" >> "$LOG_FILE" 2>&1 &
    local PID=$!

    sleep 1

    if kill -0 $PID 2>/dev/null; then
        print_success "Парсер запущен в фоне (PID: $PID)"
        print_info "Логи: tail -f $LOG_FILE"
    else
        print_error "Не удалось запустить парсер"
        if [ -f "$LOG_FILE" ]; then
            print_info "Ошибка:"
            tail -5 "$LOG_FILE"
        fi
        return 1
    fi
}

parse_env_interval() {
    # Читает PARSE_INTERVAL из .env и преобразует в cron формат
    local env_file="$PROJECT_DIR/.env"
    local parse_interval=3600  # по умолчанию 1 час

    if [ -f "$env_file" ]; then
        # Извлекаем PARSE_INTERVAL из .env
        parse_interval=$(grep "^PARSE_INTERVAL=" "$env_file" 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
    fi

    # Преобразуем секунды в cron формат
    if [ -z "$parse_interval" ]; then
        parse_interval=3600
    fi

    case $parse_interval in
        60)
            echo "* * * * *"  # каждую минуту
            ;;
        300)
            echo "*/5 * * * *"  # каждые 5 минут
            ;;
        600)
            echo "*/10 * * * *"  # каждые 10 минут
            ;;
        900)
            echo "*/15 * * * *"  # каждые 15 минут
            ;;
        1800)
            echo "*/30 * * * *"  # каждые 30 минут
            ;;
        3600)
            echo "0 * * * *"  # каждый час
            ;;
        7200)
            echo "0 */2 * * *"  # каждые 2 часа
            ;;
        86400)
            echo "0 0 * * *"  # каждый день в 00:00
            ;;
        *)
            # Для любого другого интервала - вычисляем минуты
            local minutes=$((parse_interval / 60))
            if [ $minutes -lt 60 ]; then
                echo "*/$minutes * * * *"
            else
                local hours=$((minutes / 60))
                echo "0 */$hours * * *"
            fi
            ;;
    esac
}

setup_cron_hourly() {
    print_header "Установка Cron (из PARSE_INTERVAL в .env)"

    # Читаем интервал из .env
    local PARSE_INTERVAL=3600
    if [ -f "$PROJECT_DIR/.env" ]; then
        PARSE_INTERVAL=$(grep "^PARSE_INTERVAL=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
    fi

    if [ -z "$PARSE_INTERVAL" ]; then
        PARSE_INTERVAL=3600
        print_warning "PARSE_INTERVAL не найден в .env, используется значение по умолчанию: 3600 сек (1 час)"
    else
        print_info "PARSE_INTERVAL из .env: $PARSE_INTERVAL сек"
    fi

    # Преобразуем в cron формат
    local CRON_SCHEDULE=$(parse_env_interval)
    local CRON_CMD="cd $PROJECT_DIR && $VENV_DIR/bin/python3 $PROJECT_DIR/parser.py >> $LOG_FILE 2>&1"

    # Описание расписания для вывода
    local schedule_desc="каждый час"
    case "$PARSE_INTERVAL" in
        60) schedule_desc="каждую минуту" ;;
        300) schedule_desc="каждые 5 минут" ;;
        600) schedule_desc="каждые 10 минут" ;;
        900) schedule_desc="каждые 15 минут" ;;
        1800) schedule_desc="каждые 30 минут" ;;
        3600) schedule_desc="каждый час" ;;
        7200) schedule_desc="каждые 2 часа" ;;
        86400) schedule_desc="каждый день" ;;
        *) schedule_desc="каждые $((PARSE_INTERVAL / 60)) минут" ;;
    esac

    # Проверяем есть ли уже такой cron
    if crontab -l 2>/dev/null | grep -q "$PROJECT_DIR/parser.py"; then
        print_warning "Cron уже установлен для этого проекта"
        print_info "Текущее расписание:"
        crontab -l | grep "$PROJECT_DIR/parser.py" || true
        print_info ""
        print_info "Чтобы обновить расписание, удалите старый cron (пункт 4) и установите новый"
        return 0
    fi

    # Создаём временный файл для cron
    local CRON_FILE="/tmp/dns-parser-cron-$$.txt"
    (crontab -l 2>/dev/null || true; echo "$CRON_SCHEDULE $CRON_CMD") > "$CRON_FILE"

    # Устанавливаем новый cron
    if crontab "$CRON_FILE" 2>/dev/null; then
        print_success "Cron установлен"
        print_info "Расписание: $schedule_desc"
        print_info "Cron выражение: $CRON_SCHEDULE"
        print_info "Команда: $CRON_CMD"
        print_info ""
        print_info "Проверить cron: crontab -l"
        print_info "Удалить cron: через пункт меню 4"
        rm -f "$CRON_FILE"
        return 0
    else
        print_error "Не удалось установить cron"
        rm -f "$CRON_FILE"
        return 1
    fi
}

remove_cron() {
    print_header "Удаление Cron"

    if ! crontab -l 2>/dev/null | grep -q "$PROJECT_DIR/parser.py"; then
        print_warning "Cron не установлен"
        return 0
    fi

    # Создаём новый cron без наших команд
    local CRON_FILE="/tmp/dns-parser-cron-remove-$$.txt"
    crontab -l 2>/dev/null | grep -v "$PROJECT_DIR/parser.py" > "$CRON_FILE" || true

    # Устанавливаем обновленный cron
    if [ -s "$CRON_FILE" ]; then
        crontab "$CRON_FILE"
    else
        crontab -r 2>/dev/null || true
    fi

    print_success "Cron удален"
    rm -f "$CRON_FILE"
}

show_cron_status() {
    print_header "Статус Cron"

    if crontab -l 2>/dev/null | grep -q "$PROJECT_DIR/parser.py"; then
        print_success "Cron установлен"
        print_info "Ваше расписание:"
        crontab -l | grep "$PROJECT_DIR/parser.py"
    else
        print_warning "Cron не установлен"
    fi
    echo ""
}

stop_service() {
    print_header "Остановка сервиса (systemd)"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Сервис не установлен в systemd"
        return 0
    fi

    print_info "Остановка сервиса..."
    sudo systemctl stop "$SERVICE_NAME" || true
    sleep 1

    if ! sudo systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_success "Сервис остановлен"
    else
        print_warning "Не удалось остановить сервис"
    fi
}

restart_service() {
    print_header "Перезапуск сервиса (systemd)"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Сервис не установлен в systemd"
        return 1
    fi

    print_info "Перезапуск сервиса..."
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Сервис перезапущен"
    else
        print_error "Не удалось перезапустить сервис"
        return 1
    fi
}

show_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        print_warning "Лог файл не найден: $LOG_FILE"
        return
    fi

    print_header "Логи приложения (последние 50 строк)"
    print_info "Нажмите Ctrl+C для выхода\n"

    tail -n 50 -f "$LOG_FILE"
}

show_status() {
    print_header "Статус DNS Parser"

    local status_found=0

    # Проверяем PID-файл (локальный запуск через пункт 1)
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            print_success "Статус: ЗАПУЩЕНО (локально, PID: $PID)"
            echo -e "  $(ps aux | grep $PID | grep -v grep)"
            status_found=1
        else
            rm -f "$PID_FILE"
        fi
    fi

    # Проверяем systemctl (если установлен)
    if [ -f "$SERVICE_FILE" ]; then
        if sudo systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            print_success "Статус: ЗАПУЩЕНО (systemctl)"
            sudo systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null | grep -E "Active|Main PID"
            status_found=1
        fi
    fi

    # Если ничего не найдено
    if [ $status_found -eq 0 ]; then
        print_error "Статус: ОСТАНОВЛЕНО"
    fi

    echo ""
}

################################################################################
# Systemd интеграция
################################################################################

create_systemd_unit() {
    print_header "Создание systemd unit файла"

    # Находим python в venv
    local VENV_PYTHON="$VENV_DIR/bin/python3"
    if [ ! -f "$VENV_PYTHON" ]; then
        VENV_PYTHON="$VENV_DIR/bin/python"
    fi

    # Если venv не существует, используем системный python
    if [ ! -f "$VENV_PYTHON" ]; then
        VENV_PYTHON="$(which python3)"
    fi

    UNIT_CONTENT="[Unit]
Description=DNS Shop Parser Service - безбраузерный парсер (Node.js + Playwright)
After=network.target
StartLimitInterval=60
StartLimitBurst=3

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
Environment=\"PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:$PATH\"
ExecStart=$VENV_PYTHON $PROJECT_DIR/run.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dns-parser

[Install]
WantedBy=multi-user.target
"

    print_info "Требуется sudo для создания systemd unit"
    echo "$UNIT_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null

    if [ $? -eq 0 ]; then
        print_success "Unit файл создан: $SERVICE_FILE"
        print_info "Перезагрузка systemd..."
        sudo systemctl daemon-reload
        print_success "systemd перезагружен"
    else
        print_error "Не удалось создать unit файл"
        return 1
    fi
}

enable_systemd() {
    print_header "Активация в systemd"

    if [ ! -f "$SERVICE_FILE" ]; then
        create_systemd_unit || return 1
    fi

    print_info "Активация сервиса..."
    sudo systemctl enable "$SERVICE_NAME"
    print_success "Сервис активирован"

    print_info "Запуск сервиса..."
    sudo systemctl start "$SERVICE_NAME"

    sleep 2

    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Сервис запущен"
        echo ""
        print_info "Команды для управления сервисом:"
        echo "  sudo systemctl start $SERVICE_NAME       # Запустить"
        echo "  sudo systemctl stop $SERVICE_NAME        # Остановить"
        echo "  sudo systemctl restart $SERVICE_NAME     # Перезапустить"
        echo "  sudo systemctl status $SERVICE_NAME      # Статус"
        echo "  journalctl -u $SERVICE_NAME -f          # Логи в реальном времени"
        echo ""
    else
        print_error "Не удалось запустить сервис"
        sudo systemctl status "$SERVICE_NAME"
        return 1
    fi
}

disable_systemd() {
    print_header "Удаление из systemd"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Unit файл не найден"
        return 1
    fi

    print_info "Остановка сервиса..."
    sudo systemctl stop "$SERVICE_NAME" || true

    print_info "Удаление из автозагрузки..."
    sudo systemctl disable "$SERVICE_NAME" || true

    print_info "Удаление unit файла..."
    sudo rm -f "$SERVICE_FILE"

    print_info "Перезагрузка systemd..."
    sudo systemctl daemon-reload

    print_success "Сервис удалён из systemd"
}

################################################################################
# Systemd подменю
################################################################################

systemctl_start() {
    print_header "Запуск сервиса через systemctl"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "Сервис не установлен в systemd"
        print_info "Установи сервис: выбери пункт 6 в главном меню"
        return 1
    fi

    print_info "Запуск сервиса..."
    sudo systemctl start "$SERVICE_NAME"

    sleep 2
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Сервис запущен"
    else
        print_error "Не удалось запустить сервис"
        sudo systemctl status "$SERVICE_NAME"
        return 1
    fi
}

systemctl_stop() {
    print_header "Остановка сервиса через systemctl"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "Сервис не установлен в systemd"
        return 1
    fi

    print_info "Остановка сервиса..."
    sudo systemctl stop "$SERVICE_NAME"

    sleep 1
    if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Сервис остановлен"
    else
        print_error "Не удалось остановить сервис"
        return 1
    fi
}

systemctl_restart() {
    print_header "Перезапуск сервиса через systemctl"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "Сервис не установлен в systemd"
        return 1
    fi

    print_info "Перезапуск сервиса..."
    sudo systemctl restart "$SERVICE_NAME"

    sleep 2
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Сервис перезапущен"
    else
        print_error "Не удалось перезапустить сервис"
        sudo systemctl status "$SERVICE_NAME"
        return 1
    fi
}

systemctl_status() {
    print_header "Статус сервиса"

    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Сервис не установлен в systemd"
        return 1
    fi

    sudo systemctl status "$SERVICE_NAME"
    echo ""
}

show_systemd_menu() {
    while true; do
        echo ""
        echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
        echo -e "${BLUE}║       Управление systemd сервисом     ║${NC}"
        echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
        echo ""
        echo "  1 - sudo systemctl start dns-parser"
        echo "  2 - sudo systemctl stop dns-parser"
        echo "  3 - sudo systemctl restart dns-parser"
        echo "  4 - sudo systemctl status dns-parser"
        echo "  5 - Установить сервис в systemd"
        echo "  6 - Удалить сервис из systemd"
        echo "  0 - Назад в главное меню"
        echo ""
        echo -n "Ваш выбор: "

        read -r choice

        case $choice in
            1)
                systemctl_start
                ;;
            2)
                systemctl_stop
                ;;
            3)
                systemctl_restart
                ;;
            4)
                systemctl_status
                ;;
            5)
                enable_systemd
                ;;
            6)
                disable_systemd
                ;;
            0)
                break
                ;;
            *)
                print_error "Неверный выбор. Пожалуйста, выберите 0-6"
                ;;
        esac
    done
}

################################################################################
# Главное меню
################################################################################

show_menu() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║ DNS Shop Parser - Service Manager    ║${NC}"
    echo -e "${BLUE}║ Режим: Node.js + Playwright (Linux) ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo "Выберите действие:"
    echo ""
    echo "  1 - Запустить приложение"
    echo "  2 - Остановить приложение"
    echo "  3 - Перезапустить приложение"
    echo "  4 - Показать логи (tail -f)"
    echo "  5 - Проверить статус"
    echo "  6 - Управление systemd сервисом"
    echo "  7 - Управление cron"
    echo "  0 - Выход"
    echo ""
    echo -n "Ваш выбор: "
}

kill_parser() {
    print_header "Остановка парсера (принудительно)"

    local killed=0

    # Ищем процессы парсера
    if pgrep -f "parser.py" > /dev/null; then
        print_info "Найдены процессы парсера, остановка..."
        pkill -f "parser.py"
        sleep 1

        if ! pgrep -f "parser.py" > /dev/null; then
            print_success "Парсер остановлен"
            killed=1
        else
            print_warning "Принудительная остановка..."
            pkill -9 -f "parser.py"
            print_success "Парсер остановлен (kill -9)"
            killed=1
        fi
    else
        print_warning "Процессов парсера не найдено"
    fi

    # Очищаем процессы Node.js
    if pgrep -f "node" > /dev/null; then
        print_info "Остановка Node.js процессов..."
        pkill -f "node" || true
        print_success "Node.js процессы остановлены"
    fi
}

show_cron_menu() {
    while true; do
        echo ""
        echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
        echo -e "${BLUE}║       Управление Cron (Linux)         ║${NC}"
        echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
        echo ""
        echo "  1 - Запустить парсер (однократно)"
        echo "  2 - Остановить парсер (принудительно)"
        echo "  3 - Показать логи (tail -f)"
        echo "  4 - Установить cron (каждый час)"
        echo "  5 - Удалить cron"
        echo "  6 - Проверить статус cron"
        echo "  0 - Назад в главное меню"
        echo ""
        echo -n "Ваш выбор: "

        read -r choice

        case $choice in
            1)
                start_service
                ;;
            2)
                kill_parser
                ;;
            3)
                show_logs
                ;;
            4)
                setup_cron_hourly
                ;;
            5)
                remove_cron
                ;;
            6)
                show_cron_status
                ;;
            0)
                break
                ;;
            *)
                print_error "Неверный выбор. Пожалуйста, выберите 0-6"
                ;;
        esac
    done
}

main_loop() {
    while true; do
        show_menu
        read -r choice

        case $choice in
            1)
                start_service
                ;;
            2)
                stop_service
                ;;
            3)
                restart_service
                ;;
            4)
                show_logs
                ;;
            5)
                show_status
                ;;
            6)
                show_systemd_menu
                ;;
            7)
                show_cron_menu
                ;;
            0)
                print_info "До свидания!"
                exit 0
                ;;
            *)
                print_error "Неверный выбор. Пожалуйста, выберите 0-7"
                ;;
        esac
    done
}

################################################################################
# Точка входа
################################################################################

# Проверяем что скрипт запущен из корректной директории
if [ ! -f "$PROJECT_DIR/run.py" ]; then
    print_error "Скрипт должен быть в корне проекта, где находится run.py"
    exit 1
fi

# Если передан аргумент, выполняем команду и выходим
if [ $# -gt 0 ]; then
    case $1 in
        start)
            start_service
            exit $?
            ;;
        stop)
            stop_service
            exit $?
            ;;
        restart)
            restart_service
            exit $?
            ;;
        logs)
            show_logs
            exit $?
            ;;
        status)
            show_status
            exit $?
            ;;
        enable-systemd)
            enable_systemd
            exit $?
            ;;
        disable-systemd)
            disable_systemd
            exit $?
            ;;
        *)
            print_error "Неизвестная команда: $1"
            echo ""
            echo "Использование: $0 [command]"
            echo ""
            echo "Команды:"
            echo "  start           - Запустить приложение"
            echo "  stop            - Остановить приложение"
            echo "  restart         - Перезапустить приложение"
            echo "  logs            - Показать логи"
            echo "  status          - Показать статус"
            echo "  enable-systemd  - Добавить в systemd"
            echo "  disable-systemd - Удалить из systemd"
            echo ""
            echo "Без аргументов запускает интерактивное меню."
            exit 1
            ;;
    esac
fi

# Запускаем интерактивное меню
main_loop
