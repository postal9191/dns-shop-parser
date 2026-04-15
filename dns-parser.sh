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

check_chromium() {
    print_info "Проверка Chrome..."

    if command -v google-chrome &> /dev/null; then
        print_success "Chrome установлен"
        return 0
    elif command -v google-chrome-stable &> /dev/null; then
        print_success "Chrome установлен"
        return 0
    else
        print_warning "Chrome не найден, установка..."
        install_chrome
    fi
}

install_chrome() {
    # Определяем дистрибутив
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        print_error "Не удалось определить дистрибутив Linux"
        return 1
    fi

    case $OS in
        ubuntu|debian)
            print_info "Установка Chrome для Debian/Ubuntu..."
            sudo apt-get update -qq

            # Добавляем репозиторий Google Chrome
            print_info "Добавление репозитория Google Chrome..."
            sudo apt-get install -y curl wget 2>/dev/null || true
            curl -s https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add - 2>/dev/null || true
            echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list 2>/dev/null || true
            sudo apt-get update -qq

            # Установка Chrome
            sudo apt-get install -y google-chrome-stable

            # Установка Xvfb для виртуального дисплея
            print_info "Установка Xvfb (виртуальный дисплей)..."
            sudo apt-get install -y xvfb

            # Дополнительные зависимости для полной работы
            print_info "Установка зависимостей Chrome..."
            sudo apt-get install -y \
                libglib2.0-0 libgconf-2-4 libappindicator1 libindicator7 \
                libxss1 libxext6 libxrender1 fonts-liberation \
                libappindicator3-1 libasound2 libatk-bridge2.0-0 \
                libatk1.0-0 libcups2 libdbus-1-3 libexpat1 libgcc1 \
                libgdk-pixbuf2.0-0 libgtk-3-0 libpango-1.0-0 \
                libpangocairo-1.0-0 libx11-6 libxcb1 libxcomposite1 \
                libxcursor1 libxdamage1 libxfixes3 libxi6 libxinerama1 \
                libxrandr2 libxshmfence1 libxtst6 libdrm2 libgbm1 2>/dev/null || true
            ;;
        fedora)
            print_info "Установка Chrome для Fedora..."
            sudo dnf install -y google-chrome-stable xvfb
            ;;
        centos|rhel)
            print_info "Установка Chrome для CentOS/RHEL..."
            sudo yum install -y google-chrome-stable xvfb
            ;;
        *)
            print_error "Неподдерживаемый дистрибутив: $OS"
            print_info "Пожалуйста, установите Chrome вручную"
            return 1
            ;;
    esac

    if [ $? -eq 0 ] || command -v google-chrome &> /dev/null; then
        print_success "Chrome и Xvfb установлены успешно"
    else
        print_error "Не удалось установить Chrome"
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

    # Обновляем pip используя venv python напрямую
    print_info "Обновление pip..."
    "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel --quiet 2>&1 | grep -v "WARNING" || true

    # Устанавливаем зависимости
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        print_info "Установка зависимостей из requirements.txt..."
        "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>&1 | grep -v "WARNING" || true
        print_success "Зависимости установлены"
    else
        print_warning "requirements.txt не найден"
    fi
}

check_xvfb() {
    if [ "$(uname)" != "Linux" ]; then
        return 0  # Xvfb нужен только на Linux
    fi

    print_info "Проверка Xvfb..."

    if command -v Xvfb &> /dev/null; then
        print_success "Xvfb установлен"
        return 0
    else
        print_warning "Xvfb не найден, установка..."

        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$ID
        fi

        case $OS in
            ubuntu|debian)
                sudo apt-get update -qq
                sudo apt-get install -y xvfb
                ;;
            fedora)
                sudo dnf install -y xvfb
                ;;
            centos|rhel)
                sudo yum install -y xvfb
                ;;
            arch)
                sudo pacman -S --noconfirm xorg-server-xvfb
                ;;
            *)
                print_warning "Неизвестный дистрибутив, пропускаю установку Xvfb"
                return 0
                ;;
        esac

        if command -v Xvfb &> /dev/null; then
            print_success "Xvfb установлен успешно"
        else
            print_warning "Не удалось установить Xvfb, продолжаю без виртуального дисплея"
        fi
    fi
}

