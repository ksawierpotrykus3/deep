@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"

echo ===================================================
echo        DEEPSEEK PROXY - PANEL LOGOWANIA KONT
echo ===================================================
echo.
echo [1] AUTO-LOGIN wygaslych kont (odnawia automatycznie z accounts.json)
echo [2] AUTO-LOGIN wszystkich kont z data/accounts.json
echo [3] Zaloguj pojedynczy slot recznie przez okno Chrome (login.py)
echo [4] Sprawdz waznosc tokenow i stan banow (check_slots.py)
echo [5] Wyjscie
echo.
set /p OPT="Wybierz opcje [1-5, domyslnie 1]: "
if "%OPT%"=="" set OPT=1

if "%OPT%"=="1" (
    echo.
    echo Odnawianie tylko wygaslych sesji...
    "%PY_CMD%" auto_login.py --expired
    goto end
)

if "%OPT%"=="2" (
    echo.
    echo Logowanie wszystkich kont z data/accounts.json...
    "%PY_CMD%" auto_login.py --all
    goto end
)

if "%OPT%"=="3" (
    echo.
    set /p SLOT="Podaj numer slotu do zalogowania (np. 11, 12): "
    if "%SLOT%"=="" (
        echo [!] Nie podano numeru slotu.
        goto end
    )
    "%PY_CMD%" login.py %SLOT%
    goto end
)

if "%OPT%"=="4" (
    echo.
    "%PY_CMD%" check_slots.py
    goto end
)

:end
echo.
pause
