# DeepSeek Web Proxy: Analiza First Principles, Deterministyczna Diagnoza i Baza Wiedzy

> **Cel dokumentu:** Sprowadzenie działania DeepSeek Web Proxy do samych bitów, twardych faktów, dowodów empirycznych i praw rządzących interakcją Trae IDE <-> Proxy <-> DeepSeek Web Backend. Zero zgadywania, zero łatania objawów.

---

## 1. Fundamentalny Kontrakt i Niezgodność Światów (First Principles)

Cały problem proxy wynika z próby połączenia dwóch całkowicie sprzecznych architektur:

| Aspekt | Trae IDE (Klient) | DeepSeek Web (Darmowy Backend) |
|---|---|---|
| **Protokół** | Ścisły standard OpenAI API `/v1/chat/completions` | Wewnętrzny, dynamiczny protokół przeglądarkowy SSE (`chat.deepseek.com/api/v0/chat/completion`) |
| **Wywołania narzędzi (Tool Calling)** | **Wyłącznie JSON w protokole**: chunk SSE musi zawierać `delta.tool_calls` z `id`, `name`, `arguments`, a ostatni chunk **MUSI** mieć `finish_reason: "tool_calls"`. | **Czysty tekst w oknie czatu**: model generuje tekstowe tagi (DSML, XML, JSON) bezpośrednio w strumieniu znaków. Brak pojęcia `tool_calls` na poziomie HTTP. |
| **Zarządzanie sesją** | Trae wysyła **całą historię rozmowy na nowo co turę** (brak wysyłania `chat_id`). | DeepSeek Web jest sesyjny (`chat_session_id` + `parent_message_id`). Duża historia wysyłana na raz dławi serwer. |
| **Tolerancja błędów** | **Zero-jedynkowa**: Jeśli Trae dostanie choćby 1 znak surowego tagu jako tekst albo `finish_reason: "stop"` zamiast `"tool_calls"`, uznaje turę za skończoną, nie odpala narzędzia/subagenta i rozmowa umiera. | **Niestabilna**: Model zmienia formaty tagów (DSML, XML, JSON), urywa odpowiedzi przy limitach tokenów bez żadnego sygnału `FINISHED`. |

---

## 2. Deterministyczne Dowody Przyczyn Awarii (Udowodnione na Bitach)

### DOWÓD A: Samobójczy Anti-Loop Guard (`_detect_loop`) zabijający legalny DSML
- **Fakt w kodzie:** `_detect_loop` sprawdza, czy dowolny fragment o długości 15–50 znaków powtórzył się $\ge 4$ razy w oknie ostatnich 300 znaków bufora.
- **Empiryczny dowód:** Narzędzie `Task` (uruchomienie subagenta) wymaga parametrów: `description`, `query`, `subagent_type`, `response_language`. Każdy parametr jest zamykany tagiem `</｜｜DSML｜｜parameter>`.
- **Wynik testu:** `scratch/test_loop_guard_false_positive.py` udowodnił, że tag zamykający `</｜｜DSML｜｜parameter>` powtarza się 4 razy w oknie 300 znaków i **odcina strumień na znaku 215**, ustawiając `finished_normally = True`!
- **Łańcuch katastrofy:**
  1. DeepSeek generuje poprawne wywołanie subagenta w DSML.
  2. `_detect_loop` myli tagi parametrów z pętlą tokenów i brutalnie przerywa połączenie w trakcie generowania.
  3. `_has_unclosed_tool_call` i Auto-Continue są pomijane, bo guard ustawił `finished_normally = True`.
  4. Niedokończony DSML nie daje się sparsować przez `_parse_tool_calls`.
  5. Fallback w `generate()` wycina znaczniki `<...>` za pomocą regexa i **wypluwa treść promptu subagenta jako zwykły tekst do czatu**.
  6. Trae kończy ze statusem `stop`. Subagent nigdy nie startuje.

