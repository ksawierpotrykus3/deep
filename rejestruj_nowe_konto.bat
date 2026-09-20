@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================================================
echo    DEEPSEEK - ASYSTENT REJESTRACJI NOWEGO KONTA Z ALIASEM
echo ================================================================
echo.
set "PY_CMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"

if "%~1"=="" (
    "%PY_CMD%" scripts\register_account.py
) else (
    "%PY_CMD%" scripts\register_account.py %1
)

echo.
echo Rejestracja zakonczona. Nacisnij dowolny klawisz, aby zamknac...
pause > nul
