@echo off
chcp 65001 >nul
title Proxy Mode Switcher
cd /d "%~dp0"

:menu
cls
echo ============================================
echo     PROXY DEEPSEEK - PRZELACZNIK TRYBU
echo ============================================
echo.
echo Wybierz tryb:
echo.
echo   [1] AUTO    - Manager (platny) — Kodowanie & Dev ^(zalecane^)
echo   [2] FREE    - Asystent (darmowy) — Wszystko poza kodem
echo   [3] BIEDNY  - WSZYSTKO DARMOWY web chat (kodowanie tez)
echo   [4] SPRAWDZ aktualny tryb
echo   [5] WYJSCIE
echo.
choice /c 12345 /n /m "Wybierz (1-5): "

if errorlevel 5 goto end
if errorlevel 4 goto check
if errorlevel 3 goto biedny
if errorlevel 2 goto free_mode
if errorlevel 1 goto auto

:auto
echo.
echo Przelaczanie na AUTO...
curl -s -X POST "http://localhost:4570/v1/mode?mode=auto" 2>nul
if errorlevel 1 (
    echo [BLAD] Proxy nie odpowiada. Czy serwer dziala na http://localhost:4570 ?
) else (
    echo [OK] Tryb AUTO - Manager (platny) + subagenci (darmowi).
)
echo.
pause
goto menu

:free_mode
echo.
echo Przelaczanie na FREE...
curl -s -X POST "http://localhost:4570/v1/mode?mode=free" 2>nul
if errorlevel 1 (
    echo [BLAD] Proxy nie odpowiada. Czy serwer dziala na http://localhost:4570 ?
) else (
    echo [OK] Tryb FREE - Asystent ogolny, calkowicie darmowy web chat.
)
echo.
pause
goto menu

:biedny
echo.
echo Przelaczanie na BIEDNY...
curl -s -X POST "http://localhost:4570/v1/mode?mode=biedny" 2>nul
if errorlevel 1 (
    echo [BLAD] Proxy nie odpowiada. Czy serwer dziala na http://localhost:4570 ?
) else (
    echo [OK] Tryb BIEDNY - wszystko przez darmowy web chat.
)
echo.
pause
goto menu

:check
echo.
echo Sprawdzanie trybu...
curl -s "http://localhost:4570/v1/mode" 2>nul
echo.
pause
goto menu

:end
