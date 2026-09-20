import sys, time, json, re
from pathlib import Path
from curl_cffi import requests
from cloud_shield import cloud_shield

base_dir = Path(__file__).parent
disabled_file = base_dir / "data" / "disabled_slots.txt"

disabled_slots = set()
if disabled_file.exists():
    try:
        for line in disabled_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                for p in line.replace(",", " ").split():
                    try:
                        disabled_slots.add(int(p))
                    except ValueError:
                        pass
    except Exception:
        pass

# Check if specific slot was requested: python check_slots.py <slot>
single_slot = None
if len(sys.argv) > 1:
    try:
        single_slot = int(sys.argv[1])
    except ValueError:
        pass

proxy_info = cloud_shield.get_status()
routing = proxy_info.get("active_proxy", "DIRECT")

print("===================================================")
print("     STATUS TOKENOW W SLOTACH DEEPSEEK")
print(f"     Routing: {routing}")
if single_slot is not None:
    print(f"     Sprawdzany slot: {single_slot}")
else:
    print(f"     Wylaczone sloty: {sorted(disabled_slots)}")
print("===================================================")

if single_slot is not None:
    slots_to_check = [single_slot]
else:
    # Find all session_*.json files
    session_files = sorted(base_dir.glob("session_*.json"))
    all_slots = set(disabled_slots)
    for f in session_files:
        m = re.search(r"session_(\d+)\.json", f.name)
        if m:
            all_slots.add(int(m.group(1)))
    slots_to_check = sorted(all_slots)

for idx, s in enumerate(slots_to_check):
    if idx > 0:
        time.sleep(1.2)  # Anti-spam delay between requests

    p = base_dir / f"session_{s}.json"
    is_dis = s in disabled_slots
    dis_tag = " [IGNOROWANY/WYLACZONY]" if is_dis else ""

    if not p.exists():
        print(f"Slot {s}: [BRAK PLIKU]{dis_tag}")
        continue
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        tok = d.get("auth_token", "")
        cookies = d.get("cookies", {})
        ua = d.get("user_agent", "Mozilla/5.0")
        proxy_kwargs = cloud_shield.get_proxy_kwargs(s)
        r = requests.get(
            "https://chat.deepseek.com/api/v0/users/current",
            headers={"authorization": f"Bearer {tok}", "user-agent": ua},
            cookies=cookies,
            impersonate="chrome120",
            timeout=12,
            **proxy_kwargs,
        )
        res = r.json()
        code = res.get("code")
        if code == 0:
            user = res.get("data", {}).get("biz_data", {})
            ident = user.get("email") or user.get("mobile") or "Zalogowano"
            chat = user.get("chat", {})
            is_muted = chat.get("is_muted", 0)
            mute_until = chat.get("mute_until")
            if is_muted == 1:
                import datetime
                until_str = datetime.datetime.fromtimestamp(mute_until).strftime("%Y-%m-%d %H:%M:%S") if mute_until else "nieznany"
                status = f"ZBANOWANY / ZMUTOWANY do {until_str}"
                print(f"Slot {s}: [{status}]{dis_tag} {ident}")
            else:
                status = "GOTOWY DO PRACY (OK)" if not is_dis else "AKTYWNY ALE WYLACZONY W KONFIGURACJI"
                print(f"Slot {s}: [{status}]{dis_tag} {ident}")
        elif code == 40003:
            print(f"Slot {s}: [WYGASLY TOKEN SESJI (40003)]{dis_tag} -> wymaga zalogowania (login_slot.bat {s})")
        else:
            print(f"Slot {s}: [KOD {code}]{dis_tag} {res.get('msg', 'Nieznany blad')}")
    except Exception as e:
        print(f"Slot {s}: [BLAD POLACZENIA]{dis_tag} {e}")

print("===================================================")
