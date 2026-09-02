# BUG-009: Inwersja Narzędzi (Action-Intention Mismatch: Deklaracja Write -> Wywołanie Read), Pętla Mikro-Odczytów i Paraliż Sesji (0 Tokenów)

**Data rejestracji:** 2026-08-31 20:16  
**Komponenty:** Model Planning & Tool Dispatcher, `server.py`, Context Management, Trae Tool Interface  
**Wpływ na działanie:** KRYTYCZNY (Model za każdym razem deklaruje zapisanie kodu do `types.ts`, ale zamiast `Write` w kółko wykonuje `Read types.ts`, zapychając kontekst mikro-odczytami i paraliżując sesję do stanu 0 tokenów).

---

## 1. DOWODY EMPIRYCZNE (Objawy z 3 zrzutów ekranu)

### Incydent 1: Deklaracja zapisu `Write`, a fizyczne wywołanie `Read types.ts`
* **Tekst wygenerowany przez model:**
  > `Nie mam narzędzia Edit — użyję Write do nadpisania pliku. Zaczynam od types.ts.`
* **Wywołane narzędzie (rozwinięte na screenie 2 i 3):**
  > `Read 1 file` $\rightarrow$ **`Read types.ts`**
* **Wynik:** Model zapowiadał modyfikację, ale wywołał operację odczytu pliku, który już wielokrotnie znajdował się w jego historii.

### Incydent 2: Druga tura i powtórzenie tego samego błędu (Pętla Mikro-Odczytów)
* **Tekst w kolejnym dymku (screen 1):**
  > `Przepraszam za przerwy w odczycie. Czytam pliki w mniejszych fragmentach, żeby uzyskać pełną zawartość.`  
  > `Read 3 files >`  
  > `Czytam dalsze fragmenty SupervisorView.tsx i testów.`  
  > `Read 4 files >`  
  > `Czytam końcówkę SupervisorView.tsx.`  
  > `Read 2 files >`  
  > `Mam pełny obraz. Zaczynam naprawy. Najpierw types.ts.`  
  > `Read 1 file >` (rozwinięcie: **`Read types.ts`**) $\rightarrow$ **Zwis i 0%**.
* **Twardy dowód z monitora sesji (`data/sessions_monitor.json`):**
  ```json
  [0] session_id: cd1f402e acc: 3 state: done tokens: 0 thinking: 0 age: 58.2s finished: True ok: True
  [1] session_id: b8d6da57 acc: 3 state: done tokens: 0 thinking: 0 age: 68.6s finished: True ok: True
  ```
  Zaraz po drugim wywołaniu `Read types.ts`, kolejne dwie sesje zwróciły **dokładnie 0 tokenów**.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Rozszczepienie intencji i wywołania funkcji (*Action-Perception Gap*)
Model w warstwie tekstowej poprawnie wnioskuje: *"muszę nadpisać types.ts narzędziem Write"*, ale w warstwie wyboru narzędzia ulega regresji do schematu sprawdzania: *"przeczytajmy go jeszcze raz przed edycją"*. W efekcie zamiast payloadu `Write` z nowym kodem, model emituje `Read`.

### B. Przebodźcowanie kontekstu mikro-fragmentami (*Context Saturation*)
Model wykonał łącznie w tej turze:
* `Read 3 files` + `Read 4 files` + `Read 2 files` + `Read 1 file` = **10 operacji odczytu w jednym dymku!**
Wstrzyknięcie dziesiątek tysięcy znaków tego samego pliku `SupervisorView.tsx` w mikro-porcjach nasyciło okno uwagi modelu.

### C. Zablokowanie backendu DeepSeek Web (Paraliż 0 tokenów)
Po napuchnięciu historii konwersacji powyżej progu przepustowości darmowej sesji webowej na koncie `account: 3`, backend DeepSeeka przestał przetwarzać dalsze zapytania, zwracając natychmiastowe puste odpowiedzi (`tokens: 0`).

---

## 3. DETERMINISTYCZNA ARCHITEKTURA NAPRAWCZA

```mermaid
flowchart TD
    A[Model generuje tekst 'Użyję Write / Zaczynam od pliku X'] --> B{Czy kolejnym wywołanym narzędziem jest Read tego samego pliku?}
    
    B -->|Tak (Wykryto inwersję Write -> Read)| C[INTERCEPTOR: Zablokuj Read! Wstrzyknij prompt: 'Zadeklarowałeś Write. Wykonaj Write natychmiast, zakaz ponownego Read']
    
    B -->|Nie, model wywołał Write| D[Zezwól na zapis pliku]
    
    C --> E[Model generuje kod i zapisuje plik]
```

### Zasady deterministycznej ochrony:
1. **Intention-Mismatch Interceptor:**
   * Jeśli model w odpowiedzi tekstowej deklaruje intencję zapisu (`użyję Write`, `zapisuję do pliku`, `zaczynam naprawy`), a jako pierwsze narzędzie próbuje wywołać `Read` tego samego pliku: proxy blokuje odczyt i wymusza wywołanie `Write`.
2. **Same-File Read Lock (zgodnie z BUG-005):**
   * Zablokowanie wielokrotnego czytania `types.ts` i `SupervisorView.tsx` uniemożliwiłoby zapchanie kontekstu 10 mikro-odczytami.
3. **Session Reset on Zero Tokens:**
   * Po wykryciu odpowiedzi `tokens: 0` proxy musi zrotować sesję do nowego czatu na innym koncie, aby zrzucić przeciążony bufor.
