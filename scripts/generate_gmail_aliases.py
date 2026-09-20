"""Generator aliasów Gmail z kropkami (dot trick) dla kont DeepSeek.
W Gmailu kropki w loginie są ignorowane (wszystkie maile trafiają do jednej skrzynki),
natomiast dla DeepSeek każdy wariant z kropkami to unikalny, odrębny użytkownik!
"""
import json
import itertools
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_FILE = ROOT / "data" / "accounts.json"


def generate_dot_aliases(base_username: str, max_count: int = 100) -> list[str]:
    """Generuje unikalne warianty z kropkami dla podanego base_username (np. 'pawelkowalkp').
    Username o długości n ma n-1 miejsc na kropki (2^(n-1) kombinacji).
    """
    n = len(base_username)
    if n <= 1:
        return [base_username]
    
    # Miejsca na wstawienie kropki: indeksy od 1 do n-1
    # Generujemy od 1 kropki, potem 2 kropki, itd. aby aliasy wyglądały naturalnie
    results = []
    positions = list(range(1, n))
    
    # 0 kropek (oryginał)
    results.append(base_username)
    
    # 1 kropka, 2 kropki, 3 kropki, etc.
    for k in range(1, min(len(positions) + 1, 5)):
        for comb in itertools.combinations(positions, k):
            chars = list(base_username)
            # wstawiamy od końca, aby indeksy się nie rozjechały
            for pos in sorted(comb, reverse=True):
                chars.insert(pos, ".")
            results.append("".join(chars))
            if len(results) >= max_count:
                return results
                
    return results


def main():
    base_user = "pawelkowalkp"
    domain = "@gmail.com"
    
    existing_emails = set()
    max_slot = -1
    if ACCOUNTS_FILE.exists():
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        for acc in data.get("accounts", []):
            existing_emails.add(acc["email"].lower())
            if acc["slot"] > max_slot:
                max_slot = acc["slot"]
    
    aliases = generate_dot_aliases(base_user, max_count=200)
    new_aliases = [f"{a}{domain}" for a in aliases if f"{a}{domain}".lower() not in existing_emails]
    
    print(f"=== GENERATOR ALIASÓW GMAIL DLA: {base_user}{domain} ===")
    print(f"Liczba wygenerowanych unikalnych aliasów: {len(aliases)}")
    print(f"Już zarejestrowanych w accounts.json: {len(aliases) - len(new_aliases)}")
    print(f"Dostępnych nowych czystych aliasów: {len(new_aliases)}")
    print("\nPrzykładowe pierwsze 20 nowych aliasów do wykorzystania:")
    for i, email in enumerate(new_aliases[:20], 1):
        slot_candidate = max_slot + i
        print(f"  [Slot {slot_candidate:02d}] {email}")
        
    # Zapisz pełną pulę do data/available_aliases.json
    out_file = ROOT / "data" / "available_aliases.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "base_email": f"{base_user}{domain}",
        "total_available": len(new_aliases),
        "aliases": new_aliases
    }
    out_file.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
    print(f"\n[+] Zapisano pełną listę {len(new_aliases)} aliasów do: {out_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
