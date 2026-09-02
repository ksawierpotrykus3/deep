# BUG-015: Zduplikowane Podwójne Wywołanie `Read SupervisorView.tsx` w Jednym Dymku i Pętla Zagłady po Pytaniu Hipotetycznym

**Data rejestracji:** 2026-08-31 22:30  
**Komponenty:** `server.py` (Disabled Debounce L2748), Model Planning & Tool Dispatcher, Trae Interface  
**Wpływ na działanie:** WYSOKI (Model wygenerował DWA identyczne wywołania `Read SupervisorView.tsx` w tym samym dymku, czytając ten sam plik łącznie 3 razy pod rząd bez wygenerowania żadnego kodu).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu)

### Incydent: Podwójny odczyt tego samego pliku w jednej odpowiedzi
* **Dymek asystenta po kliknięciu 'kontynuuj' (ze zrzutu ekranu):**
  * `Agent`
  * `Read 2 files v`
    * `Read SupervisorView.tsx`
    * `Read SupervisorView.tsx`
  * Postęp: `1%` $\rightarrow$ **Zwis**.
* **Wynik:** Model wpadł w amok i w jednej odpowiedzi zażądał dwukrotnego odczytu dokładnie tego samego pliku.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Wyłączony debounce w `server.py` (Liniijka 2748)
Proxy nie zablokowało identycznego wywołania narzędzia w ramach tego samego strumienia. Model wygenerował dwa tagi `<invoke name="Read">` dla `SupervisorView.tsx`, a proxy bezkrytycznie przekazało oba do Trae.

### B. Szok kognitywny na promptach hybrydowych
Użytkownik zapytał: *„założmy że mam globalny przycisk... jakby on wyglądał? i musisz go dodać gdzieś”*.
Połączenie pytania teoretycznego (*jakby wyglądał*) z poleceniem wykonawczym (*dodaj go*) wprowadziło model w paranoję analityczną i pętlę redundancji.

---

## 3. DETERMINISTYCZNA NAPRAWA

1. **Wdrożenie Same-File Lock w `server.py`:**
   Bezwzględne blokowanie powtórnych odczytów tego samego pliku.
2. **Jednoznaczne polecenie dla Trae:**
   > *„Dodaj do `src/supervisor/SupervisorView.tsx` na każdej karcie pipeline'u przycisk '▶ Uruchom potok', który wywołuje `window.nexusBridge.supervisorRunPipeline(pipeline.id)`. Zapisz plik od razu.”*
