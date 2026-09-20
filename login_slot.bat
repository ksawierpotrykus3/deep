@echo off
setlocal
cd /d "%~dp0"

set SLOT=%1
if "%SLOT%"=="" (
    echo ===================================================
    echo           DEEPSEEK PROXY - LOGOWANIE KONTA
    echo ===================================================
    echo.
    set /p SLOT="Podaj numer slotu do zalogowania (np. 3, 4, 5...) [domyslnie 3]: "
)
if "%SLOT%"=="" set SLOT=3

echo.
set "PY_CMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"
"%PY_CMD%" login.py %SLOT%

echo.
pause
