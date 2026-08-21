import sys, os, time, json, shutil
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

def direct_login(slot: int = 0):
    print("=" * 60)
    print(f"   LOGOWANIE DO SLOTU {slot} (DEEPSEEK PROXY)")
    print("=" * 60)
    
    root_dir = Path(__file__).parent
    data_dir = root_dir / ".chrome_slot" / f"slot_{slot}"
    if data_dir.exists():
        try:
            shutil.rmtree(data_dir)
            print(f"[+] Wyczyszczono profil tymczasowy: {data_dir.name}")
        except Exception:
            pass
    data_dir.mkdir(parents=True, exist_ok=True)
    
    chrome_opt = ChromiumOptions()
    chrome_opt.set_user_data_path(str(data_dir))
    chrome_opt.set_argument("--no-first-run")
    chrome_opt.set_argument("--no-default-browser-check")
    chrome_opt.set_argument("--disable-blink-features=AutomationControlled")
    chrome_opt.set_argument("--disable-features=IsolateOrigins,site-per-process")
    chrome_opt.set_argument("--disable-infobars")
    chrome_opt.set_argument("--window-size=1280,800")
    chrome_opt.auto_port()
    
    print("\n[1/3] Uruchamianie przegladarki Chrome...")
    driver = ChromiumPage(chrome_opt)
    
    try:
        print("[2/3] Otwieranie strony logowania DeepSeek...")
        driver.get("https://chat.deepseek.com/sign_in")
        
        try:
            from CloudflareBypasser import CloudflareBypasser
            cf = CloudflareBypasser(driver, max_retries=10, log=False)
            cf.bypass()
        except Exception:
            pass
            
        print("\n" + "#" * 60)
        print(">>> PRZEJDZ DO OTWARTEGO OKNA CHROME I ZALOGUJ SIE <<<")
        print(">>> NIE ZAMYKAJ OKNA - ZAMKNIE SIE SAMO PO ZALOGOWANIU! <<<")
        print("#" * 60 + "\n")
        
        token = None
        while True:
            try:
                token = driver.run_js("try { return JSON.parse(localStorage.getItem('userToken')).value } catch(e) { return null }")
                if token and isinstance(token, str) and len(token) > 10:
                    print(f"\n[+] Wykryto poprawny token uzytkownika!")
                    break
                    
                url = driver.url
                if "/a/chat" in url or (url.rstrip("/") == "https://chat.deepseek.com" and "/sign_in" not in url):
                    time.sleep(1)
                    try:
                        token = driver.run_js("try { return JSON.parse(localStorage.getItem('userToken')).value } catch(e) { return null }")
                    except Exception:
                        pass
                    if token and isinstance(token, str) and len(token) > 10:
                        break
            except Exception:
                pass
            time.sleep(1)
            
        cookies = {c["name"]: c["value"] for c in driver.cookies()}
        user_agent = driver.user_agent
        driver.quit()
        
        session_file = root_dir / f"session_{slot}.json"
        session_data = {
            "auth_token": token,
            "cookies": cookies,
            "user_agent": user_agent,
            "created_at": time.time(),
            "last_validated_at": time.time(),
        }
        session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
        
        print("\n" + "=" * 60)
        print(f"[3/3] SUKCES! Zalogowano slot {slot}.")
        print(f"      Zapisano plik: {session_file.name}")
        print("=" * 60 + "\n")
        return True
    except Exception as e:
        print(f"\n[-] Blad logowania: {e}")
        try:
            driver.quit()
        except Exception:
            pass
        return False

if __name__ == "__main__":
    slot_num = 0
    if len(sys.argv) > 1:
        try:
            slot_num = int(sys.argv[1])
        except ValueError:
            pass
    direct_login(slot_num)