check_all_dependencies() {
    print_header "Проверка всех зависимостей"

    check_chromium || return 1
    check_xvfb || return 1
    check_python || return 1
    check_pip_dependencies || return 1

    print_success "Все зависимости проверены и установлены!"
}

################################################################################
# Управление сервисом
################################################################################

start_service() {
    print_header "Запуск DNS Parser"

    check_all_dependencies || return 1

    # Создаём папку для логов
    print_info "Создание папки для логов..."
    mkdir -p "$PROJECT_DIR/logs"

    # Проверяем Xvfb на Linux для виртуального дисплея
    if [ "$(uname)" == "Linux" ]; then
        if ! command -v Xvfb &> /dev/null; then
            print_warning "Xvfb не установлен, но Chrome может работать в headless режиме"
        else
            # Проверяем есть ли уже запущенный Xvfb
            if ! ps aux | grep -q "[X]vfb :99"; then
                print_info "Запуск виртуального дисплея (Xvfb)..."
                Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
                sleep 1
            fi
            export DISPLAY=:99
            print_info "Используется виртуальный дисплей: DISPLAY=:99"
        fi
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

    print_info "Запуск приложения..."

    # Запускаем в фоне с venv python и DISPLAY для Linux
    if [ "$(uname)" == "Linux" ]; then
        nohup env DISPLAY=:99 "$VENV_PYTHON" "$PROJECT_DIR/run.py" > "$LOG_FILE" 2>&1 &
    else
        nohup "$VENV_PYTHON" "$PROJECT_DIR/run.py" > "$LOG_FILE" 2>&1 &
    fi
    echo $! > "$PID_FILE"

    sleep 2

    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        print_success "Приложение запущено (PID: $PID)"
        print_info "Логи: $LOG_FILE"
    else
        print_error "Не удалось запустить приложение"
        if [ -f "$LOG_FILE" ]; then
            tail -20 "$LOG_FILE"
        else
            print_warning "Лог файл не создан, проверьте ошибки выше"
        fi
        return 1
    fi
}

stop_service() {
    print_header "Остановка DNS Parser"

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            print_info "Остановка процесса (PID: $PID)..."
            kill $PID
            sleep 2

            if ! kill -0 $PID 2>/dev/null; then
                print_success "Приложение остановлено"
                rm -f "$PID_FILE"
            else
                print_warning "Принудительная остановка..."
                kill -9 $PID
                rm -f "$PID_FILE"
                print_success "Приложение остановлено (kill -9)"
            fi
        else
            print_warning "Процесс не найден"
            rm -f "$PID_FILE"
        fi
    else
        print_warning "PID файл не найден, процесс может быть остановлен"
    fi
}

restart_service() {
    print_header "Перезапуск DNS Parser"
    stop_service
    sleep 1
    start_service
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

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            print_success "Статус: ЗАПУЩЕНО (PID: $PID)"
            echo -e "  $(ps aux | grep $PID | grep -v grep)"
        else
            print_error "Статус: ОСТАНОВЛЕНО (PID файл устарел)"
        fi
    else
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
Description=DNS Shop Parser Service
After=network.target
StartLimitInterval=60
StartLimitBurst=3

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
Environment=\"PATH=$VENV_DIR/bin:$PATH\"
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
    echo -e "${BLUE}║   DNS Shop Parser - Service Manager   ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo "Выберите действие:"
    echo ""
    echo "  1 - Запустить приложение"
    echo "  2 - Остановить приложение"
    echo "  3 - Перезапустить приложение"
    echo "  4 - Показать логи"
    echo "  5 - Проверить статус"
    echo "  6 - Управление systemd сервисом"
    echo "  0 - Выход"
    echo ""
    echo -n "Ваш выбор: "
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
            0)
                print_info "До свидания!"
                exit 0
                ;;
            *)
                print_error "Неверный выбор. Пожалуйста, выберите 0-6"
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
