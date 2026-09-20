"""Półautomatyczny asystent rejestracji nowych kont DeepSeek z wykorzystaniem aliasów Gmail.

Zasada działania:
1. Bierze kolejny czysty alias z data/available_aliases.json (lub wskazany ręcznie).
2. Uruchamia okno Chrome ze stroną rejestracji DeepSeek (https://chat.deepseek.com/sign_up).
3. Samodzielnie wpisuje alias e-mail i wspólne hasło (KSAWIER43211).
4. Akceptuje regulamin i klika 'Wyślij kod'.
5. Jeśli pojawi się CAPTCHA/suwak - użytkownik przesuwa go myszką w oknie.
6. Kod OTP przychodzi na główną skrzynkę Gmail (pawelkowalkp@gmail.com).
7. Użytkownik podaje kod w konsoli (lub wpisuje w oknie).
8. Skrypt finalizuje rejestrację, przechwytuje userToken, sprawdza sesję przez API,
   zapisuje session_<slot>.json i automatycznie dopisuje konto do data/accounts.json.

Użycie:
    python scripts/register_account.py          # weź kolejny wolny slot i alias
    python scripts/register_account.py 14       # zarejestruj konkretny slot 14
"""
import sys
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from DrissionPage import ChromiumPage, ChromiumOptions
from curl_cffi import requests
from cloud_shield import cloud_shield

ACCOUNTS_FILE = ROOT / "data" / "accounts.json"
ALIASES_FILE = ROOT / "data" / "available_aliases.json"
API_CURRENT_USER = "https://chat.deepseek.com/api/v0/users/current"
SIGN_UP_URL = "https://chat.deepseek.com/sign_up"


def load_accounts_data() -> dict:
    if not ACCOUNTS_FILE.exists():
        return {"default_password": "KSAWIER43211", "accounts": []}
    return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))


def get_next_slot_and_alias(requested_slot: int = None) -> tuple[int, str]:
    acc_data = load_accounts_data()
    existing_slots = {int(a["slot"]) for a in acc_data.get("accounts", [])}
    existing_emails = {a["email"].lower() for a in acc_data.get("accounts", [])}
    
    if requested_slot is not None:
        target_slot = requested_slot
    else:
        target_slot = max(existing_slots) + 1 if existing_slots else 0

    if not ALIASES_FILE.exists():
        raise RuntimeError("Brak pliku data/available_aliases.json! Uruchom najpierw scripts/generate_gmail_aliases.py")

    aliases_data = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    available = [a for a in aliases_data.get("aliases", []) if a.lower() not in existing_emails]
    
    if not available:
        raise RuntimeError("Wszystkie wygenerowane aliasy zostały już zużyte!")

    return target_slot, available[0]


def get_token_from_page(page: ChromiumPage) -> str:
    try:
        return page.run_js(
            "try { const t = JSON.parse(localStorage.getItem('userToken')); return t && t.value ? t.value : null } catch(e) { return null }"
        )
    except Exception:
        return None


def verify_token(token: str, cookies: dict, user_agent: str, slot: int = 0):
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
            return True, ident
        return False, f"code={res.get('code')} {res.get('msg', '')}"
    except Exception as e:
        return False, f"błąd API: {e}"


