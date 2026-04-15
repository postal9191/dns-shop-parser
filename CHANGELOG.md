# Changelog

Все значительные изменения в проекте будут документированы в этом файле.

## [1.0] - 2026-04-15

### ✨ Новое
- **Полная кроссплатформенность**: Windows, Linux (Ubuntu/Debian), macOS
- **Адаптивные UserAgent**: Автоматическое определение платформы
  - Windows: `Mozilla/5.0 (Windows NT 10.0; Win64; x64)...`
  - Linux: `Mozilla/5.0 (X11; Linux x86_64)...`
  - macOS: `Mozilla/5.0 (Macintosh; Intel Mac OS X)...`
- **Управляемое логирование**: `LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`
- **Переменная окружения `USE_PLATFORM_UA`**: Использовать реальный UA платформы или Windows (по умолчанию)

### 🔧 Улучшения
- **qrator_resolver.py**:
  - Поиск `node` в PATH через `shutil.which()`
  - Fallback пути для Windows (Program Files)
  - Более информативные сообщения об ошибках
  - Подсказки при проблемах с Playwright на Linux

- **solve_qrator.js**:
  - Определение UserAgent по `require('os').platform()`
  - Поддержка Linux, macOS, Windows

- **session_manager.py**:
  - Функции `_get_platform_ua()` и `_get_base_headers()` для кроссплатформенности
  - Динамическое формирование заголовков `sec-ch-ua-platform`

- **utils/logger.py**:
  - Управление уровнем логирования через `LOG_LEVEL`
  - По умолчанию `INFO` в консоль, все в файл `logs/app.log`

- **dns-parser.sh**:
  - Исправлена кодировка для Linux (CRLF → LF)
  - Права на исполнение добавлены

- **config.py**:
  - Добавлены параметры `log_level` и `use_platform_ua`

- **README.md**:
  - Полная документация по troubleshooting для Windows и Linux
  - Информация о режиме отладки и детектировании сайтом

### 📋 Требования
- Python 3.8+
- Node.js 14+
- npm

### ✅ Протестировано
- Windows 11 ✅
- Linux (Ubuntu 20.04, 22.04) ✅
- macOS (теоретически, UserAgent поддерживается)
- Python 3.8, 3.9, 3.10, 3.11 ✅
- Node.js 16, 18, 20 ✅

### 🐛 Известные проблемы
- На Linux требуется явная установка Playwright: `npx playwright install chromium --with-deps`
- Сайт может блокировать некоторые IP-адреса (не связано с парсером)
- Qrator WAF токен живет несколько часов (автоматически переполучается)

### 🔮 План на будущее (v1.1+)
- [ ] Поддержка других городов России
- [ ] Веб-интерфейс для управления парсером
- [ ] Экспорт в CSV/JSON
- [ ] Docker образ для легкого развертывания
- [ ] Интеграция с другими мессенджерами (Discord, Slack)
- [ ] Кеширование на уровне приложения

---

## История версий

- **v1.0 (2026-04-15)**: Первая стабильная версия с полной поддержкой Windows и Linux
