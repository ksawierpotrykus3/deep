"""Automatyczna logowarka do kont DeepSeek (bez recznego wpisywania).

Uzycie:
    python auto_login.py 2 3 4      # zaloguj konkretne sloty
    python auto_login.py --all      # zaloguj wszystkie sloty z data/accounts.json
    python auto_login.py --expired  # zaloguj tylko sloty z niewaznym tokenem

Konta i hasla sa w data/accounts.json. Wynik zapisywany jest do session_<slot>.json.
"""
import sys
import time
import json
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions
from curl_cffi import requests
from cloud_shield import cloud_shield

ROOT = Path(__file__).parent
ACCOUNTS_FILE = ROOT / "data" / "accounts.json"
API_CURRENT_USER = "https://chat.deepseek.com/api/v0/users/current"

SIGN_IN_URL = "https://chat.deepseek.com/sign_in"
EMAIL_SELECTOR = "css:input[type=text]"
PASSWORD_SELECTOR = "css:input[type=password]"
SUBMIT_SELECTOR = "xpath://div[@role='button'][normalize-space(.)='Zaloguj się']"

LOGIN_TIMEOUT = 90
POLL_INTERVAL = 1.0


def load_accounts() -> dict:
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    default_pw = data.get("default_password", "")
    accounts = {}
    for acc in data.get("accounts", []):
        accounts[int(acc["slot"])] = {
            "email": acc["email"],
            "password": acc.get("password") or default_pw,
        }
    return accounts


def get_token(page: ChromiumPage):
    try:
        return page.run_js(
            "try { const t = JSON.parse(localStorage.getItem('userToken')); return t && t.value ? t.value : null } catch(e) { return null }"
        )
    except Exception:
        return None


def verify_token(token: str, cookies: dict, user_agent: str, slot: int = 0):
    """Sprawdza token przez oficjalne API. Zwraca (ok, identyfikator_klienta)."""
    try:
        proxy_kwargs = cloud_shield.get_proxy_kwargs(slot)
        r = requests.get(
            API_CURRENT_USER,
            headers={"authorization": f"Bearer {token}", "user-agent": user_agent},
            cookies=cookies,
            impersonate="chrome120",
            timeout=15,
            **proxy_kwargs,
        )
        res = r.json()
        if res.get("code") == 0:
            biz = res.get("data", {}).get("biz_data", {})
            ident = biz.get("email") or biz.get("mobile") or "?"
            chat = biz.get("chat", {})
            is_muted = chat.get("is_muted", 0)
            mute_until = chat.get("mute_until")
            if is_muted == 1:
                import datetime
                until_str = datetime.datetime.fromtimestamp(mute_until).strftime("%Y-%m-%d %H:%M:%S") if mute_until else "?"
                return True, f"{ident} (UWAGA: ZMUTOWANY do {until_str})"
            return True, ident
        return False, f"code={res.get('code')} {res.get('msg', '')}"
    except Exception as e:
        return False, f"blad API: {e}"


def is_slot_expired(slot: int) -> bool:
    """Sprawdza, czy plik sesji danego slotu brakuje lub token w API jest niewazny/wygasly."""
    session_file = ROOT / f"session_{slot}.json"
    if not session_file.exists():
        return True
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        token = data.get("auth_token")
        if not token:
            return True
        ok, _ = verify_token(token, data.get("cookies", {}), data.get("user_agent", "Mozilla/5.0"), slot=slot)
        return not ok
    except Exception:
        return True


def dismiss_optional_captcha(page: ChromiumPage) -> None:
    """Jesli na stronie jest hCaptcha/turnstile to nie da sie jej obejsc automatycznie.
    Wykrywamy i informujemy - w takim wypadku trzeba ja rozwiazac recznie."""
    try:
        for iframe in page.eles("tag:iframe"):
            src = (iframe.attrs.get("src") or "").lower()
            if "hcaptcha" in src or "turnstile" in src or "recaptcha" in src:
                print(f"    [!] Wykryto captcha ({src[:60]}...)")
                print("    [!] Rozwiaz captcha w oknie Chrome - skrypt poczeka i dokonczy sam.")
                return
    except Exception:
        pass


def accept_terms_if_present(page: ChromiumPage) -> None:
    try:
        for box in page.eles("css:input[type=checkbox]"):
            try:
                if not box.states.is_checked:
                    box.click()
                    time.sleep(0.3)
            except Exception:
                pass
    except Exception:
        pass