def register_slot(slot: int, email: str, password: str = "KSAWIER43211"):
    print("=" * 65)
    print(f"   ASYSTENT REJESTRACJI NOWEGO KONTA DEEPSEEK")
    print(f"   Slot:  {slot}")
    print(f"   Email: {email}")
    print(f"   Hasło: {password}")
    print("=" * 65)
    print("\n[Wskazówka] Wiadomość z kodem trafi na Twoją główną skrzynkę pawelkowalkp@gmail.com.")

    data_dir = ROOT / ".chrome_slot" / f"slot_{slot}"
    data_dir.mkdir(parents=True, exist_ok=True)

    opt = ChromiumOptions()
    opt.set_user_data_path(str(data_dir))
    opt.set_argument("--no-first-run")
    opt.set_argument("--no-default-browser-check")
    opt.set_argument("--disable-blink-features=AutomationControlled")
    opt.set_argument("--disable-infobars")
    opt.set_argument("--window-size=1280,900")
    opt.auto_port()

    print("\n[1/6] Uruchamiam okno przeglądarki Chrome...")
    page = ChromiumPage(opt)

    try:
        print("[2/6] Otwieram stronę rejestracji DeepSeek...")
        page.get(SIGN_UP_URL)
        time.sleep(3)

        # Czekaj na formularz
        for _ in range(20):
            if page.ele("css:input[placeholder*='e-mail']", timeout=1):
                break
            time.sleep(1)

        print("[3/6] Wypełniam formularz rejestracji...")
        # Pole e-mail
        email_input = page.ele("css:input[placeholder*='e-mail']") or page.ele("css:input[type=text]")
        if email_input:
            email_input.clear()
            email_input.input(email)
            time.sleep(0.3)

        # Hasła
        pw_inputs = page.eles("css:input[type=password]")
        if len(pw_inputs) >= 2:
            pw_inputs[0].clear()
            pw_inputs[0].input(password)
            time.sleep(0.3)
            pw_inputs[1].clear()
            pw_inputs[1].input(password)
            time.sleep(0.3)
        elif len(pw_inputs) == 1:
            pw_inputs[0].clear()
            pw_inputs[0].input(password)

        # Checkbox regulaminu
        for box in page.eles("css:input[type=checkbox]"):
            try:
                if not box.states.is_checked:
                    box.click()
                    time.sleep(0.3)
            except Exception:
                pass

        print("[4/6] Klikam 'Wyślij kod'...")
        send_btn = page.ele("xpath://div[@role='button'][contains(., 'Wyślij kod') or contains(., 'Send')]")
        if send_btn:
            send_btn.click()
            time.sleep(1.5)
        else:
            print("    [!] Nie znaleziono przycisku 'Wyślij kod' - kliknij go ręcznie w oknie.")

        print("\n" + "#" * 65)
        print("  [!] JEŚLI WIDZISZ PUZZLE / SUWAK CAPTCHA - PRZESUŃ GO W OKNIE CHROME!")
        print("  [!] SPRAWDŹ GMAIL (pawelkowalkp@gmail.com) I ODBIERZ 6-CYFROWY KOD.")
        print("  [!] Kod możesz wpisać bezposrednio w okno Chrome LUB w konsoli.")
        print("#" * 65, flush=True)

        # Czekamy na kod wpisany przez użytkownika w konsoli LUB w oknie Chrome
        code = None
        code_holder = []
        import threading

        def _read_stdin():
            try:
                line = sys.stdin.readline()
                if line:
                    code_holder.append(line.strip())
            except Exception:
                pass

        t = threading.Thread(target=_read_stdin, daemon=True)
        t.start()

        deadline = time.time() + 180  # 3 minuty na kod
        last_log = 0
        while time.time() < deadline:
            # 1. Sprawdz czy user podal w konsoli
            if code_holder:
                c = "".join(filter(str.isdigit, code_holder[0]))
                if len(c) == 6:
                    code = c
                    print(f"\n[+] Odebrano kod z konsoli: {code}", flush=True)
                    break

            # 2. Sprawdz czy w oknie Chrome wpisano kod
            try:
                code_box = page.ele("css:input[placeholder*='Kod']") or page.ele("css:input[maxlength='6']")
                if code_box:
                    val = (code_box.value or "").strip()
                    val_digits = "".join(filter(str.isdigit, val))
                    if len(val_digits) == 6:
                        code = val_digits
                        print(f"\n[+] Wykryto wpisanie kodu w oknie Chrome: {code}", flush=True)
                        break
            except Exception:
                pass

            # 3. Sprawdz czy uzytkownik juz sam sie zarejestrowal i jest zalogowany
            if get_token_from_page(page):
                print("\n[+] Wykryto zalogowanie w oknie Chrome!", flush=True)
                break

            now = time.time()
            if now - last_log >= 10:
                rem = int(deadline - now)
                print(f"[OCZEKIWANIE] Czekam na kod z Gmaila lub rozwiazanie w oknie Chrome (pozostalo {rem}s)...", flush=True)
                last_log = now

            time.sleep(1.0)

        if code:
            try:
                code_box = page.ele("css:input[placeholder*='Kod']") or page.ele("css:input[maxlength='6']")
                if code_box and (code_box.value or "").strip() != code:
                    code_box.clear()
                    code_box.input(code)
                    time.sleep(0.5)
            except Exception:
                pass

            print("\n[5/6] Klikam 'Zarejestruj się'...", flush=True)
            register_btn = page.ele("xpath://div[@role='button'][contains(., 'Zarejestruj') or contains(., 'Sign up')]")
            if register_btn:
                try:
                    register_btn.click()
                except Exception as e:
                    print("    Klikniecie przycisku:", e, flush=True)

        print("[6/6] Czekam na zalogowanie i token sesji (max 60s)...")
        token = None
        deadline = time.time() + 60
        while time.time() < deadline:
            token = get_token_from_page(page)
            if token and len(token) > 10:
                break
            time.sleep(1.0)

        if not token:
            print("[-] BŁĄD: Nie wykryto tokenu sesji. Być może kod był błędny lub wymagana była dodatkowa captcha.")
            return False

        cookies = {c["name"]: c["value"] for c in page.cookies()}
        user_agent = page.user_agent

        ok, ident = verify_token(token, cookies, user_agent, slot=slot)
        if not ok:
            print(f"[-] Token uzyskany, ale API DeepSeek go odrzuciło: {ident}")
            return False

        # Zapisz plik sesji
        session_file = ROOT / f"session_{slot}.json"
        session_data = {
            "auth_token": token,
            "cookies": cookies,
            "user_agent": user_agent,
            "email": email,
            "created_at": time.time(),
            "last_validated_at": time.time(),
        }
        session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")

        # Zapisz w data/accounts.json
        acc_data = load_accounts_data()
        accounts_list = acc_data.setdefault("accounts", [])
        
        # Zastąp jeśli slot już istniał, w przeciwnym razie dopisz
        found = False
        for acc in accounts_list:
            if acc["slot"] == slot:
                acc["email"] = email
                acc["password"] = password
                found = True
                break
        if not found:
            accounts_list.append({"slot": slot, "email": email, "password": password})
            
        accounts_list.sort(key=lambda x: x["slot"])
        ACCOUNTS_FILE.write_text(json.dumps(acc_data, indent=2), encoding="utf-8")

        print("\n" + "=" * 65)
        print(f"[+] SUKCES! Zarejestrowano i aktywowano konto:")
        print(f"    Slot:       {slot}")
        print(f"    Email:      {email}")
        print(f"    Identyfik:  {ident}")
        print(f"    Sesja:      {session_file.name}")
        print(f"    Plik kont:  data/accounts.json zaktualizowany!")
        print("=" * 65)
        return True

    finally:
        try:
            page.quit()
        except Exception:
            pass


def main():
    target_slot = int(sys.argv[1]) if len(sys.argv) > 1 else None
    slot, alias = get_next_slot_and_alias(target_slot)
    register_slot(slot, alias)


if __name__ == "__main__":
    main()
