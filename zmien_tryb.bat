@echo off
chcp 65001 >nul
title Proxy Mode Switcher
cd /d "%~dp0"

:menu
cls
echo ================================================================
echo             PROXY DEEPSEEK - PRZELACZNIK TRYBU
echo ================================================================
echo.
echo Wybierz tryb:
echo.
echo   [1] FREE (100%% Darmowy Web Chat - wszystkie zapytania przez web chat)
echo   [2] AUTO (Hybrydowy: Glowny agent -> API, Subagenci -> darmowy web chat)
echo   [3] FREE_FIRST (Web First: Web chat, fallback do API przy dlugim kontekscie)
echo   [4] BIEDNY (Darmowy Web Chat z promptem optymalizacyjnym Managera)
echo   [5] SPRAWDZ aktualny tryb
echo   [6] WYJSCIE
echo.
echo ================================================================
choice /c 123456 /n /m "Wybierz (1-6): "

if errorlevel 6 goto end
if errorlevel 5 goto check
if errorlevel 4 goto mode_biedny
if errorlevel 3 goto mode_free_first
if errorlevel 2 goto mode_auto
if errorlevel 1 goto mode_free

:mode_free
echo.
echo Przelaczanie na tryb FREE (100%% Darmowy Web Chat)...
curl -s -X POST "http://localhost:4570/v1/mode?mode=free" 2>nul
goto result

:mode_auto
echo.
echo Przelaczanie na tryb AUTO (Hybrydowy)...
curl -s -X POST "http://localhost:4570/v1/mode?mode=auto" 2>nul
goto result

:mode_free_first
echo.
echo Przelaczanie na tryb FREE_FIRST (Web First + Fallback API)...
curl -s -X POST "http://localhost:4570/v1/mode?mode=free_first" 2>nul
goto result

:mode_biedny
echo.
echo Przelaczanie na tryb BIEDNY (Darmowy Manager)...
curl -s -X POST "http://localhost:4570/v1/mode?mode=biedny" 2>nul
goto result

:result
if errorlevel 1 (
    echo.
    echo [BLAD] Proxy nie odpowiada. Czy serwer dziala na http://localhost:4570 ?
) else (
    echo.
    echo [OK] Tryb zostal pomyslnie zmieniony!
)
echo.
pause
goto menu

:check
echo.
echo Aktualny stan proxy:
echo ----------------------------------------------------------------
curl -s "http://localhost:4570/v1/mode" 2>nul
if errorlevel 1 (
    echo [BLAD] Proxy nie odpowiada.
)
echo.
echo ----------------------------------------------------------------
echo.
pause
goto menu

:end
exit /b 0
