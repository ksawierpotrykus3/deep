@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DeepSeek Proxy (silent)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4570" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

python -u server.py %*