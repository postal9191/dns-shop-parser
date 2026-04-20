@echo off
echo Запуск тестов...
python -m pytest tests/ -v --tb=short
if %errorlevel% equ 0 (
    echo.
    echo ✅ Все тесты пройдены!
) else (
    echo.
    echo ❌ Некоторые тесты не пройдены
)
pause
