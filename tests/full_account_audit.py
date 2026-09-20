import sys
import json
import datetime
from pathlib import Path
import curl_cffi.requests as requests

sys.stdout.reconfigure(encoding="utf-8")

with open("data/accounts.json", encoding="utf-8") as f:
    acc_emails = {a["slot"]: a["email"] for a in json.load(f)["accounts"]}

now = datetime.datetime.now()
print(f"=== PEŁNY AUDYT STANU WSZYSTKICH 14 KONT (Data: {now.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")

active_count = 0
muted_count = 0
expired_count = 0

for idx in range(14):
    p = Path(f"session_{idx}.json")
    email = acc_emails.get(idx, "unknown")
    if not p.exists():
        print(f"Slot {idx:2d} | {email:<30} | BRAK PLIKU SESJI")
        continue
    try:
        sdata = json.loads(p.read_text(encoding="utf-8"))
        token = sdata.get("auth_token")
        r = requests.get(
            "https://chat.deepseek.com/api/v0/users/current",
            headers={"authorization": f"Bearer {token}"},
            impersonate="chrome120",
            timeout=10
        )
        data = r.json()
        code = data.get("code")
        msg = data.get("msg", "")
        biz = data.get("data") or {}
        biz_data = biz.get("biz_data") or {}
        chat = biz_data.get("chat") or {}
        is_muted = chat.get("is_muted", 0)
        mute_until = chat.get("mute_until")

        if is_muted == 1 and mute_until:
            muted_count += 1
            until_dt = datetime.datetime.fromtimestamp(mute_until)
            diff_h = (until_dt - now).total_seconds() / 3600
            if diff_h <= 6:
                urgency = ">>> ODBLOKOWANIE DZISIAJ POPOLUDNIU! <<<"
            elif diff_h <= 24:
                urgency = "ODBLOKOWANIE W CIAGU 24H"
            else:
                urgency = f"kara {diff_h/24:.1f} dni"
            print(f"Slot {idx:2d} | {email:<30} | [ZBANOWANE/MUTE] do {until_dt.strftime('%Y-%m-%d %H:%M:%S')} (za {diff_h:.1f}h) | {urgency}")
        elif code == 0:
            active_count += 1
            print(f"Slot {idx:2d} | {email:<30} | [AKTYWNE - 100% OK] GOTOWE DO PRACY")
        elif code == 40003:
            expired_count += 1
            print(f"Slot {idx:2d} | {email:<30} | [WYGASLY TOKEN] Wymaga logowania")
        else:
            print(f"Slot {idx:2d} | {email:<30} | KOD {code}: {msg}")
    except Exception as e:
        print(f"Slot {idx:2d} | {email:<30} | BLAD: {e}")

print(f"\nPodsumowanie: {active_count} AKTYWNYCH | {muted_count} ZBANOWANYCH | {expired_count} WYGASŁYCH")
