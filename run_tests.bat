@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo Запуск тестов...
echo.

python -m pytest tests/ -v --tb=short -x
set TEST_RESULT=!errorlevel!

echo.
if !TEST_RESULT! equ 0 (
    echo ✅ Все тесты пройдены!
) else (
    echo ❌ Некоторые тесты не пройдены (код ошибки: !TEST_RESULT!)
)
echo.
pause
