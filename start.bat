@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DeepSeek Proxy

:menu
cls
echo ================================================================
echo        DEEPSEEK DUAL-PORT PROXY - WYBOR TRYBU
echo ================================================================
echo.
echo   [1] STANDARD DUAL (Zalecany):
echo       - Port 4570: KODOWANIE (Trae / Cursor / Cortex)
echo       - Port 4571: CZYSTY PASSTHROUGH (Useme Core / Boty)
echo.
echo   [2] CZYSTY PROMPT2 (z pliku prompt2.txt na 4570)
echo.
echo ================================================================
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
echo [*] Ubijanie starych procesow na portach 4570 i 4571...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4570" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4571" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [*] Czyszczenie __pycache__...
for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

echo [*] Uruchamianie proxy...
echo ============================================
echo.
set "PY_CMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"
"%PY_CMD%" -u server.py %PROXY_ARGS%
pause