### DOWÓD B: Ślepota detektora urwanych tagów (`_has_unclosed_tool_call`)
- **Fakt w kodzie:** Detektor zlicza otwarcia i zamknięcia tagów za pomocą prymitywnego regexa:
  `<\s*(?:tool_call|invoke|tool_capability|_call|call|tool)\s+name=`
- **Fakt protokołu:** DeepSeek V3/R1/V4 natywnie generuje format DSML z pełnoszerokościowymi znakami pipe:
  `<｜｜DSML｜｜invoke name="Task">` oraz tagi nadrzędne `<｜｜DSML｜｜tool_calls>`.
- **Wynik:** Regex `_has_unclosed_tool_call` zwraca `False` dla każdego uciętego DSML. Proxy uznaje przerwany strumień za kompletny i nie wysyła `KONTYNUUJ`.

### DOWÓD C: Dławienie kontekstowe DeepSeek Web (0-Byte Drop / `No data lines`)
- **Fakt protokołu:** DeepSeek Web (darmowy endpoint webowy) posiada sztywny limit przetwarzania pojedynczego żądania.
- Gdy historia wysyłana przez Trae (narastająca przez wyniki `Read`, `Grep`, `LS`) przekracza ~50k–70k znaków:
  1. Backend DeepSeek Web zwraca `200 OK`, ale w strumieniu SSE wysyła **0 linii danych** (`data:`) i natychmiast zamyka socket (`FIN`).
  2. Proxy otrzymuje pusty strumień, nie ma żadnych tokenów i generuje komunikat o błędzie.

### DOWÓD D: Rotacja tożsamości i zaostrzone zabezpieczenia Web WAF
- **Fakt:** Prawdziwy frontend DeepSeek wysyła zestaw nagłówków wersji i sygnatur:
  `x-client-version: 2.3.0`, `x-client-bundle-id: com.deepseek.chat`, `x-client-timezone-offset: 7200`, `x-hif-leim` (dynamiczny podpis), `x-ds-pow-response` (Proof of Work).
- Stary kod proxy wysyłał nieistniejące `x-app-version: 2.0.0` i brakujące sygnatury, co powodowało cichy throttling (dławienie sesji po kilku requestach).

---

## 3. Prawa Determinizmu (Jak proxy MUSI działać)

Aby proxy działało bezbłędnie w 100% przypadków:

1. **ZAKAZ niszczących heurystyk:**
   - Usunąć/przepisać `_detect_loop`, aby wykrywał wyłącznie rzeczywiste powtórzenia całych zdań/linii (np. 100-znakowy blok powtórzony 5 razy), a NIGDY nie sprawdzał krótkich 15-znakowych fragmentów zawierających składnię tagów XML/DSML.

2. **Ścisła Maszyna Stanów Strumienia (Stream State Machine):**
   - Jeśli w tekście pojawi się otwierający tag narzędzia (`<｜｜DSML`, `<tool_call`, `<invoke`, `<_call`), **ŻADEN fragment tego bloku nie ma prawa trafić do Trae jako zwykły tekst**.
   - Jeśli strumień się skończy bez domknięcia tagu -> **BEZWZGLĘDNIE odpala się Auto-Continue** (wysłanie `"KONTYNUUJ"` z `parent_message_id`).
   - Dopiero po kompletnym domknięciu tagu następuje parsowanie do formatu OpenAI i wysłanie do Trae z `finish_reason: "tool_calls"`.

3. **Deterministyczna Kompresja Kontekstu (Proaktywny Context Management):**
   - Zamiast czekać aż prompt spuchnie do 74k znaków i DeepSeek zwróci 0 bajtów:
   - Wyniki starych narzędzi (`Read`, `Grep`, `Glob`, `LS`) w historii wiadomości wysyłanej do DeepSeeka muszą być redukowane do zwięzłych znaczników (np. `[Plik X przeczytany, N linii]`), utrzymując rozmiar całego promptu zawsze poniżej 30k znaków.