def login_slot(slot: int, email: str, password: str) -> bool:
    print("=" * 62)
    print(f"   AUTO-LOGOWANIE SLOTU {slot}  ->  {email}")
    print("=" * 62)

    data_dir = ROOT / ".chrome_slot" / f"slot_{slot}"
    data_dir.mkdir(parents=True, exist_ok=True)

    opt = ChromiumOptions()
    opt.set_user_data_path(str(data_dir))
    opt.set_argument("--no-first-run")
    opt.set_argument("--no-default-browser-check")
    opt.set_argument("--disable-blink-features=AutomationControlled")
    opt.set_argument("--disable-features=IsolateOrigins,site-per-process")
    opt.set_argument("--disable-infobars")
    opt.set_argument("--window-size=1280,900")
    opt.auto_port()

    proxy_url = cloud_shield.get_proxy(slot)
    if proxy_url:
        opt.set_argument(f"--proxy-server={proxy_url}")
        print(f"[SHIELD] Uruchamiam Chrome przez proxy: {proxy_url}", flush=True)

    print("[1/5] Uruchamiam Chrome...")
    page = ChromiumPage(opt)

    try:
        print("[2/5] Otwieram strone logowania...")
        page.get(SIGN_IN_URL)

        # czekaj na formularz (AWS WAF / Cloudflare moga chwilowo blokowac)
        form_ready = False
        for _ in range(30):
            time.sleep(1)
            try:
                if page.ele(EMAIL_SELECTOR, timeout=0.5) and page.ele(PASSWORD_SELECTOR, timeout=0.5):
                    form_ready = True
                    break
            except Exception:
                pass
            # jesli juz jestesmy zalogowani
            if get_token(page):
                break

        token_before = get_token(page)

        if not form_ready and token_before:
            print("    Konto juz zalogowane w tej przegladarce - odswiezam sesje.")

        if form_ready:
            print("[3/5] Wypelniam formularz (e-mail + haslo)...")
            accept_terms_if_present(page)

            email_box = page.ele(EMAIL_SELECTOR, timeout=10)
            email_box.clear()
            email_box.input(email)

            pw_box = page.ele(PASSWORD_SELECTOR, timeout=10)
            pw_box.clear()
            pw_box.input(password)

            time.sleep(0.4)
            accept_terms_if_present(page)

            print("    Klikam 'Zaloguj sie'...")
            submit = page.ele(SUBMIT_SELECTOR, timeout=10)
            submit.click()

            dismiss_optional_captcha(page)
        else:
            print("[3/5] Formularz niedostepny - sprawdzam czy sesja juz istnieje.")

        print("[4/5] Czekam na token...")
        token = None
        deadline = time.time() + LOGIN_TIMEOUT
        while time.time() < deadline:
            token = get_token(page)
            if token and token != token_before and len(token) > 10:
                break
            if token and token == token_before and form_ready:
                token = None  # stary token - jeszcze nie zalogowano
            time.sleep(POLL_INTERVAL)

        if not token:
            print("[-] NIE UDALO SIE: brak nowego tokenu w czasie oczekiwania.")
            try:
                print("    URL:", page.url)
                body = page.ele("tag:body").text
                interesting = [l for l in body.splitlines() if l.strip()][:25]
                print("    Widoczny tekst strony:")
                for line in interesting:
                    print("      |", line)
            except Exception:
                pass
            return False

        cookies = {c["name"]: c["value"] for c in page.cookies()}
        user_agent = page.user_agent

        print("[5/5] Weryfikuje token przez API DeepSeek...")
        ok, ident = verify_token(token, cookies, user_agent, slot=slot)
        if not ok:
            print(f"[-] Token zapisany, ale API go odrzuca: {ident}")
            return False

        session_file = ROOT / f"session_{slot}.json"
        session_data = {
            "auth_token": token,
            "cookies": cookies,
            "user_agent": user_agent,
            "email": email or ident,
            "created_at": time.time(),
            "last_validated_at": time.time(),
        }
        session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")

        print(f"[+] SUKCES! Zalogowano {ident} -> {session_file.name}")
        return True
    finally:
        try:
            page.quit()
        except Exception:
            pass


def login_expired_slots() -> dict[int, bool]:
    """Wyszukuje wygasle sloty i loguje je automatycznie po kolei."""
    accounts = load_accounts()
    expired = [s for s in sorted(accounts) if is_slot_expired(s)]
    if not expired:
        print("[AUTO-LOGIN] Wszystkie sloty maja wazne sesje (brak wygaslych).")
        return {}
    print(f"[AUTO-LOGIN] Wykryto wygasle sloty wymagajace odnowienia: {expired}")
    results = {}
    for slot in expired:
        acc = accounts[slot]
        try:
            results[slot] = login_slot(slot, acc["email"], acc["password"])
        except Exception as e:
            print(f"[-] Blad logowania slotu {slot}: {e}")
            results[slot] = False
    return results


def main():
    accounts = load_accounts()

    args = sys.argv[1:]
    if not args or "--all" in args:
        slots = sorted(accounts)
    elif "--expired" in args:
        print("[*] Sprawdzam waznosc tokenow w slotach...")
        slots = [s for s in sorted(accounts) if is_slot_expired(s)]
        if not slots:
            print("[+] Wszystkie konta maja aktywne sesje! Zadne konto nie wymaga logowania.")
            return
        print(f"[!] Wykryto wygasle sloty: {slots}")
    else:
        slots = []
        for a in args:
            try:
                slots.append(int(a))
            except ValueError:
                print(f"Pomijam nieprawidlowy argument: {a}")

    print(f"\nDo zalogowania: {slots}\n")

    results = {}
    for slot in slots:
        acc = accounts.get(slot)
        if not acc:
            print(f"[-] Brak konta dla slotu {slot} w data/accounts.json")
            results[slot] = False
            continue
        try:
            results[slot] = login_slot(slot, acc["email"], acc["password"])
        except Exception as e:
            print(f"[-] Blad slotu {slot}: {e}")
            results[slot] = False

    print("\n" + "=" * 62)
    print("   PODSUMOWANIE")
    print("=" * 62)
    for slot in slots:
        acc = accounts.get(slot, {})
        status = "OK" if results.get(slot) else "NIEUDANE"
        print(f"  Slot {slot}: [{status}] {acc.get('email', '?')}")
    print("=" * 62)


if __name__ == "__main__":
    main()
