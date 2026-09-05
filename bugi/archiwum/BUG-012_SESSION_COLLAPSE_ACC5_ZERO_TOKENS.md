# BUG-012: Zacięcie Sesji na Koncie `acc: 5` (4x Z rzędu 0 Tokenów / Zombie Account) i Niedokończona Refaktoryzacja `agent.py`

**Data rejestracji:** 2026-08-31 22:02  
**Komponenty:** `server.py` (Session State Management, Multi-Account Rotator), DeepSeek Web Backend  
**Wpływ na działanie:** WYSOKI (Konto `acc: 5` po serii zapytań zablokowało się na zwracaniu 0 tokenów; proxy nie zrotowało konta, przez co model urwał pracę nad flagą `--auto-approve` w `agent.py`).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu i monitora sesji)

### Incydent 1: Zwis po zapowiedzi modyfikacji kodu
* **Tekst asystenta w Trae:**
  > `Czytam aktualne pliki przed edycją.`  
  > `Poprawiam kod agenta — czystszy, bez magicznych liczb, z flagą --auto-approve do testów end-to-end, i bardziej odpornym dopasowaniem decyzji.`  
  > `Read 1 file > Read agent.py` $\rightarrow$ **Zwis**.
* **Stan plików na dysku:**
  * Utworzono katalog `agent/` z plikami `agent.py`, `requirements.txt`, `README.md`,
  * Utworzono pipeline testowy `data/pipelines/agent_przyklad/stan.json`.
  * Brakuje jedynie zapowiadanej flagi `--auto-approve` i stałych w `agent.py`.

### Incydent 2: Twardy dowód z monitora sesji (`data/sessions_monitor.json`)
```json
[0] session_id: bb94f619 acc: 5 state: done tokens: 0 thinking: 0 age: 4.6s finished: True ok: True
[1] session_id: 87d8919e acc: 5 state: done tokens: 0 thinking: 0 age: 11.3s finished: True ok: True
[2] session_id: 8b08fd84 acc: 5 state: done tokens: 0 thinking: 0 age: 31.6s finished: True ok: True
[3] session_id: 66c26203 acc: 5 state: done tokens: 0 thinking: 0 age: 37.2s finished: True ok: True
```
Aż **cztery kolejne zapytania pod rząd na koncie 5** zakończyły się natychmiastowym zwrotem **0 tokenów**.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Śmierć sesji na koncie `acc: 5`
Po intensywnym transferze danych testowych pipeline'u, sesja webowa DeepSeeka na koncie 5 uległa zablokowaniu (rate-limit / parent desync).

### B. Brak automatycznego Failover w proxy
Proxy widząc, że konto 5 zwraca pusty strumień (0 tokenów), nie zneutralizowało sesji i nie przełączyło zapytania na inne wolne konto (np. konto 0, 1, 2, 4), lecz uporczywie wysyłało kolejne żądania do martwego konta 5.

---

## 3. DETERMINISTYCZNA NAPRAWA

1. **Keep All w Trae:**
   Kliknij **„Keep All”** na dole w Trae (zatwierdza utworzenie `agent.py`, `requirements.txt`, `README.md`).
2. **Restart czatu dla wymuszenia rotacji konta:**
   Otwórz nowy czat w Trae i wpisz:
   > *„Otwórz agent/agent.py. Dodaj obsługę flagi CLI `--auto-approve` oraz zastąp liczby stałymi. Zapisz plik od razu narzędziem Write.”*
