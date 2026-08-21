@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DeepSeek Proxy

:menu
cls
echo ============================================
echo     DEEPSEEK PROXY - WYBOR TRYBU STARTU
echo ============================================
echo.
echo   [1] NORMALNY  - Twoj obecny tryb
echo   [2] CZYSTY    - wlasny prompt (prompt2.txt)
echo.
choice /c 12 /n /m "Wybierz (1-2): "
if errorlevel 2 goto clean
if errorlevel 1 goto normal

:normal
set PROXY_ARGS=
goto run

:clean
set PROXY_ARGS=--clean
goto run

:run
echo [*] Ubijanie starego procesu na porcie 4570...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4570" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    if errorlevel 1 (
        echo     ! Nie moge zabic PID %%a - brak uprawnien. Uruchom jako Administrator.
    ) else (
        echo     Zabito PID %%a
    )
)

echo [*] Czyszczenie __pycache__...
for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

echo [*] Uruchamianie proxy...
echo ============================================
echo.
python -u server.py %PROXY_ARGS%
pause