import os
import json
import socket
import time
from pathlib import Path
from typing import Optional, Dict, Any

PROXY_CONFIG_FILE = Path(__file__).parent / "data" / "proxy_config.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_detect_warp": True,
    "warp_socks5_url": "socks5h://127.0.0.1:40000",
    "warp_port": 40000,
    "custom_proxy": None,
    "account_proxies": {},
    "fallback_to_direct": True,
}

class CloudShield:
    """
    Automatyczny menedzer Cloud / Proxy dla DeepSeek Proxy.
    Chroni IP i umozliwia bezwysilkowe (effortless) korzystanie z Cloudflare WARP
    oraz niestandardowych serwerow proxy z automatycznym fallbackiem.
    """

    def __init__(self, config_path: Path = PROXY_CONFIG_FILE):
        self.config_path = config_path
        self._config_cache: Dict[str, Any] = {}
        self._config_mtime: float = 0.0
        self._last_probe_time: float = 0.0
        self._warp_alive: bool = False
        self._proxy_unhealthy_until: float = 0.0
        self._last_status_log_time: float = 0.0
        self._last_mode_logged: Optional[str] = None
        self._ensure_config_exists()
        self._load_config()

    def _ensure_config_exists(self) -> None:
        try:
            if not self.config_path.parent.exists():
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.config_path.exists():
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception as e:
            print(f"[CLOUD SHIELD] Blad tworzenia {self.config_path}: {e}", flush=True)

    def _load_config(self) -> Dict[str, Any]:
        try:
            if self.config_path.exists():
                mtime = self.config_path.stat().st_mtime
                if mtime != self._config_mtime:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    cfg = DEFAULT_CONFIG.copy()
                    cfg.update(loaded)
                    self._config_cache = cfg
                    self._config_mtime = mtime
            else:
                self._config_cache = DEFAULT_CONFIG.copy()
        except Exception as e:
            if not self._config_cache:
                self._config_cache = DEFAULT_CONFIG.copy()
        return self._config_cache

    def _is_port_open(self, host: str, port: int, timeout: float = 0.2) -> bool:
        """Szybki test czy port lokalny slucha (np. WARP SOCKS5 40000)."""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            res = s.connect_ex((host, port))
            return res == 0
        except Exception:
            return False
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    def _probe_warp(self) -> bool:
        """Sprawdza stan Cloudflare WARP (port 40000 lub 1080) z cache 5s."""
        now = time.time()
        if now - self._last_probe_time < 5.0:
            return self._warp_alive

        cfg = self._load_config()
        port = int(cfg.get("warp_port", 40000))
        is_open = self._is_port_open("127.0.0.1", port)
        if not is_open and port != 1080:
            # Sprawdz alternatywny standardowy port socks5
            is_open = self._is_port_open("127.0.0.1", 1080)

        self._warp_alive = is_open
        self._last_probe_time = now
        return self._warp_alive

    def mark_proxy_unhealthy(self, reason: str, cooldown_s: float = 30.0) -> None:
        """Tymczasowo deaktywuje proxy po powaznym bledzie sieciowym."""
        now = time.time()
        self._proxy_unhealthy_until = now + cooldown_s
        print(f"[CLOUD SHIELD] Proxy oznaczone jako nieaktywne na {cooldown_s}s (powod: {reason}). Bezpieczny fallback na bezposrednie polaczenie.", flush=True)

    def is_healthy(self) -> bool:
        return time.time() >= self._proxy_unhealthy_until

    def get_proxy(self, account_idx: Optional[int] = None) -> Optional[str]:
        """
        Zwraca URL proxy (np. 'socks5://127.0.0.1:40000') lub None dla bezposredniego.
        Kolejnosc priorytetow:
        1. Dedykowany proxy konta (account_proxies w configu)
        2. Niestandardowy custom_proxy w configu
        3. Cloudflare WARP (jesli wlaczony i port 40000 odpowiada)
        4. Zmienne srodowiskowe (HTTPS_PROXY / HTTP_PROXY)
        5. None (bezposrednie z Pancerna Tarcza 2.0)
        """
        cfg = self._load_config()
        if not cfg.get("enabled", True):
            return None

        # Jesli w trakcie cooldownu bledu i wlaczony fallback -> bezposrednie
        if not self.is_healthy():
            if cfg.get("fallback_to_direct", True):
                return None

        # 1. Dedykowany proxy konta
        if account_idx is not None:
            acc_proxies = cfg.get("account_proxies", {})
            acc_proxy = acc_proxies.get(str(account_idx)) or acc_proxies.get(account_idx)
            if acc_proxy:
                self._log_mode_once(f"DEDYKOWANY PROXY (Slot {account_idx}) -> {acc_proxy}")
                return acc_proxy

        # 2. Niestandardowy custom_proxy
        custom = cfg.get("custom_proxy")
        if custom and str(custom).strip():
            self._log_mode_once(f"CUSTOM PROXY -> {custom}")
            return str(custom).strip()

        # 3. Cloudflare WARP (Auto-detect)
        if cfg.get("auto_detect_warp", True):
            if self._probe_warp():
                warp_url = cfg.get("warp_socks5_url", "socks5://127.0.0.1:40000")
                self._log_mode_once(f"CLOUDFLARE WARP (Auto-detected SOCKS5) -> {warp_url}")
                return warp_url

        # 4. Zmienne srodowiskowe
        env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("ALL_PROXY")
        if env_proxy and str(env_proxy).strip():
            self._log_mode_once(f"ENV PROXY -> {env_proxy}")
            return str(env_proxy).strip()

        # 5. Bezposrednie polaczenie
        self._log_mode_once("DIRECT (Pancerna Tarcza 2.0, Global IP Pacer)")
        return None

    def _log_mode_once(self, mode_str: str) -> None:
        now = time.time()
        if mode_str != self._last_mode_logged or (now - self._last_status_log_time > 300.0):
            print(f"[CLOUD SHIELD] Aktualny tryb routingu: {mode_str}", flush=True)
            self._last_mode_logged = mode_str
            self._last_status_log_time = now

    def get_proxy_kwargs(self, account_idx: Optional[int] = None) -> Dict[str, Any]:
        """Zwraca slownik argumentow dla curl_cffi.requests.post/get."""
        proxy_url = self.get_proxy(account_idx)
        if proxy_url:
            return {"proxy": proxy_url}
        return {}

    def get_requests_proxies(self, account_idx: Optional[int] = None) -> Optional[Dict[str, str]]:
        """Zwraca slownik proxies dla standardowej biblioteki requests (np. {'http': ..., 'https': ...})."""
        proxy_url = self.get_proxy(account_idx)
        if proxy_url:
            return {"http": proxy_url, "https": proxy_url}
        return None

    def get_status(self) -> Dict[str, Any]:
        """Zwraca status do API /slots lub /proxy/status."""
        cfg = self._load_config()
        warp_up = self._probe_warp()
        active_proxy = self.get_proxy()
        
        mode = "direct"
        if active_proxy:
            if "127.0.0.1:40000" in active_proxy or "warp" in active_proxy.lower():
                mode = "cloudflare_warp"
            else:
                mode = "custom_or_env"

        return {
            "shield_enabled": cfg.get("enabled", True),
            "routing_mode": mode,
            "active_proxy": active_proxy or "DIRECT",
            "cloudflare_warp_detected": warp_up,
            "is_healthy": self.is_healthy(),
            "auto_detect_warp": cfg.get("auto_detect_warp", True),
            "fallback_to_direct": cfg.get("fallback_to_direct", True),
        }

# Globalna instancja dostepna dla calego projektu
cloud_shield = CloudShield()
