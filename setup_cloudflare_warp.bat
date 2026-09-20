@echo off
chcp 65001 >nul
title Cloudflare WARP - Setup dla DeepSeek Proxy
cls
echo =====================================================================
echo       CLOUDFLARE WARP - AUTOMATYCZNA TARCZA DLA DEEPSEEK PROXY
echo =====================================================================
echo.
echo Ten skrypt konfiguruje Cloudflare WARP w trybie PROXY (SOCKS5 40000).
echo W tym trybie:
echo   - Twoj zwykly internet, gry i przegladarka dzialaja BEZ ZMIAN.
echo   - Ruch DeepSeek Proxy automatycznie leci przez serwery Cloudflare.
echo   - Twoje lokalne IP jest w 100%% ukryte przed DeepSeekiem.
echo.

set WARP_CLI="C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"

if not exist %WARP_CLI% (
    echo [1/3] Cloudflare WARP nie jest jeszcze zainstalowany.
    echo Instalowanie Cloudflare WARP przez winget...
    winget install --id Cloudflare.Warp -e --accept-package-agreements --accept-source-agreements
    if not exist %WARP_CLI% (
        echo.
        echo [INFO] Jesli instalator wymagal potwierdzenia uprawnien Administratora (UAC),
        echo dokoncz instalacje na ekranie lub pobierz instalator z:
        echo https://one.one.one.one/
        echo Po instalacji uruchom ten plik ponownie.
        pause
        exit /b 1
    )
)

echo [2/3] Konfiguracja WARP w bezpieczny tryb lokalnego Proxy (SOCKS5 40000)...
%WARP_CLI% registration new 2>nul
%WARP_CLI% mode proxy
%WARP_CLI% proxy port 40000

echo [3/3] Aktywacja polaczenia WARP...
%WARP_CLI% connect

echo.
echo =====================================================================
echo [SUKCES] Cloudflare WARP jest gotowy i nasluchuje na 127.0.0.1:40000!
echo DeepSeek Proxy natychmiast automatycznie wykryje polaczenie (zero restartu).
echo =====================================================================
echo.
pause
