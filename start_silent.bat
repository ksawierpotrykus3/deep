@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DeepSeek Proxy (silent)

echo [*] Ubijanie starych procesow na portach 4570 i 4571...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4570" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4571" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

set "PY_CMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"
"%PY_CMD%" -u server.py %*