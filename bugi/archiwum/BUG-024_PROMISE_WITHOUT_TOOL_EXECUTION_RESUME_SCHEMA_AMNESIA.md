# BUG-024: Puste Obietnice Narzędzi bez Emisji XML i Amnezja Schematów w Trybie Resume (Podwójne Przerwanie Czatu / 0%)

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** ✅ **Naprawione w proxy / Zweryfikowane testami** (`test_bug024.py`)  
**Dotknięte komponenty:** `server.py` (`tool_pat` asymetria DSML/invoke, `_build_prompt` resume directive, `generate` empty promise guard)  
**Dowody wizualne:** [`media_1788595689394.png`](file:///C:/Users/Ksawier/.gemini/antigravity/brain/87701fc8-c77e-455c-831f-ebcd5eee55d0/.user_uploaded/media_1788595689394.png), [`media_1788595749053.png`](file:///C:/Users/Ksawier/.gemini/antigravity/brain/87701fc8-c77e-455c-831f-ebcd5eee55d0/.user_uploaded/media_1788595749053.png), [`media_1788596162070.png`](file:///C:/Users/Ksawier/.gemini/antigravity/brain/87701fc8-c77e-455c-831f-ebcd5eee55d0/.user_uploaded/media_1788596162070.png)  

---

## 1. Objawy Awarii (Objawy Widoczne w GUI Trae)

Użytkownik zlecił agentowi wykonanie audytu całego systemu AI w projekcie Cortex. W trakcie pracy wystąpiła seria trzech zacięć z rzędu:

### Incydent 1 (Pierwsze przerwanie):
1. Agent modyfikuje `start.bat` (`1 file changed +1 -2`).
2. Następnie wypisuje w czacie:
   > *"Naprawiłem start.bat. Czekam jeszcze na wyniki subagentów audytowych, żeby zebrać komplet błędów i wad całego systemu AI."*
3. **Awaria:** Agent natychmiast kończy turę. Żadne wyniki nie spływają, a subagenci w rzeczywistości nie zostali uruchomieni lub ich wywołania przepadły.

### Incydent 2 (Drugie przerwanie — zrzut `media_1788595689394.png`):
1. Zdezorientowany użytkownik pisze: `nic nie wyslales`.
2. Agent odpowiada:
   > *"Masz rację — subagenci audytowi nie zwrócili wyników (zlecenia nie wróciły). Odpalam je teraz na świeżo, równolegle."*
3. **Awaria:** Agent stawia kropkę i **natychmiast kończy turę**. Wskaźnik postępu w Trae zamarza na **`0%`**. Agent nie wyemitował żadnego wywołania narzędzia (`Task`), nie uruchomił żadnego procesu w tle — złożył pustą obietnicę i zamilkł.

### Incydent 3 (Trzecie przerwanie — zrzut `media_1788595749053.png`):
1. Użytkownik ponawia uwagę: `przerywa cos. twoj tool cos nie dziaal`.
2. Agent odpowiada:
   > *"Rozumiem — mój tool do zlecania subagentów nie zadziałał, więc zrobię audyt samodzielnie, bez subagentów. Zacznę od przeczytania kluczowych fragmentów kodu."*
3. **Awaria:** Znowu to samo! Agent deklaruje, że zaczyna czytać kod, po czym **nie wywołuje narzędzia `Read` ani `Grep`**. Kończy generowanie z `finish_reason: "stop"`, a w Trae pojawia się kółko **`0%`**.

---

## 2. Dowody z Logów Proxy (`proxy_output.log` & `raw_stream_capture.jsonl`)

W logach proxy z momentu incydentu 2 (sesja `30e14ee42913`):
```text
[REQUEST] roles={'assistant', 'user', 'tool', 'system'} tools=20 msgs=66
[HYBRID] Using web chat (resume, msgs=66)
[RESUME] ds_session=1c7a7682-dc43-4e77-bc96-5b35e71f7d01 account=2 parent=60 skip=64 send=1 new msgs (no schemas, no echo)
...
[TIMING] DS stream done, resp_id=62 finished=True
[TIMING] Stream done (9.0s, 0 tools, wm=30e14ee42913...)
```

W surowym zrzucie myślenia modelu (`raw_stream_capture.jsonl`):
```text
user says "nic nie wyslales" (you didn't send anything). The subagent Task calls I made earlier (the three audit tasks) apparently never got returned to me — I see them as tool_uses in the conversation but I never received their results...
Let me re-launch the audit subagents now (in parallel) and wait for their results...
Let me launch them now.

Masz rację — subagenci audytowi nie zwrócili wyników (zlecenia nie wróciły). Odpalam je teraz na świeżo, równolegle.
```
Model w myślach pisze: *"Let me launch them now"*, po czym na kanale wyjściowym generuje tylko jedno zdanie i **zamyka strumień bez wyemitowania tagu `<tool_call name="Task">`**. Proxy raportuje: `0 tools`!

W incydencie 3 (sesja `834d3357dcfc`):
```text
[HYBRID] Using web chat (resume, msgs=68)
[RESUME] ds_session=1c7a7682-dc43-4e77-bc96-5b35e71f7d01 account=2 parent=62 skip=66 send=1 new msgs (no schemas, no echo)
[TIMING] Stream ready (0.5s, resp_id=64)
...
[TIMING] DS stream done, resp_id=64 finished=True
[TIMING] Stream done (2.3s, 0 tools, wm=834d3357dcfc...)
```
Odpowiedź trwała zaledwie 2.3 sekundy, wygenerowała 153 znaki tekstu, `0 tools` i zamknęła się z `finish_reason: "stop"`.

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

### A. Amnezja schematów i formatu narzędzi w trybie `resume` (`server.py:L3476`)
W kodzie wznawiania sesji proxy:
```python
print(f"[RESUME] ds_session={chat_id} account={account_idx} parent={parent_id} skip={state['msgs_len']} send={len(new_msgs)} new msgs (no schemas, no echo)", flush=True)
prompt = _build_prompt(new_msgs, tools=None, state=state)
```
Proxy przekazuje `tools=None` z założeniem, że DeepSeek pamięta schematy narzędzi z pierwszej wiadomości sprzed kilkudziesięciu tur.  
Jednak gdy `tools is None`:
1. `tools_suffix` w `_build_prompt` jest pusty (`""`).
2. Nie zostaje dołączona sekcja `# Tool Call Format`:
   ```text
   CRITICAL: When you say you will check, read, edit, or search files, you MUST emit the <tool_call> block immediately in the same message. NEVER output promises or plain text parameter lists like 'Grep pattern: ...' without the actual <tool_call> XML block!
   ```
3. Gdy użytkownik wysyła krótką wiadomość (`"nic nie wyslales"`, `"przerywa cos..."`), prompt wysłany do DeepSeeka zawiera **wyłącznie ten krótki string bez żadnego kontekstu narzędziowego ani instrukcji agenta**.

### B. Przełączenie modelu w tryb konwersacyjny (Conversational Fallback)
Pozbawiony przypomnienia o narzędziach i formacie XML, model interpretuje uwagę użytkownika jako zwykłą ludzką rozmowę. Zamiast zachowywać się jak autonomiczny agent:
- Przyznaje rację użytkownikowi.
- Deklaruje zamiar podjęcia akcji w czasie przyszłym (*"Odpalam je teraz"*, *"Zrobię audyt samodzielnie, zacznę od przeczytania..."*).
- Kończy wypowiedź, czekając na kolejną turę, zamiast natychmiast wygenerować blok `<tool_call>`.

### C. Zakończenie tury w Trae z `0%`
Ponieważ proxy nie wykryło żadnego narzędzia (`tools_yielded == 0`), kończy odpowiedź z `finish_reason: "stop"`. Trae wyświetla tekst w dymku, widget postępu staje na `0%`, a użytkownik zostaje z obietnicą bez pokrycia.

---

## 4. Wymagany Plan Naprawy

1. **Wstrzykiwanie przypomnienia formatu narzędzi w trybie `resume`:**  
   Nawet gdy pełne schematy JSON/XML nie są powtarzane w trybie `resume` (aby oszczędzać tokeny), do wiadomości **MUSI** być zawsze doklejane skrócone przypomnienie narzędziowe:
   ```text
   [SYSTEM DIRECTIVE: You are an autonomous agent with active tools (Task, Read, Grep, Write, etc.). If you intend to run subagents, read files, or execute commands, you MUST output the <tool_call name="...">...</tool_call> block NOW in this message. Do NOT make bare text promises.]
   ```
2. **Strażnik pustych deklaracji (Empty Promise Guard):**  
   Jeśli wygenerowany tekst asystenta kończy się bez wywołań narzędzi, a zawiera sformułowania deklaratywne:
   `r"(?:odpalam|zrobię|zacznę od|czekam na|zaraz|uruchamiam|let me launch|let me read)\b"`:  
   Proxy powinno wstrzyknąć ostrzeżenie lub zapobiec przedwczesnemu zamykaniu tury z pozorowanym sukcesem.
