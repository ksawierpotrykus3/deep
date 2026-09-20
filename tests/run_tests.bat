@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title DeepSeek Proxy Test Suite

echo ================================================================
echo             DEEPSEEK PROXY - PAKIET TESTOW
echo ================================================================
echo.
echo [1] Testy jednostkowe Pancernej Tarczy (tests/test_pacing_shield.py)
echo [2] Kompleksowy audyt bezpieczenstwa (tests/test_security_audit.py)
echo [3] Uruchom wszystkie testy (1 + 2)
echo [4] Wyjscie
echo.
choice /c 1234 /n /m "Wybierz (1-4): "

if errorlevel 4 goto end
if errorlevel 3 goto all
if errorlevel 2 goto audit
if errorlevel 1 goto pacing

:pacing
echo.
echo [*] Uruchamianie testu Pancernej Tarczy...
.\.venv\Scripts\python.exe -m unittest tests/test_pacing_shield.py
echo.
pause
goto end

:audit
echo.
echo [*] Uruchamianie audytu bezpieczenstwa...
.\.venv\Scripts\python.exe tests/test_security_audit.py
echo.
pause
goto end

:all
echo.
echo [*] 1/2: Testy jednostkowe Pancernej Tarczy...
.\.venv\Scripts\python.exe -m unittest tests/test_pacing_shield.py
echo.
echo [*] 2/2: Audyt bezpieczenstwa...
.\.venv\Scripts\python.exe tests/test_security_audit.py
echo.
pause
goto end

:end
exit /b 0
