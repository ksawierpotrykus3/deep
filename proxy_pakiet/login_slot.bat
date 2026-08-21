@echo off
setlocal
cd /d "%~dp0"

set SLOT=%1
if "%SLOT%"=="" (
    echo ===================================================
    echo           DEEPSEEK PROXY - LOGOWANIE KONTA
    echo ===================================================
    echo.
    set /p SLOT="Podaj numer slotu do zalogowania (np. 0, 1, 2, 3, 4) [domyslnie 0]: "
)
if "%SLOT%"=="" set SLOT=0

echo.
python login.py %SLOT%

echo.
pause
