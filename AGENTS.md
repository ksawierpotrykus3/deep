# DeepSeek Proxy Server - Dokumentacja dla Agentów

## 🎯 Cel dokumentu

Ten dokument wyjaśnia działanie serwera proxy `deepseek-proxy`, który działa jako most między IDE (Kiro/Trae) a DeepSeek Chat API. Każdy agent pracujący nad tym projektem powinien znać te mechanizmy.

---

## ⚠️ KRYTYCZNE ZAŁOŻENIE

**RESUME NIGDY NIE JEST POCZĄTKIEM ROZMOWY!**

- ✅ **NOWA SESJA** = pierwszy request użytkownika (messages: [system, user])
- ✅ **RESUME** = kontynuacja po otrzymaniu tool results (messages: [system, user, assistant, tool, user, ...])

**Jeśli jest resume, to znaczy że:**
- Sesja DeepSeek **już istnieje**
- System prompt i tools **już zostały wysłane** w pierwszej turze
- Teraz wysyłamy **TYLKO nowe tool results**

**NIGDY nie zakładaj, że resume = początek konwersacji!**

---

## 📋 Spis treści

1. [Architektura ogólna](#architektura-ogólna)
2. [Wykrywanie nowych sesji vs wznowienie (resume)](#wykrywanie-nowych-sesji-vs-wznowienie-resume)
3. [Przekazywanie narzędzi (tools) do agenta](#przekazywanie-narzędzi-tools-do-agenta)
4. [Przekazywanie serwerów MCP](#przekazywanie-serwerów-mcp)
5. [Routing subagentów](#routing-subagentów)
6. [Najważniejsze moduły](#najważniejsze-moduły)
7. [Przepływ danych - diagramy sekwencji](#przepływ-danych-diagramy-sekwencji)
8. [Multi-Part Chunked Prompt Injection i struktura drzewa wiadomości](#multi-part-chunked-prompt-injection-i-struktura-drzewa-wiadomości)
9. [Obsługa niestandardowych formatów Tool Calls (Chinese Bracket Calls `[调用 ToolName]`)](#obsługa-niestandardowych-formatów-tool-calls-chinese-bracket-calls-调用-toolname)
10. [Obsługa tagów potomnych i restartu wywołania (Stutter & Sibling Tags `description`)](#obsługa-tagów-potomnych-i-restartu-wywołania-stutter--sibling-tags-description)
11. [Obsługa wywołań w buforze myślenia i uszkodzonych openerów (Thinking Fallback & `ToolMgr.try_parse`)](#obsługa-wywołań-w-buforze-myślenia-i-uszkodzonych-openerów-thinking-fallback--toolmgretry_parse)
12. [Zakaz przerywania strumienia na `quasi_status` (Quasi Reasoning vs Response)](#zakaz-przerywania-strumienia-na-quasi_status-quasi-reasoning-vs-response)
13. [Obsługa błędów chwilowej niedostępności klastra (Transient Cluster Errors: `Server is temporarily unavailable.`)](#obsługa-błędów-chwilowej-niedostępności-klastra-transient-cluster-errors-server-is-temporarily-unavailable)
14. [Automatyczny Re-prompt przy przedwczesnym zamilknięciu agenta (Auto-reprompt on Premature Stop without Tool Calls)](#automatyczny-re-prompt-przy-przedwczesnym-zamilknięciu-agenta-auto-reprompt-on-premature-stop-without-tool-calls)
15. [Zabezpieczenie przed fałszywym sukcesem przy pustym ponowieniu strumienia (Empty Stream Guard in Retry)](#zabezpieczenie-przed-fałszywym-sukcesem-przy-pustym-ponowieniu-strumienia-empty-stream-guard-in-retry)
16. [Zapobieganie dublowaniu promptu w trybie Resume (`is_resume` Guard w `NEW_SESSION_FIX` & Delta Consecutive User Dedup)](#16-zapobieganie-dublowaniu-promptu-w-trybie-resume-is_resume-guard-w-new_session_fix--delta-consecutive-user-dedup)
17. [Automatyczny Session Rollover przy przeciążeniu kontekstu sesji DeepSeek (>250k tokenów) lub persistent 503](#17-automatyczny-session-rollover-przy-przeciążeniu-kontekstu-sesji-deepseek-250k-tokenów-lub-persistent-503)
18. [Całkowity zakaz wycieku myśli jako odpowiedzi asystenta (`thinking_fallback` suppression w trybie narzędzi) i odblokowanie retry (`content_already_sent`)](#18-całkowity-zakaz-wycieku-myśli-jako-odpowiedzi-asystenta-thinking_fallback-suppression-w-trybie-narzędzi-i-odblokowanie-retry-content_already_sent)
19. [Natywny mechanizm Continue (`POST /api/v0/chat/continue`) oraz obsługa fragmentów RESPONSE w obiekcie SSE](#19-natywny-mechanizm-continue-post-apiv0chatcontinue-oraz-obsługa-fragmentów-response-w-obiekcie-sse)
20. [Obsługa multimodalna OpenAI Vision (Ekstrakcja obrazów, upload do DeepSeek Web i `ref_file_ids`)](#20-obsługa-multimodalna-openai-vision-ekstrakcja-obrazów-upload-do-deepseek-web-i-ref_file_ids)
21. [Multi-Part Chunked Prompt Injection (Obsługa gigantycznych promptów w `prompt_chunker.py`)](#21-multi-part-chunked-prompt-injection-obsługa-gigantycznych-promptów-w-prompt_chunkerpy)
22. [Optymalizacja PoW (Proof-of-Work) i wielotargetowy Cache w `deepseek_client.py`](#22-optymalizacja-pow-proof-of-work-i-wielotargetowy-cache-w-deepseek_clientpy)
24. [Usunięcie martwych helperów stanu, nieużywanych importów i metod AccountPool (v2.28)](#24-usunięcie-martwych-helperów-stanu-nieużywanych-importów-i-metod-accountpool-v228)
25. [Usunięcie martwego modelu ChatRequest, zbędnych stałych konfiguracyjnych i nieużywanych importów (v2.29)](#25-usunięcie-martwego-modelu-chatrequest-zbędnych-stałych-konfiguracyjnych-i-nieużywanych-importów-v229)
26. [Natywny stop_stream dla Interim Chunków i ochrona kontekstu Smart Context Retention (v2.30)](#26-natywny-stop_stream-dla-interim-chunków-i-ochrona-kontekstu-smart-context-retention-v230)
27. [Aktualizacja nagłówków i payloadu do protokołu DeepSeek Web v2.5.0 (v2.31)](#27-aktualizacja-nagłówków-i-payloadu-do-protokołu-deepseek-web-v250-v231)
28. [Samonaprawiający się stan sesji i autokorekta Parent ID (Self-Healing Session State & `biz_code: 26`) (v2.32)](#28-samonaprawiający-się-stan-sesji-i-autokorekta-parent-id-self-healing-session-state--biz_code-26-v232)
29. [Deterministyczne interim chunky z ACK i Repetition Loop Guard (v2.33)](#29-deterministyczne-interim-chunky-z-ack-i-repetition-loop-guard-v233)
30. [Likwidacja opóźnień orkiestracji interim chunków i nagłówki antybuforujące SSE (v2.34)](#30-likwidacja-opóźnień-orkiestracji-interim-chunków-i-nagłówki-antybuforujące-sse-v234)
31. [Strategia załączania dokumentów z limitem 100 MB per plik (Document Attachment Strategy) (v2.35)](#31-strategia-załączania-dokumentów-z-limitem-100-mb-per-plik-document-attachment-strategy-v235)
32. [Pełne zachowanie historii konwersacji z IDE w conversation_history.md i likwidacja sztucznego obcinania wiadomości (v2.36)](#32-pełne-zachowanie-historii-konwersacji-z-ide-w-conversation_historymd-i-likwidacja-sztucznego-obcinania-wiadomości-v236)
33. [Eliminacja catastrophic backtracking (ReDoS) w _sanitize_for_structure i natychmiastowy bail-out w _is_capture_complete (v2.37)](#33-eliminacja-catastrophic-backtracking-redos-w-_sanitize_for_structure-i-natychmiastowy-bail-out-w-_is_capture_complete-v237)
34. [Eliminacja Double Throttling, ochrona pętli asyncio przed time.sleep oraz bezbłędny keep-alive retry bez kodu 429 (v2.38)](#34-eliminacja-double-throttling-ochrona-pętli-asyncio-przed-timesleep-oraz-bezbłędny-keep-alive-retry-bez-kodu-429-v238)
35. [Multi-Account Authentication & Dynamic Account Rotation (Slot 0 + Slot 1) (v2.39)](#35-multi-account-authentication--dynamic-account-rotation-slot-0--slot-1-v239)
36. [Płynny Account Failover, Session Rollover i 100% historii w conversation_history.md (v2.40)](#36-płynny-account-failover-session-rollover-i-100-historii-w-conversation_historymd-v240)
37. [Automatyczne wykrywanie uciętych odpowiedzi i bezszwowe Auto-Continue (v2.41)](#37-automatyczne-wykrywanie-uciętych-odpowiedzi-i-bezszwowe-auto-continue-v241)
38. [Twardy limit budżetowy załącznika historii (95 KB ceiling) i eliminacja OOM klastra (v2.42)](#38-twardy-limit-budżetowy-załącznika-historii-95-kb-ceiling-i-eliminacja-oom-klastra-v242)
39. [Bezwzględny priorytet POST /api/v0/chat/continue w trwających sesjach, likwidacja niechcianych nowych konwersacji i zachowanie 100% historii (v2.43)](#39-bezwzględny-priorytet-post-apiv0chatcontinue-w-trwających-sesjach-likwidacja-niechcianych-nowych-konwersacji-i-zachowanie-100-historii-v243)
40. [Eliminacja zamarzania odpowiedzi na myśleniu, zakaz wycieku thinking_fallback w trybie narzędzi oraz odporność reprompt na błędy klastra (v2.44)](#40-eliminacja-zamarzania-odpowiedzi-na-myśleniu-zakaz-wycieku-thinking_fallback-w-trybie-narzędzi-oraz-odporność-reprompt-na-błędy-klastra-v244)
41. [Automatyczny Account Failover / Session Rollover po wyczerpaniu STREAM BACKOFF i eliminacja błędu rl_time (v2.45)](#41-automatyczny-account-failover--session-rollover-po-wyczerpaniu-stream-backoff-i-eliminacja-błędu-rl_time-v245)
42. [Prawidłowe zachowanie resp_msg_id i natychmiastowe wznawianie uciętych odpowiedzi (POST /continue) bez blokady myślenia (v2.46)](#42-prawidłowe-zachowanie-resp_msg_id-i-natychmiastowe-wznawianie-uciętych-odpowiedzi-post-continue-bez-blokady-myślenia-v246)
43. [Priorytetyzacja kontenerów tool_calls w Sieve i likwidacja 15s opóźnienia throttle w pętli narzędziowej (v2.47)](#43-priorytetyzacja-kontenerów-tool_calls-w-sieve-i-likwidacja-15s-opóźnienia-throttle-w-pętli-narzędziowej-v247)
44. [Naprawa błędu NameError w async_throttle, ochrona awaitable i jawne logowanie błędów strumienia (v2.48)](#44-naprawa-błędu-nameerror-w-async_throttle-ochrona-awaitable-i-jawne-logowanie-błędów-strumienia-v248)
45. [Automatyczny Reprompt przy uszkodzonym XML znaczników narzędzi (unparsed_tool_markup) i rozszerzona naprawa direct tags (v2.49)](#45-automatyczny-reprompt-przy-uszkodzonym-xml-znaczników-narzędzi-unparsed_tool_markup-i-rozszerzona-naprawa-direct-tags-v249)
46. [Natychmiastowy Session Rollover i Account Failover przy Length limit reached na najmniej używanym koncie z załączeniem conversation_history.md (v2.50)](#46-natychmiastowy-session-rollover-i-account-failover-przy-length-limit-reached-na-najmniej-używanym-koncie-z-załączeniem-conversation_historymd-v250)
47. [Eliminacja blokady pętli asyncio przy streamingu, usunięcie przedwczesnych keep-alive oraz kompaktowanie dawnych tur historii (v2.51)](#47-eliminacja-blokady-pętli-asyncio-przy-streamingu-usunięcie-przedwczesnych-keep-alive-oraz-kompaktowanie-dawnych-tur-historii-v251)
48. [Zwolnienie połączenia curl_cffi w bloku finally i granularne logowanie kroków Rolloveru (v2.52)](#48-zwolnienie-połączenia-curl_cffi-w-bloku-finally-i-granularne-logowanie-kroków-rolloveru-v252)
49. [Eliminacja samoblokady (Self-Deadlock) na threading.Lock w clear_conv_by_messages i przejście na threading.RLock (v2.53)](#49-eliminacja-samoblokady-self-deadlock-na-threadinglock-w-clear_conv_by_messages-i-przejście-na-threadingrlock-v253)

---

## 🏗️ Architektura ogólna

### Stack technologiczny
- **Framework:** FastAPI + Uvicorn
- **Język:** Python 3.11+
- **State management:** JSON file (`conv_state.json`) + in-memory cache
- **WebSocket:** Dashboard real-time metrics
- **Browser automation:** Playwright (login flow)

### Główny endpoint
```
POST /v1/chat/completions
```
Kompatybilny z OpenAI Chat Completions API.


### Kluczowe komponenty

```
┌─────────────────────────────────────────────────────────────────┐
│                       IDE (Kiro/Trae)                           │
│  Wysyła: messages, tools, model, stream                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
         ┌───────────────────────────────────────────────┐
         │  server/api/routes.py                         │
         │  POST /v1/chat/completions                    │
         └───────────────────┬───────────────────────────┘
                             │
                             ▼
         ┌───────────────────────────────────────────────┐
         │  server/services/proxy_service.py             │
         │  ProxyService.chat_completions()              │
         │  - Walidacja                                  │
         │  - Wykrywanie resume vs nowa sesja            │
         │  - Budowanie promptu                          │
         │  - Streaming odpowiedzi                       │
         └───────────────────┬───────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐   ┌─────────────────┐   ┌──────────────┐
│ InputParser  │   │ StateService    │   │ DeepSeek API │
│ - Routing    │   │ - Hash lookup   │   │ - Sessions   │
│ - Cleaning   │   │ - State persist │   │ - Streaming  │
└──────────────┘   └─────────────────┘   └──────────────┘
                             │
                             ▼
         ┌───────────────────────────────────────────────┐
         │  server/core/stream_handler.py                │
         │  StreamHandler                                │
         │  - Parsowanie DSML tool calls                 │
         │  - MCP rewrite                                │
         └───────────────────┬───────────────────────────┘
                             │
                             ▼
         ┌───────────────────────────────────────────────┐
         │  Zwrot do IDE (SSE stream)                    │
         │  - Content chunks                             │
         │  - Tool calls (przepisane dla MCP)            │
         └───────────────────────────────────────────────┘
```


---

## 🔍 Wykrywanie nowych sesji vs wznowienie (resume)

### ⚠️ KLUCZOWE: Resume ≠ początek rozmowy

**RESUME zawsze oznacza kontynuację:**
- Użytkownik **już** wysłał pierwszą wiadomość
- Agent **już** odpowiedział (może z tool calls)
- IDE wykonało tool calls i teraz wysyła wyniki
- To jest **N-ta tura** konwersacji (N ≥ 2)

**NOWA SESJA to:**
- Pierwszy request w całej konwersacji
- messages: `[{role: "system"}, {role: "user"}]` - tylko 2 wiadomości
- Brak wcześniejszych odpowiedzi agenta
- Brak tool results w historii

### Problem do rozwiązania
Serwer musi rozpoznać, czy IDE wysyła:
- **Nową sesję (Tura 1)** → stwórz nową sesję DeepSeek, wyślij **PEŁNY** system prompt + tools + user message
- **Wznowienie (Tura N, N≥2)** → kontynuuj istniejącą sesję, wyślij **TYLKO** nowe tool results (bez system prompt, bez tools)

### ⚠️ KRYTYCZNE: Jak IDE formatuje messages

**IDE (Kiro/Cursor/Trae) wysyła messages w specyficznej strukturze:**

#### 🔹 NOWA KONWERSACJA (Turn 1):

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are an AI coding assistant, powered by deepseek-v4-pro. ..."
    },
    {
      "role": "user",
      "content": "<user_info>\nOS Version: win32 10.0.19045\nShell: powershell\nWorkspace Path: F:\\PROJEKTY\\vinted\n...</user_info>"
    },
    {
      "role": "user",
      "content": "<user_query>\nYou are auditing a Vinted bot at F:\\PROJEKTY\\vinted...\n</user_query>"
    },
    {
      "role": "user",
      "content": "<manually_attached_skills>\nThe user has manually attached...\n</manually_attached_skills>"
    }
  ],
  "tools": [...],
  "model": "deepseek-chat",
  "stream": true
}
```

**⚠️ UWAGA:** IDE wysyła **WIELE user messages** na początku:
1. **user_info** - workspace path, OS, shell (STABLE między konwersacjami w tym samym workspace)
2. **user_query** - actual user message (RÓŻNY dla każdej konwersacji!)
3. **manually_attached_skills** - opcjonalnie (jeśli user attachował skills)

**KRYTYCZNE:** Hash MUSI brać pod uwagę user_query (message #2), nie tylko user_info (#1)!

#### 🔹 RESUME (Turn 2+):

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are an AI coding assistant..."
    },
    {
      "role": "user",
      "content": "<user_info>...</user_info>"
    },
    {
      "role": "user",
      "content": "<user_query>Original query...</user_query>"
    },
    {
      "role": "user",
      "content": "<manually_attached_skills>...</manually_attached_skills>"
    },
    {
      "role": "assistant",
      "content": "",
      "tool_calls": [...]
    },
    {
      "role": "tool",
      "content": "Tool execution result..."
    },
    {
      "role": "user",
      "content": "<system-reminder>\n<tool_result>...\n<git_status>...\n<open_files>...\n</system-reminder>"
    }
  ],
  "tools": [],  // ← IDE często NIE wysyła tools przy resume!
  "model": "deepseek-chat",
  "stream": true
}
```

**Volatile content w resume:**
- `<system-reminder>` - tool results, git status, open files
- `<git_status>` - zmienia się przy każdym zapisie pliku
- `<open_and_recently_viewed_files>` - zmienia się dynamicznie
- `<system_notification>` - task completion notifications
- `"Today's date:"` - zmienia się codziennie

**Stable content:**
- system prompt
- user_info (workspace, OS)
- **user_query** (original message - NIE zmienia się między turami tej samej konwersacji)
- skills

#### 🔹 SUBAGENT (z task_id):

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are an AI coding assistant..."
    },
    {
      "role": "user",
      "content": "<user_info>...</user_info>"
    },
    {
      "role": "user",
      "content": "<manually_attached_skills>...</manually_attached_skills>"
    },
    {
      "role": "assistant",
      "content": ""
    },
    {
      "role": "tool",
      "content": "Subagent is running in the background..."
    },
    {
      "role": "user",
      "content": "<system_notification>\nThe following task has finished...\n<task>\ntask_id: 70cc3b57-28f5-4a24-9c8e-abc123def456\n</task>\n</system_notification>"
    }
  ]
}
```

**task_id detection:** Regex `task_id: ([a-f0-9\-]{36})` w user content.

---

### Rozwiązanie: Stabilny hash konwersacji

#### Kod: `server/services/state_service.py`

```python
def _msg_hash(messages: list[dict], n: int = 12) -> str:
    """Hash of stable conversation prefix: system + user messages only.
    
    Strategy: hash system + first K non-tool-result user messages.
    This is TRULY stable because:
      Round 1 save:   H([system, u1_info, u2_query, u3_skills])
      Round 2 lookup: H([system, u1_info, u2_query, u3_skills])  — MATCH!
      Round 3 lookup: H([system, u1_info, u2_query, u3_skills])  — MATCH!
    """
    MAX_USERS = 3  # system + first 3 user messages (user_info + user_query + skills)
    stable = []
    user_count = 0
    
    for m in messages:
        role = m.get("role", "")
        raw = m.get("content", "")
        content = _clean_content(raw)  # Usuwa volatile content
        
        if role == "system":
            stable.append({"role": role, "content": content})
        elif role == "user":
            if content.startswith("<tool_result>"):
                continue  # Skip tool results (resume turn)
            if not content.strip():
                continue  # Skip empty (system-reminder only)
            if user_count < MAX_USERS:
                stable.append({"role": role, "content": content})
                user_count += 1
        # assistant, tool roles are IGNORED
    
    tail = stable[-n:] if stable else []
    if not tail or user_count == 0:
        return ""  # ⚠️ KRYTYCZNE: bez co najmniej 1 wiadomości usera (np. sam system prompt) hash jest PUSTY!
    key = json.dumps(tail, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```


#### Funkcja `_clean_content()`

Usuwa **volatile content** (zmienia się w każdej turze):
- `<system-reminder>...</system-reminder>` - tool results
- `<git_status>...</git_status>` - zmienia się przy każdym zapisie
- `<open_and_recently_viewed_files>` - zmienia się dynamicznie
- `<system_notification>` - task completions
- `"Today'\''s date:"` - zmienia się codziennie

**Zachowuje stable content:**
- Workspace path
- OS version
- User'\''s actual message text

### Lookup flow

```python
def get_conv(messages: list[dict]) -> dict | None:
    """Return existing conversation state if hash matches and not expired.
    
    ⚠️ UWAGA: Jeśli zwraca state (nie None), to ZAWSZE jest resume!
    Oznacza to, że sesja już istnieje i była użyta wcześniej.
    """
    if len(messages) < 2:
        return None  # Za mało wiadomości - brak możliwości resume
    
    # 1. Hash match (nowy stabilny algorytm)
    h = _msg_hash(messages)
    if h:
        with conv_lock:
            entry = conv_state.get(h)
        if entry and time.time() - entry["ts"] < _TTL:
            return entry  # ✅ RESUME (sesja już istnieje!)
    
    # 2. Legacy hash match (backward compatibility)
    h_legacy = _msg_hash_legacy(messages)
    if h_legacy and h_legacy != h:
        with conv_lock:
            entry = conv_state.get(h_legacy)
        if entry and time.time() - entry["ts"] < _TTL:
            return entry  # ✅ RESUME
    
    # 3. Watermark extraction (PROXY_CHAT w assistant content)
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = str(m.get("content", ""))
            match = _PROXY_CHAT_RE.search(content)
            if match:
                chat_id = match.group(1)
                with conv_lock:
                    entry = chat_state.get(chat_id)
                if entry and time.time() - entry["ts"] < _TTL:
                    return entry  # ✅ RESUME
    
    return None  # ❌ NOWA SESJA (to jest pierwsza tura!)
```


### Przykład lifecycle

```
┌──────────────────────────────────────────────────────────────┐
│ Tura 1: NOWA SESJA (POCZĄTEK ROZMOWY)                       │
├──────────────────────────────────────────────────────────────┤
│ IDE wysyła:                                                  │
│   messages: [                                                │
│     {role: "system", content: "You are..."},                 │
│     {role: "user", content: "<user_info>workspace: F:\\PRJ"},│
│     {role: "user", content: "<user_query>Audit the bot"},   │
│     {role: "user", content: "<skills>..."}                   │
│   ]                                                          │
│   tools: [{name: "Write", ...}, {name: "Read", ...}]        │
│                                                              │
│ Proxy:                                                       │
│   _msg_hash([sys, u1_info, u2_query, u3_skills])            │
│     → "abc123def456"                                         │
│   get_conv() → None (nie znaleziono w state)                │
│   ✅ NOWA SESJA                                              │
│                                                              │
│ Proxy do DeepSeek:                                           │
│   PromptBuilder.build(                                       │
│     system_prompt = "You are..." ← WYSYŁA                    │
│     tools_schema = [Write, Read, ...] ← WYSYŁA               │
│     history = [] ← pusty                                     │
│     user_message = "<user_info>...\n<user_query>..."        │
│   )                                                          │
│                                                              │
│ create_session() → chat_id="sess_xyz", parent_id="msg_001"  │
│ set_conv() → zapisuje:                                       │
│   conv_state["abc123def456"] = {                             │
│     chat_id: "sess_xyz",                                     │
│     parent_id: "msg_001",                                    │
│     tools: [Write, Read, ...]                                │
│   }                                                          │
│                                                              │
│ DeepSeek odpowiada: tool_calls: [{name: "Write", ...}]      │
└──────────────────────────────────────────────────────────────┘


┌──────────────────────────────────────────────────────────────┐
│ Tura 2: RESUME (KONTYNUACJA PO TOOL EXECUTION)              │
├──────────────────────────────────────────────────────────────┤
│ ⚠️ TO NIE JEST POCZĄTEK! To jest kontynuacja po Turze 1!    │
│                                                              │
│ IDE wykonało Write, teraz wysyła wynik:                      │
│   messages: [                                                │
│     {role: "system", content: "You are..."},                 │
│     {role: "user", content: "<user_info>workspace: F:\\PRJ"},│
│     {role: "user", content: "<user_query>Audit the bot"},   │
│     {role: "user", content: "<skills>..."},                  │
│     {role: "assistant", tool_calls: [{Write}]},              │
│     {role: "tool", content: "File created"},                 │
│     {role: "user", content: "<system-reminder>..."}          │
│   ]                                                          │
│   tools: [] ← IDE często NIE wysyła tools przy resume!      │
│                                                              │
│ Proxy:                                                       │
│   _msg_hash([sys, u1_info, u2_query, u3_skills, asst, tool, u4])│
│     → ignoruje asst/tool/u4 (volatile)                       │
│     → zwraca hash([sys, u1_info, u2_query, u3_skills])      │
│     → "abc123def456" ✅ TEN SAM co Tura 1!                   │
│                                                              │
│   get_conv() → state = {                                    │
│     chat_id: "sess_xyz",  ← TA SAMA sesja!                  │
│     parent_id: "msg_001",                                    │
│     tools: [Write, Read, ...] ← ZAPISANE z Tury 1           │
│   }                                                          │
│   ✅ RESUME (sesja istnieje, to kontynuacja!)                │
│                                                              │
│ Proxy do DeepSeek:                                           │
│   PromptBuilder.build(                                       │
│     system_prompt = None ← NIE WYSYŁA (już jest w sesji!)   │
│     tools_schema = None ← NIE WYSYŁA (już jest w sesji!)    │
│     history = [                                              │
│       {role: "tool", content: "<tool_result>...</..."}       │
│     ]                                                        │
│     user_message = "<system-reminder>..."                    │
│   )                                                          │
│                                                              │
│ stream_completion(                                           │
│   chat_id="sess_xyz", ← KONTYNUACJA tej samej sesji!        │
│   parent_id="msg_001",                                       │
│   prompt="<tool_result>...</tool_result>\n[User]: Continue" │
│ )                                                            │
│                                                              │
│ DeepSeek widzi:                                              │
│   - System prompt (z Tury 1, zachowany w sesji)             │
│   - Tools (z Tury 1, zachowane w sesji)                     │
│   - User: "<user_info>...\n<user_query>..." (z Tury 1)      │
│   - Assistant: tool_calls Write (z Tury 1)                  │
│   - Tool result: "File created" (NOWE, z Tury 2)            │
│   - User: "<system-reminder>..." (NOWE, z Tury 2)           │
└──────────────────────────────────────────────────────────────┘


┌──────────────────────────────────────────────────────────────┐
│ BŁĄD: Dwie różne konwersacje (przed fixem v2.6)             │
├──────────────────────────────────────────────────────────────┤
│ Konwersacja A (16:35):                                       │
│   messages: [                                                │
│     {role: "system", content: "You are..."},                 │
│     {role: "user", content: "<user_info>F:\\PROJEKTY\\vinted"},│
│     {role: "user", content: "Audit the bot"}, ← RÓŻNY!      │
│   ]                                                          │
│                                                              │
│   _msg_hash() z MAX_USERS=1:                                │
│     → hash([sys, u1_info]) = "b44ca3d65672b18c"             │
│     (u2_query POMINIĘTY!)                                    │
│                                                              │
│ Konwersacja B (21:51):                                       │
│   messages: [                                                │
│     {role: "system", content: "You are..."},                 │
│     {role: "user", content: "<user_info>F:\\PROJEKTY\\vinted"},│
│     {role: "user", content: "Create implementation plan"},   │
│                                  ↑ RÓŻNY ale IGNOROWANY!     │
│   ]                                                          │
│                                                              │
│   _msg_hash() z MAX_USERS=1:                                │
│     → hash([sys, u1_info]) = "b44ca3d65672b18c"             │
│     ❌ TEN SAM HASH! → błędnie resumuje sesję A             │
│                                                              │
│ FIX v2.6: MAX_USERS=3                                        │
│   Konwersacja A: hash([sys, u1_info, u2_audit, u3])         │
│   Konwersacja B: hash([sys, u1_info, u2_plan, u3])          │
│   ✅ Różne hashe bo u2 (user_query) jest INCLUDED           │
└──────────────────────────────────────────────────────────────┘
```

### Sub-worker detection

Gdy subagent (np. `[Worker #0]`) używa tej samej konwersacji:

```python
def _get_worker_id(messages: list[dict]) -> str | None:
    """Extract worker ID (e.g. [Worker #0]) from any message content."""
    for m in messages:
        content = m.get("content", "")
        # ... search for [Worker #N] pattern
        ws = _WORKER_ID_RE.search(content)
        if ws:
            return ws.group(0)
    return None

# W get_conv():
if entry.get("worker_id"):
    current_wid = _get_worker_id(messages)
    if current_wid != entry["worker_id"]:
        return None  # different sub-worker → nowa sesja
```

**Efekt:** Każdy sub-worker dostaje własną sesję DeepSeek, nawet jeśli system prompt jest ten sam.

---

## 🔧 Przekazywanie narzędzi (tools) do agenta

### ⚠️ UWAGA: Nowa sesja vs Resume

**NOWA SESJA (Tura 1):**
- IDE **zawsze** wysyła `tools: [...]`
- Proxy **musi** wysłać je do DeepSeek w `tools_schema`
- Zapisujemy je w `conv_state` dla przyszłych tur

**RESUME (Tura 2+):**
- IDE **często NIE wysyła** `tools: []` (pusta lista lub brak)
- Proxy **NIGDY nie wysyła** tools do DeepSeek (już są w sesji!)
- Używamy zapisanych tools z `state` dla fallback

### Problem
- **Nowa sesja:** IDE wysyła pełną listę `tools` → trzeba ją przekazać do DeepSeek
- **Resume:** IDE często **NIE wysyła** `tools` → trzeba użyć zapisanych z Tury 1


### Rozwiązanie: Persist tools w state

#### Kod: `server/services/proxy_service.py`

```python
async def chat_completions(self, raw_request: Request) -> Any:
    # Parse request
    raw_json = await raw_request.json()
    tools = list(raw_json.get("tools") or [])
    
    # Get conversation state
    messages = list(raw_json.get("messages", []))
    state = get_conv(messages)
    
    # Fallback: jeśli IDE nie wysłało tools, użyj zapisanych
    if not tools and state:
        tools = list(state.get("tools") or [])
        logger.info(f"[TOOLS FALLBACK] restored {len(tools)} tools from state")
    
    # ... later, after streaming:
    
    # Save state with tools
    set_conv(
        messages,
        chat_id,
        parent_id,
        account_idx,
        tools=tools  # ← Zapisane dla następnej tury
    )
```

### Budowanie promptu

#### NOWA SESJA (Tura 1)
```python
if not parsed.is_resume:
    prompt = PromptBuilder.build(
        user_message=user_message,
        system_prompt=system_prompt,      # ✅ Pełna preambuła
        history=history,                  # ✅ Poprzednie wiadomości (jeśli są)
        tools_schema=tools                # ✅ WSZYSTKIE narzędzia
    )
```

**Wynik:** Prompt zawiera:
```
You are an AI assistant...

Available Tools:
- Write(path, contents)
- Read(path)
- Execute(command)
[... wszystkie narzędzia ...]

[User]:
Write hello.py
```


#### RESUME (Tura 2+)
```python
if parsed.is_resume:
    prompt = PromptBuilder.build(
        user_message=user_message,
        system_prompt=None,               # ❌ Nie wysyłaj ponownie
        history=history,                  # ✅ TYLKO nowe tool results
        tools_schema=None                 # ❌ Już są w sesji DeepSeek
    )
```

**Wynik:** Prompt zawiera TYLKO:
```xml
<tool_result>
<t>Write</t>
<id>call_abc123</id>
<content>
File created successfully
</content>
</tool_result>

[User]:
Continue working on the task
```

**Dlaczego to działa:**
- DeepSeek sesja **pamięta** system prompt i tools z Tury 1
- Wysyłanie ich ponownie przy resume byłoby marnowaniem tokenów
- Wystarczy wysłać TYLKO nowe wyniki narzędzi

---

## 🚨 KRYTYCZNE ZASADY - PRZECZYTAJ TO!

### 1. Resume NIGDY nie jest początkiem rozmowy

```python
# ❌ ŹLE - zakładasz że resume = początek
if parsed.is_resume:
    # "To resume, więc muszę wysłać tools żeby model wiedział co ma dostępne"
    tools_schema = tools  # BŁĄD!

# ✅ DOBRZE - rozumiesz że resume = kontynuacja
if parsed.is_resume:
    # "To resume, więc tools JUŻ SĄ w sesji DeepSeek z Tury 1"
    tools_schema = None  # Poprawne!
```

### 2. Jeśli get_conv() zwróciło state - to resume!

```python
state = get_conv(messages)

if state is None:
    # Tura 1 - POCZĄTEK rozmowy
    # Wyślij: system_prompt + tools + user_message
    
if state is not None:
    # Tura 2+ - KONTYNUACJA
    # Wyślij TYLKO: tool_results + user_message
```

### 3. Tools w state są dla fallback, nie dla wysyłania

```python
# Fallback gdy IDE nie wysłało tools
if not tools and state:
    tools = state.get("tools")  # ✅ Przywróć z state
    
# Ale NIGDY nie wysyłaj ich do DeepSeek przy resume!
if parsed.is_resume:
    tools_schema = None  # ✅ Nie wysyłaj nawet jeśli masz!
```

---

## 6. Najważniejsze moduły

Architektura projektu została zorganizowana w modularne pakiety pod `server/`:

### 🌐 Warstwa API (`server/api/`)
- `routes.py`: Endpointy FastAPI (`/v1/chat/completions`, `/v1/chat/completions/dry-run`, `/v1/models`, `/v1/login`, `/v1/accounts`, `/health`).
- `deps.py`: Wstrzykiwanie zależności i singleton `ProxyService`.

### 🧠 Warstwa Core (`server/core/`)
- `deepseek_client.py`: Klient HTTP DeepSeek Web API (tworzenie sesji, autoryzacja, PoW solver & caching, streaming SSE, natywny `stream_continue`, upload plików).
- `input_parser.py`: Parsowanie, walidacja i czyszczenie payloadu OpenAI z IDE, routing modeli, detekcja formatu Vision.
- `prompt_builder.py`: Budowanie zunifikowanego promptu tekstowego w formacie DSML dla DeepSeeka (preambuła systemowa, schema narzędzi, blok wymuszenia agentic `_AGENTIC_FORCING_BLOCK`).
- `stream_handler.py`: Przetwarzanie strumienia SSE, detekcja i ekstrakcja wywołań narzędzi, przepisywanie MCP.
- `image_processor.py`: Ekstrakcja obrazów z payloadów OpenAI Vision (base64 oraz URL), przygotowanie do uploadu do API DeepSeeka.
- `mcp_catalog.py`: Zarządzanie schematami i katalogiem narzędzi MCP.

### ⚙️ Warstwa Usług (`server/services/`)
- `proxy_service.py`: Główny orchestrator żądań, streaming, pętla retry, session rollover, natywny continue oraz reprompt.
- `state_service.py`: Śledzenie stanu konwersacji (`conv_state.json`), stabilny algorytm hashowania wiadomości (`_msg_hash`), wykrywanie resume i subagentów.
- `rate_limiter.py`: Centralny, wielowątkowy zarządca limitów kont (`RateLimiter`).
- `account_selector.py`: Wybór optymalnego konta (sticky dla resume, najmniej obciążone dla nowych sesji) z uwzględnieniem rate limitów.
- `session_manager.py`: Zarządzanie liczbą aktywnych slotów na kontach.
- `auth_service.py`: Logowanie do DeepSeeka za pomocą przeglądarki i omijanie Cloudflare (`CloudflareBypasser`).
- `prompt_chunker.py`: Obsługa i podział gigantycznych promptów (>120k znaków) na pionowe łańcuchy w drzewie wiadomości.

### 🔍 Parsery i naprawa błędów (`server/parser/`, `server/repair/`)
- `dsml_sieve.py`: Filtr strumieniowy czasu rzeczywistego (wyłapuje XML `<tool_calls>` oraz chiński bracket syntax `[调用 Tool]`).
- `dsml_parser.py`: Parser XML/DSML i nawiasowych wywołań narzędzi.
- `repair_tier1.py`: Deterministyczna naprawa zniekształconych wywołań narzędzi przed wysłaniem do IDE.

---

## 🔧 DSML Tool Call Parsing & Repair

### Poprawny format DSML tool calls

Agent powinien używać tego formatu:

```xml
<tool_calls>
<invoke name="ToolName">
<parameter name="param1">value1</parameter>
<parameter name="param2">value2</parameter>
</invoke>
<invoke name="AnotherTool">
<parameter name="param">value</parameter>
</invoke>
</tool_calls>
```

**Kluczowe elementy:**
- `<tool_calls>` - wrapper dla wszystkich wywołań (może być `<|DSML|tool_calls>` lub `<|TOOL|tool_calls>`)
- `<invoke name="ToolName">` - pojedyncze wywołanie narzędzia (MUSI mieć `name` attribute!)
- `<parameter name="paramName">` - parametr (MUSI mieć `name` attribute!)
- Zamykające tagi: `</parameter>`, `</invoke>`, `</tool_calls>`

### Najczęstsze błędy agentów

#### ❌ BŁĄD #1: `<｜｜DSML｜｜>` zamiast `<invoke>`

```xml
<tool_calls>
<｜｜DSML｜｜>           ← BŁĄD!
<parameter name="x">value</parameter>
</invoke>              ← Correct close but wrong open
</｜｜DSML｜｜>          ← BŁĄD!
```

**Fix (automatyczny):** `_fix_malformed_dsml_invoke()` zamienia to na:
```xml
<tool_calls>
<invoke name="unknown">
<parameter name="x">value</parameter>
</invoke>
</invoke>
```

#### ❌ BŁĄD #2: Missing `name` attribute w `<invoke>`

```xml
<invoke>                ← BŁĄD: brak name="..."!
<parameter name="x">value</parameter>
</invoke>
```

**Nie ma automatycznego fixa** - parser nie wie jakie narzędzie wywołać.

#### ❌ BŁĄD #3: `string="true"` attribute w `<parameter>`

```xml
<parameter name="pattern" string="true">regex</parameter>
                          ↑ BŁĄD: niepoprawny attribute!
```

**Fix:** Parser ignoruje nieznane attributes, bierze tylko `name` i `content`.

### Repair pipeline (Tier 1)

Proxy automatycznie naprawia najczęstsze błędy w `server/repair/repair_tier1.py`:

```python
def repair_tier1(text: str, tool_names: list[str] | None = None) -> str | None:
    """Run text-level DSML/XML repair on *text*."""
    text = _fix_broken_namespace(text)        # |DSL| → |DSML|
    text = _fix_missing_lt(text)              # |TOOL|invoke → <|TOOL|invoke
    text = _fix_malformed_dsml_invoke(text)   # <｜｜DSML｜｜> → <invoke name="unknown">
    text = _strip_markdown_fences(text)       # Usuń ```xml...```
    text = _fix_unclosed_cdata(text)          # <![CDATA[...  → <![CDATA[...]]>
    text = _strip_leading_prose(text)         # Usuń tekst przed <tool_calls>
    text = _fix_tool_called_format(text)      # <tool_called> → <invoke>
    text = _fix_nested_invoke_mismatch(text)  # Napraw zagnieżdżone <invoke>
    text = _fix_damaged_invoke_opener(text)   # oke name="X"> → <invoke name="X">
    text = _fix_truncated_tag(text)           # Dokończ obcięte tagi
    return text
```

**Kolejność ma znaczenie!** Najpierw fixujemy namespace i missing brackets, potem strukturę.

### Debugging niepoprawnych tool calls

Gdy agent wysyła malformed tool calls, sprawdź logi:

```bash
# Główne logi proxy
tail -f deepseek-proxy/server_stdout.log | grep -i "tool_call\|dsml\|parse"

# Szukaj:
[HANDLER_EVENTS] ✅ tool_calls detected!  ← Parser znalazł tool calls
[HANDLER_EVENTS] events=['text']          ← Parser NIE znalazł (tylko text)
[RAW#2] {\"type\":\"error\"...            ← Błąd od DeepSeek API
```

**Jeśli `events=['text']` zamiast `['tool_calls', 'text']`:**
1. Agent użył niepoprawnego formatu
2. Repair pipeline nie naprawił błędu
3. Parser nie rozpoznał struktury jako tool calls
4. IDE traktuje odpowiedź jako text → rozmowa zatrzymana

**Rozwiązanie:**
1. Sprawdź content w logach - znajdź malformed XML
2. Dodaj nowy pattern do `repair_tier1.py` jeśli to recurring issue
3. Restart proxy żeby załadować fix

---
## 📝 Changelog

### 2026-09-07 v2.9 - FIX: Malformed DSML tool calls repair

**Root cause:** Agent czasami używa `<｜｜DSML｜｜>` jako tagu `<invoke>` zamiast prawidłowego formatu:

```xml
<tool_calls>
<｜｜DSML｜｜>           ← BŁĄD: To powinno być <invoke name="ToolName">
<parameter name="pattern">...</parameter>
</invoke>
</｜｜DSML｜｜>          ← BŁĄD: To powinno być </invoke>
</tool_calls>
```

Proxy nie mógł sparsować tego formatu → IDE traktowało odpowiedź jako text (bez tool calls) → rozmowa zatrzymana.

**Fix** w repair_tier1.py:
Dodano nową funkcję `_fix_malformed_dsml_invoke()` do pipeline:

```python
def _fix_malformed_dsml_invoke(text: str) -> str:
    """Fix <｜｜DSML｜｜> used as invoke tag instead of <invoke name="ToolName">."""
    # Replace standalone <｜｜DSML｜｜> or <|DSML|> with <invoke name="unknown">
    text = re.sub(
        r'<[｜|]+(?:DSML|TOOL)[｜|]+\s*>',
        '<invoke name="unknown">',
        text,
        flags=re.IGNORECASE,
    )
    # Replace standalone </｜｜DSML｜｜> with </invoke>
    text = re.sub(
        r'</[｜|]+(?:DSML|TOOL)[｜|]+\s*>(?!\s*/?tool_calls)',
        '</invoke>',
        text,
        flags=re.IGNORECASE,
    )
    return text
```

**Działanie po fixie:**
- PRZED: `<｜｜DSML｜｜>` → parser fails → text response
- PO: `<｜｜DSML｜｜>` → repaired to `<invoke name="unknown">` → parser success → tool calls detected

**Lokacja:** `server/repair/repair_tier1.py` (linia ~333)
**Pipeline:** Wywołane po `_fix_missing_lt()` w `repair_tier1()`

**Impact:**
- Agent może używać niepoprawnego formatu DSML i proxy automatycznie go naprawi
- IDE dostanie poprawne tool calls zamiast text response
- Rozmowa kontynuowana zamiast zatrzymana

### 2026-09-07 v2.8 - FIX: Hash collision detection & debug logging

**Root cause (diagnoza):** Wynik subagenta trafił jako NOWA SESJA zamiast RESUME do orchestratora.

**Problem #1:** `<system-reminder>Please continue...</system-reminder>` zmienia hash

IDE dodaje user message z `<system-reminder>` między turami. Po czyszczeniu przez `_clean_content()`,
message może zawierać INNE treści (np. skills), więc **NIE jest pomijany** i trafia do hasha jako
dodatkowa stable message → hash się zmienia → state nie znaleziony → NEW SESSION!

**Problem #2:** Subagent result notification zmienia zestaw messages

IDE wysyła **inny zestaw user messages** po zakończeniu subagenta:
- Turn 1 (orchestrator): `[user_info, manually_attached_skills, user_query]` → 4 messages w hashu
- Turn 2 (po subagent): `[user_info, user_query]` (BEZ skills!) → 3 messages w hashu → INNY HASH!

**Fix** w state_service.py:
Dodano szczegółowe debug logging dla diagnozy:

```python
# W _msg_hash():
debug_log.debug(f"[MSG_HASH] user #{user_count} RAW: {raw_preview!r}")
debug_log.debug(f"[MSG_HASH] user #{user_count} CLEAN: {clean_preview!r}")
debug_log.debug(f"[MSG_HASH] Added user msg #{user_count}: {content[:100]!r}...")

# W _clean_content():
before_reminder = text[:200]
text = _SYSTEM_REMINDER_RE.sub("", text)
after_reminder = text[:200]
if before_reminder != after_reminder:
    debug_log.debug(f"[CLEAN] Stripped <system-reminder>: before={before_reminder!r} after={after_reminder!r}")
```

**Output:** `debug_state.log` zawiera:
- Dokładnie jakie user messages trafiają do hasha (RAW vs CLEAN)
- Co jest usuwane przez `_clean_content()`
- Dlaczego hash się zmienia między turami

**Status:** DIAGNOZA - fix wymaga dalszej analizy logów z produkcji. Możliwe rozwiązania:
1. Wykluczyć więcej volatile content z `_clean_content()`
2. Zmienić strategię haszowania (np. brać TYLKO system + pierwszy user_query, ignorując skills/attachments)
3. Dodać normalizację kolejności user messages przed haszowaniem

**Lokacja:** `server/services/state_service.py`
**Debug log:** `debug_state.log` w root projektu

### 2026-09-07 v2.7 - FIX: Missing _TOOL_IN_SYSTEM_RE regex

**Root cause:** Kod w `input_parser.py` linia 83 używał `_TOOL_IN_SYSTEM_RE.search(content)` ale
regex **nie był zdefiniowany** na początku pliku → `NameError: name '_TOOL_IN_SYSTEM_RE' is not defined`
→ proxy crash przy każdym requestcie.

**Fix** w input_parser.py:
```python
# Pattern to detect if tools schema is already embedded in system prompt
_TOOL_IN_SYSTEM_RE = re.compile(r"<tool_call|Available Tools:|function_name|tool_choice", re.IGNORECASE)
```

Dodano po `_SYS_TAG_START_RE` (linia ~35).

**Użycie:**
```python
# Detect if tools are already in system prompt
has_tools = False
for m in messages:
    if m.get("role") == "system":
        content = m.get("content", "")
        if isinstance(content, str) and _TOOL_IN_SYSTEM_RE.search(content):
            has_tools = True
            break
```

**Impact:**
- Przed: Proxy crash z NameError przy każdym requestcie
- Po: Proxy działa, wykrywa czy tools są w system prompt

**Lokacja:** `server/core/input_parser.py` (linia ~35)


### 2026-09-05 v2.6 - FIX: Hash collision przy różnych user queries

**Root cause:** IDE wysyła 2-3 user messages na początku konwersacji:
1. `<user_info>` (workspace path, OS, shell)
2. `<user_query>` (actual user message - RÓŻNY między konwersacjami!)
3. `<manually_attached_skills>` (opcjonalnie)

`_msg_hash()` brał tylko PIERWSZĄ user message (MAX_USERS = 1), więc hash był z:
- system prompt
- user_info (workspace path)

**user_query NIE WCHODZIŁ do hashu!** Efekt: dwie RÓŻNE konwersacje w tym samym workspace
(np. "audit bot" vs "create implementation plan") miały TEN SAM HASH i resumowały tę samą
sesję DeepSeek.

**Przykład konfliktu:**
```
Konwersacja A (16:35): "You are auditing a Vinted bot..."
  hash = H([system, user_info]) = 'b44ca3d65672b18c'
  
Konwersacja B (21:51): "You are producing IMPLEMENTATION PLAN..."
  hash = H([system, user_info]) = 'b44ca3d65672b18c'  ← TEN SAM!
  
get_conv() znalazł match → BŁĘDNIE resumowało sesję A dla konwersacji B
```

**Fix** w _msg_hash() (state_service.py):
```python
MAX_USERS = 3  # było: 1
```

Teraz hash bierze pierwsze 3 user messages:
- user_info (workspace)
- user_query (actual message - **RÓŻNY!**)
- skills (optional)

**Impact:**
- Przed: `hash('b44ca3d65672b18c')` dla obu konwersacji → collision
- Po: różne hashe bo user_query jest included → no collision

**Testy:** Kompilacja OK, wymaga restartu proxy i manual verification.

### 2026-09-04 v2.1 - FIX: tools schema na poczatku rozmowy

**Root cause:** IDE wysyla kilka role:user messages na starcie konwersacji
(np. user_info + user_query). _extract_prompt_parts traktowal tylko OSTATNI
jako user_message, a wczesniejsze trafialy do history. PromptBuilder budowal
prompt z niepustym history zamiast wyslac wszystko jako user_message razem
z tools_schema. Efekt: tools schema nie trafialo do pierwszego promptu.

**Impact:**
- Przed: `[TOOLS_POST_BUILD] ❌ Tools schema MISSING from prompt!`
- Po: `[TOOLS_POST_BUILD] ✅ Tools schema IN prompt (41KB schema added)`
- Model teraz widzi wszystkie narzedzia i moze ich uzywac poprawnie



### 2026-09-07 v2.10 - FIX: orphaned </tool_calls> closing tag repair

**Root cause:** Agent czasami generuje poprawny DSML <invoke> ale **bez opening <tool_calls> tag**:
```xml
<invoke name="Grep">
  <parameter name="pattern">...</parameter>
</invoke>
</tool_calls>  <- orphaned closing tag!
```

**Symptom:** 
- StreamSieve wykrywa <invoke> i parsuje poprawnie
- _extract_post_wrapper() usuwa orphaned </tool_calls> jako debris
- **ALE** brak <tool_calls> wrapper powoduje że parser nie rozpoznaje tego jako kompletnego tool call block
- Rezultat: tool call trafia do IDE jako plain text zamiast JSON tool_use

**Fix** w 
epair_tier1.py:
Dodano nową funkcję _fix_orphaned_tool_calls_close() która:
1. Wykrywa przypadek: ma </tool_calls> ALE NIE MA <tool_calls>
2. Znajduje pierwszy <invoke> tag
3. Dodaje brakujący <tool_calls> opening tag przed <invoke>

```python
def _fix_orphaned_tool_calls_close(text: str) -> str:
    has_close = re.search(r'</(?:\|?(?:TOOL|DSML)\|)?tool_calls?\s*>', text, re.IGNORECASE)
    has_open = re.search(r'<(?:\|?(?:TOOL|DSML)\|)?tool_calls?\s*>', text, re.IGNORECASE)
    
    if has_close and not has_open:
        invoke_match = re.search(r'<(?:\|?(?:TOOL|DSML)\|)?invoke\s', text, re.IGNORECASE)
        if invoke_match:
            insert_pos = invoke_match.start()
            text = text[:insert_pos] + '<tool_calls>\n' + text[insert_pos:]
    return text
```

**Wywołanie:** Dodane w 
epair_tier1() pipeline po _fix_tool_called_format().

**Test case:**
```python
# Input:
<invoke name="Grep">
<parameter name="pattern">per-trasa|OBALONE</parameter>
</invoke>
</tool_calls>

# Output after repair:
<tool_calls>
<invoke name="Grep">
<parameter name="pattern">per-trasa|OBALONE</parameter>
</invoke>
</tool_calls>
```

**Impact:**
- Przed: Tool call wyciekał jako plain text do IDE → brak execution
- Po: Tool call poprawnie sparsowany do JSON → IDE wykonuje

**Testy:** Manual verification passed (test_orphaned.py)

### 2026-09-04 v2.0 - KRYTYCZNA AKTUALIZACJA
- ⚠️ **DODANO:** Sekcja "RESUME NIGDY NIE JEST POCZĄTKIEM ROZMOWY"
- ⚠️ **ZMIENIONO:** Wszystkie przykłady jasno pokazują że resume = Tura 2+
- ⚠️ **DODANO:** Sekcja "Najczęstszy błąd agentów"
- ⚠️ **DODANO:** Sekcja "KRYTYCZNE ZASADY"
- ✅ Poprawiono dokumentację lifecycle (jasny podział Tura 1 vs Tura 2+)

### 2026-09-04 v1.0
- ✅ Utworzono AGENTS.md
- ✅ Udokumentowano resume detection logic
### 2026-09-04 v2.0 - KRYTYCZNA AKTUALIZACJA
- ⚠️ **DODANO:** Sekcja "RESUME NIGDY NIE JEST POCZĄTKIEM ROZMOWY"
- ⚠️ **ZMIENIONO:** Wszystkie przykłady jasno pokazują że resume = Tura 2+
- ⚠️ **DODANO:** Sekcja "Najczęstszy błąd agentów"
- ⚠️ **DODANO:** Sekcja "KRYTYCZNE ZASADY"
- ✅ Poprawiono dokumentację lifecycle (jasny podział Tura 1 vs Tura 2+)

### 2026-09-04 v1.0
- ✅ Utworzono AGENTS.md
- ✅ Udokumentowano resume detection logic
- ✅ Udokumentowano MCP catalog & rewrite
- ✅ Udokumentowano subagent routing
- ✅ Dodano diagramy sekwencji
- ✅ Dodano debugging tips

### 2026-09-08 v2.13 - FIX: Natychmiastowe utrwalanie parent_id i eliminacja rozgałęzień drzewa (< 1 / 2 >)
- 🐛 **ROOT CAUSE (Rozgałęzienie drzewa wiadomości w DeepSeek Web Chat):**
  - **Opóźnione utrwalanie stanu:** Proxy aktualizowało `parent_id` w `conv_state` dopiero po całkowitym zakończeniu strumienia odpowiedzi (`_save_state`). W efekcie podczas trwania fazy myślenia (trwającej 30–120s) lub po niespodziewanym przerwaniu strumienia / restarcie proxy / retry z IDE, w `conv_state` pozostawał stary `parent_id`. Kolejny request trafiał do DeepSeeka z identycznym rodzicem, co powodowało powstanie rodzeństwa (siblings: `< 1 / 2 >` i `< 2 / 2 >`) i odcięcie gałęzi z wynikami narzędzi!
  - **Pusta delta po przerwaniu strumienia:** Gdy Cursor przysyłał ponowienie, w którym ostatnią wiadomością był `assistant`, algorytm delty (`delta_msgs = all_msgs[last_asst_idx + 1 :]`) zwracał pustą listę. W efekcie `PromptBuilder.build` generował prompt złożony wyłącznie z nagłówka `[User]:` i `_AGENTIC_FORCING_BLOCK` (464 znaki), który jako wersja 2/2 nadpisywał wyniki narzędzi z wersji 1/2!
- 🚀 **ROZWIĄZANIE:**
  - **Wczesne utrwalanie (`Early Persistence`):** W `proxy_service.py` natychmiast po wywołaniu `ds.stream_completion()`, gdy znane jest `resp_msg_id` z preambuły, stan sesji jest zapisywany w `conv_state`. Każdy kolejny request, retry czy wznowienie od pierwszej sekundy jest zawsze dopinane pod nowy węzeł.
  - **Zabezpieczenie pustej delty:** Jeśli `delta_msgs` jest puste (ostatnia wiadomość to `assistant`), automatycznie wstrzykiwany jest komunikat `Continue`, a `PromptBuilder.build` pomija puste nagłówki `[User]:`.
- 🧪 **Testy:** Wszystkie 62 testy jednostkowe przechodzą pomyślnie.

### 2026-09-08 v2.12 - FIX: Obsługa BATCH SSE i likwidacja przedwczesnego zatrzymywania myślenia subagenta
- 🐛 **ROOT CAUSE 1 (Bezwarunkowy `break` na pakietach BATCH):**
  - W `server/core/deepseek_client.py` pętla czytająca strumień SSE natrafiając na pakiet `{"o": "BATCH", ...}` wykonywała bezwarunkowy `break` z głównej pętli generatora (przez błędne wcięcie `break` poza wewnętrzną pętlą sprawdzającą `quasi_status == "FINISHED"`).
  - Ponieważ DeepSeek co kilka sekund wysyła w strumieniu pakiety `BATCH` (np. z aktualizacją zużycia tokenów lub metadanych), strumień był natychmiastowo zrywany w trakcie fazy myślenia (thinking).
- 🐛 **ROOT CAUSE 2 (Wyciek myśli jako odpowiedź asystenta):**
  - Gdy strumień urwał się przed wystąpieniem nagłówka `RESPONSE` (`response_started == False`), blok awaryjny `if not response_started:` brał cały dotychczasowy `content_buffer` (zawierający myśli modelu z fazy thinking) i yieldował go do Cursora jako normalną treść odpowiedzi asystenta.
  - Cursor odbierał te myśli jako kompletną odpowiedź (200 OK + `finish_reason: "stop"`), nie widział żadnych `tool_calls` i zamykał turę subagenta (`turn_ended, status: success`), zatrzymując jego działanie.
- 🚀 **ROZWIĄZANIE:**
  - W `deepseek_client.py` pakiety `BATCH` są teraz bezpiecznie rozwijane (`items = data["v"]`): aktualizacje metadanych i tokenów nie przerywają już strumienia, a wyjście następuje wyłącznie po odebraniu `FINISHED`.
  - Zabezpieczono pre-response fallback: przy włączonym myśleniu (`thinking_enabled == True`) niedokończone myśli są zachowywane w `result_meta["thinking_fallback"]` i NIE są yieldowane jako odpowiedź asystenta.
- 🧪 **Testy:** Dodano `tests/test_deepseek_client_stream.py` (3 testy) – wszystkie testy jednostkowe (47 passed) przechodzą.

---

## 8. Multi-Part Chunked Prompt Injection i struktura drzewa wiadomości

### ⚠️ Limit długości pojedynczego requestu DeepSeek Web API
Oficjalne Web API DeepSeek (`/api/v0/chat/completion`) posiada twardy limit długości pojedynczego promptu:
* Zgłoszenia o wielkości powyżej **~120 000 – 128 000 znaków** (np. duże odczyty plików z wielu `tool_result`) są odrzucane:
  ```json
  {"finish_reason": "input_exceeds_limit", "content": "Content is too long. Please shorten it and try again."}
  ```
* Aby obsłużyć duże wyniki narzędzi (np. 150k–300k+ znaków) bez ucinania treści, proxy stosuje **Multi-Part Chunked Prompt Injection**.

### 🧩 Mechanizm działania Chunkera (`server/services/prompt_chunker.py`)
1. **Próg podziału:** `PROMPT_CHUNK_THRESHOLD = 120 000` znaków.
2. **Semantyczny podział:**
   - Prompt jest dzielony wzdłuż granic bloków `<tool_result>...</tool_result>`.
   - Jeśli pojedynczy plik wewnątrz `<content>` przekracza próg, zostaje podzielony na mniejsze części z nagłówkiem kontynuacji `[SYSTEM NOTE: File content continued in next part...]`.
   - Bloki wymuszenia agenta (`_AGENTIC_FORCING_BLOCK`) oraz marker `[Assistant]:` są dołączane **wyłącznie do ostatniej części**.

### 📡 Przepływ wstrzykiwania interim chunków (`server/core/deepseek_client.py` & `proxy_service.py`)
Każda część przedostatnia (interim chunk) jest rejestrowana w DeepSeek Web Chat bez generowania odpowiedzi asystenta:
```
IDE wysyła prompt (175k znaków) -> podział na 3 części:
  1. ds.send_interim_chunk(part 1, parent_id=P0)
     -> DeepSeek zwraca response_message_id=R1 w SSE
     -> Proxy natychmiast zamyka strumień (r.close())
     -> Aktualizacja parent_id = R1 oraz conv_state
  2. ds.send_interim_chunk(part 2, parent_id=R1)
     -> DeepSeek zwraca response_message_id=R2
     -> Proxy zamyka strumień
     -> Aktualizacja parent_id = R2 oraz conv_state
  3. ds.stream_completion(part 3 [final], parent_id=R2)
     -> Model w chmurze ma w kontekście część 1, 2 i 3!
     -> Strumieniowanie odpowiedzi asystenta do IDE.
```

### 🌳 Struktura drzewa wiadomości DeepSeek i unikanie edycji rodzeństwa (`< 1 / 4 >`)
DeepSeek Web Chat przechowuje konwersacje jako **drzewo acykliczne**:
* **Węzły-rodzeństwo (siblings):** Jeśli dwa zapytania użytkownika wskażą ten sam `parent_message_id`, DeepSeek traktuje je jako **edycję/regenerację tej samej tury** i tworzy w UI przełącznik wersji: `< 1 / N >`.
* **Zagrożenie:** W aktywnym kontekście modelu liczy się **wyłącznie aktualnie wybrana gałąź** (domyślnie ostatnia). Wszelkie narzędzia z odciętych gałęzi wypadają z kontekstu!
* **Prawidłowy łańcuch pionowy:** Każdy kolejny chunk MUSI mieć jako rodzica odpowiedź asystenta z poprzedniego kroku (`P0 -> R1 -> R2 -> ...`).
* **Zabezpieczenie przed powtarzaniem (retry guard) i obsługa fallbacków:**
  - W `send_interim_chunk` zaimplementowano automatyczną obsługę `INVALID_POW_RESPONSE` (reset cache PoW i retry) oraz retry dla błędów sieciowych `CurlError` (do 3 prób).
  - W `proxy_service.py` cała orkiestracja chunków została wydzielona do asynchronicznej metody `_orchestrate_chunks_if_needed`.
  - **Krytyczne:** `_orchestrate_chunks_if_needed` jest wywoływana NIE TYLKO przed główną pętlą zapytań, ale także w ścieżkach awaryjnych:
    - w handlerze `[EMPTY RESUME]` (gdy DeepSeek odrzuci sesję błędem `message still wip` i proxy tworzy nową sesję, odbudowując pełny prompt z historii wiadomości),
    - w handlerze `[LENGTH RETRY]` (gdy sesja jest resetowana).
    Dzięki temu żaden nowo wygenerowany prompt > 120 000 znaków nie trafi bezpośrednio do API bez podziału na chunki.
  - Po każdym udanym wstrzyknięciu natychmiast zapisywany jest stan w `conv_state`, dzięki czemu nawet przy awarii kolejne zapytanie z IDE kontynuuje od zarejestrowanego węzła, zamiast uderzać w starego rodzica.

---

## 9. Obsługa niestandardowych formatów Tool Calls (Chinese Bracket Calls `[调用 ToolName]`)

### ⚠️ Problem z chińskim formatem nawiasowym `[调用 ToolName]`
W pewnych okolicznościach DeepSeek Pro emituje wywołania narzędzi w chińskim formacie nawiasowym:
```
[调用 Read] {"path": "F:/PROJEKTY/vinted/.superpowers/sdd/task-C1-brief.md"}
```
zamiast oczekiwanego formatu XML DSML (`<tool_calls><invoke name="Read">...</invoke></tool_calls>`).

**Skutek braku obsługi:**
1. `StreamSieve` traktował ciąg `[调用 Read] {...}` jako zwykłą prozę (`text chunk`), ponieważ nasłuchiwał wyłącznie na znaczniki XML (`<tool_calls>`, `<invoke`, itp.).
2. Tekst ten był bezpośrednio emitowany do IDE jako zwykła odpowiedź tekstowa asystenta.
3. IDE (np. Cursor) interpretowało to jako finalną wypowiedź asystenta (`turn_ended`), zamiast wywołać narzędzie (`tool_use`), co całkowicie blokowało pracę subagenta.

### 🛡️ Wdrożona architektura detekcji i normalizacji (v2.15)
Wprowadzono wielowarstwową ochronę (Defense in Depth):

1. **Wykrywanie w strumieniu czasu rzeczywistego (`server/parser/dsml_sieve.py`):**
   - Dodano prefiksy wywołań nawiasowych do `TOOL_STARTS`: `"[调用"`, `"【调用"`, `"[call "`, `"[invoke "`.
   - `_find_tool_start`: wykrywa początek wywołania za pomocą `_BRACKET_OPENER_RE` równolegle z tagami XML.
   - `_split_safe`: zatrzymuje urwane w połowie chunka prefiksy (np. `[`, `[调`, `[调用`, `[call`) w buforze `_pending`, zapobiegając wyciekowi fragmentów tagu jako tekstu do IDE.
   - `_is_capture_complete`: weryfikuje kompletność obiektu JSON `{...}` za nagłówkiem `[调用 ToolName]` przy pomocy dekodera JSON `raw_decode`.
   - `_try_finish_capture` oraz `_extract_post_wrapper`: wyodrębniają sparsowane wywołanie i ewentualny tekst po domknięciu nawiasu JSON.

2. **Parser i normalizacja (`server/parser/dsml_parser.py`):**
   - Funkcja `parse_bracket_tool_calls(text, tool_names)` parsuje wywołania `[调用 ToolName] {json}`, mapując je na standardowy format `{name: ..., arguments: json_str}`.
   - Wpięta jako fallback bezpośrednio w `parse_dsml_tool_calls`.

3. **Naprawa strukturalna (`server/repair/repair_tier1.py`):**
   - Funkcja `_fix_bracket_call_format(text)` automatycznie przepisuje wywołania `[调用 ToolName] {json}` na kanoniczny XML DSML:
     ```xml
     <tool_calls>
       <invoke name="ToolName">
         <parameter name="key"><![CDATA[value]]></parameter>
       </invoke>
     </tool_calls>
     ```
   - Rozpoznawanie w `_has_tool_tag`.

4. **Wymuszenie w promptach (`server/core/prompt_builder.py`):**
   - W `_TOOL_FORMAT_INSTRUCTION` oraz `_AGENTIC_FORCING_BLOCK` dodano jawny zakaz używania składni `[调用 ToolName]` / `[call ToolName]` i bezwzględny nakaz stosowania tagów XML `<tool_calls><invoke name="...">`.

---

## 10. Obsługa tagów potomnych i restartu wywołania (Stutter & Sibling Tags `description`)

### ⚠️ Problem pustych wywołań w terminalu IDE (`&` lub `$`)
Gdy model DeepSeek emitował wywołania powłoki z dodatkowymi tagami (np. `<description string="true">Commit C6</description>`) lub zrestartował blok (`<tool_calls><invoke name="Shell"><tool_calls><invoke name="Shell">...`), w IDE pojawiało się puste wywołanie albo sam znak promptu terminala (`&` lub `$`).

**Przyczyny źródłowe:**
1. **Błędna heurystyka fałszywego domknięcia (`fake close`) w `_parse_parameters`:**
   Wcześniejszy kod zakładał, że po `</parameter>` musi natychmiast wystąpić `<parameter` lub `</invoke>`. Gdy model wyemitował tag rodzeństwa `<description string="true">...`, parser uznał poprawny `</parameter>` za tekst kodu wewnątrz parametru i szukał dalej, co zerowało wartość parametru `command` do pustego ciągu `""`.
2. **Pomijanie tagów rodzeństwa z atrybutami:**
   Tagi takie jak `<description string="true">val</description>` były ignorowane przez fallback, ponieważ fallback wymagał braku atrybutów oraz pustego słownika `args`.
3. **Stutter (zrestartowany nagłówek bez parametrów):**
   Model najpierw wyemitował ucięty `<invoke name="Shell">`, a zaraz po nim pełny `<invoke name="Shell">`. Pierwszy trafiał do IDE z pustymi argumentami `{}`, a drugi z `{"command": ""}`.
4. **Niewłaściwa naprawa w `_fix_nested_invoke_mismatch`:**
   Zamieniała drugi `<invoke name="Shell">` na `<parameter name="Shell">`, bo widziała go wewnątrz niezamkniętego pierwszego wywołania.

### 🛡️ Rozwiązanie (v2.16)
1. **Precyzyjna detekcja domknięcia w `_parse_parameters`:**
   Tag `</parameter>` jest uznawany za fałszywy **wyłącznie wtedy**, gdy tekst po nim nie zaczyna się od znacznika XML (nie zaczyna się od `<`). Obecność dowolnego innego tagu rodzeństwa (np. `<description>`, `<arg>`, `</invoke>`) jest w pełni honorowana jako prawidłowy koniec parametru.
2. **Parsowanie tagów potomnych obok `<parameter>`:**
   Tagi potomne (w tym z atrybutami jak `string="true"`) są automatycznie uzupełniane do argumentów wywołania.
3. **Filtrowanie zduplikowanych pustych wywołań (`stutter filter`):**
   W `parse_dsml_tool_calls` puste wywołania narzędzi (np. `Shell` z `{}` lub `{"command": ""}`) są automatycznie usuwane, jeśli w tym samym zapytaniu istnieje to samo narzędzie z prawidłowymi argumentami.
4. **Zabezpieczenie `_fix_nested_invoke_mismatch`:**
   Wywołanie posiadające własne tagi `<parameter>` lub poprzedzone nowym kontenerem `<tool_calls>` nie jest już błędnie konwertowane na parametr.

---

## 11. Obsługa wywołań w buforze myślenia i uszkodzonych openerów (Thinking Fallback & `ToolMgr.try_parse`)

### ⚠️ Problem: wywołanie narzędzia trafia do IDE jako tekst asystenta zamiast tool call
Gdy model DeepSeek generuje odpowiedź bez jawnego nagłówka fragmentu `RESPONSE` (np. wygenerowanie kodu narzędzia w sekwencji myślenia lub nagłe zakończenie strumienia sygnałem `FINISHED` z `response_started=False`), treść trafia do bufora `thinking_fallback`.
Jeśli dodatkowo model wyemitował uszkodzony opener (np. zgubił prefiks `<inv` i zaczął od `oke name="Shell">`), wywołanie nie wykonywało się w IDE, lecz pojawiało się w oknie czatu jako surowy XML odpowiedzi asystenta (`role: "assistant", content: "oke name="Shell">..."`).

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Brak nagłówka `RESPONSE` z DeepSeek Web API:**
   API DeepSeek zakończyło strumień (`response/status: FINISHED`) bez wyemitowania fragmentu typu `RESPONSE`. Cały wygenerowany bufor (550 znaków) trafił do `result_meta["thinking_fallback"]`.
2. **Pominięcie pipeline'u naprawczego w `proxy_service.py`:**
   W `proxy_service.py` (linia ~664) obsługa `thinking_fallback` wywoływała bezpośrednio surowy parser `parse_dsml_tool_calls(thinking_fallback, tool_names)` zamiast zintegrowanego menedżera `ToolMgr.try_parse(thinking_fallback, tool_names)`.
3. **Porażka surowego parsera na uciętym `<inv`:**
   Surowy `parse_dsml_tool_calls` nie zawiera naprawy Tier 2 (`_fix_damaged_invoke_opener`), dlatego dla ciągu `oke name="Shell">...` zwrócił pustą listę `[]`.
4. **Wyciek jako czysty tekst:**
   Gdy `fb_result` było puste, proxy przechodziło do gałęzi `elif not text_buffer.strip(): yield _chunk({"content": thinking_fallback})`, emitując cały surowy kod XML do IDE jako zwykłą wypowiedź asystenta. IDE zapisywało to jako treść czatu bez wykonywania powłoki bash/git.

### 🛡️ Rozwiązanie (v2.17)
- **Pełny pipeline naprawy w `thinking_fallback`:**
  W `server/services/proxy_service.py` podmieniono wywołanie na:
  ```python
  fb_result = (
      ToolMgr.try_parse(thinking_fallback, tool_names)
      if thinking_fallback
      else []
  )
  fb_result = ToolMgr.validate(fb_result, tool_names)
  ```
  Dzięki temu każdy tool call uwięziony w `thinking_fallback` przechodzi przez:
  - **Tier 1:** Standardowy DSML.
  - **Tier 2:** `repair_pipeline` (w tym `_fix_damaged_invoke_opener` odzyskujący brakujący `<inv`, `_fix_orphaned_tool_calls_close`, itp.).
  - **Tier 3-5:** Formaty JSON, naprawy skróconych bloków i fallbacki legacy.
- **Wynik:** Wywołanie zostaje poprawnie zidentyfikowane, opakowane w strukturę `tool_calls` OpenAI i wyemitowane z `finish_reason: "tool_calls"`.

---

## 12. Zakaz przerywania strumienia na `quasi_status` (Quasi Reasoning vs Response)

### ⚠️ Problem: model urywa odpowiedź po zakończeniu myślenia (thinking) i zatrzymuje rozmowę
W trybie myślenia (`thinking_enabled: True`) model generował krótki proces myślowy (np. 200–800 znaków), po czym proxy natychmiast kończyło strumień (`data: [DONE]`), emitowało treść myśli jako tekst odpowiedzi asystenta i zamykało turę z `finish_reason: "stop"`. W IDE powodowało to natychmiastowe zablokowanie agenta bez wykonania jakichkolwiek wywołań narzędzi.

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Wewnętrzny protokół DeepSeek Web:**
   W oficjalnym backendzie DeepSeek Web przetwarzanie odpowiedzi z włączonym wnioskowaniem dzieli się na etapy:
   - **Etap "quasi" (reasoning / myślenie / query planning):** Stan tego podetapu jest raportowany polem `quasi_status`. Gdy model kończy myśleć, backend wysyła event:
     ```json
     {"p": "quasi_status", "v": "FINISHED"}
     ```
     Oznacza to jedynie: **„Faza myślenia została zakończona, teraz następuje faza właściwej odpowiedzi (RESPONSE)”**.
   - **Prawdziwy koniec całej odpowiedzi:** To wyłącznie:
     ```json
     {"p": "response/status", "o": "SET", "v": "FINISHED"}
     ```
     oraz naturalne wyczerpanie strumienia HTTP (`iter_lines`).
2. **Błędny warunek w `deepseek_client.py`:**
   W `server/core/deepseek_client.py` warunek przerywający pętlę strumienia zawierał:
   ```python
   # KOD PRZED POPRAWKĄ (BŁĘDNY):
   if (
       (path == "response/status" and op == "SET" and val == "FINISHED")
       or (path == "quasi_status" and val == "FINISHED")       # ❌ BŁĄD!
       or (item.get("quasi_status") == "FINISHED")             # ❌ BŁĄD!
   ):
       stream_finished = True
       break  # ❌ ROZŁĄCZAŁO GNIAZDO HTTP!
   ```
   W momencie gdy model kończył myśleć, proxy widziało słowo `"FINISHED"`, natychmiast robiło `break`, zamykało połączenie HTTP do DeepSeeka i odcinało nadejście fragmentu `RESPONSE` z kodem narzędzi.

### 🛡️ Rozwiązanie (v2.18)
- Usunięto `quasi_status == "FINISHED"` z warunku przerywającego strumień.
- `quasi_status == "FINISHED"` jest obecnie wyłącznie logowane (`[DS_QUASI] quasi stage completed`) i ignorowane (`continue`), pozwalając na swobodne przejście do fazy właściwej odpowiedzi.
- Jedynym dopuszczalnym sygnałem zakończenia strumienia jest `path == "response/status" and op == "SET" and val == "FINISHED"` lub naturalne zakończenie iteratora HTTP.

---

## 13. Obsługa błędów chwilowej niedostępności klastra (Transient Cluster Errors: `Server is temporarily unavailable.`)

### ⚠️ Problem: Błąd `Server is temporarily unavailable.` zrywa strumień z kodem błędu w oknie czatu
Podczas wysokiego obciążenia klastra DeepSeek Web API (HTTP 503 / SSE error payload), w strumieniu SSE z DeepSeek Web pojawia się pakiet:
```json
{"type": "error", "content": "Server is temporarily unavailable."}
```
W logach proxy pojawia się wpis:
```
[ERROR] DeepSeek SSE error mid-stream: Server is temporarily unavailable.
[STREAM ERROR] DeepSeek error: Server is temporarily unavailable.
```
Zamiast ponowić próbę (backoff) lub obsłużyć błąd w sposób transparentny dla IDE, proxy natychmiast kończyło strumień i emitowało błąd bezpośrednio jako treść odpowiedzi:
```
[Stream error: DeepSeek error: Server is temporarily unavailable.]
```
Po stronie IDE (np. Kiro / Cursor) zamykało to turę ze statusem błędu i zmuszało użytkownika do ręcznego ponawiania pytania.

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Niepełna lista fraz w klasyfikacji błędów przejściowych (`is_rate` / `_RATE_ERRORS`):**
   W `server/services/proxy_service.py` (`_stream_gen` oraz `chat_completions`) lista fraz kwalifikujących błąd jako przeciążenie/rate limit zawierała:
   `("busy", "rate_limit", "too frequent", "try again later", "too many requests", "service unavailable")`.
   Komunikat DeepSeeka: `"Server is temporarily unavailable."` NIE zawierał żadnej z powyższych fraz (brakowało słów `"unavailable"` i `"temporarily unavailable"`).
2. **Ominięcie mechanizmu `STREAM BACKOFF`:**
   W `_stream_gen` proxy posiada już bezpieczny mechanizm ponawiania na tej samej sesji:
   `_STREAM_BACKOFF = [3, 6, 12, 20]`.
   Gdy żaden token nie został jeszcze wysłany do IDE (`content_already_sent == False`), ponowienie jest całkowicie bezpieczne (brak ryzyka zdublowania odpowiedzi w IDE).
   Ponieważ jednak `is_rate` zostało ocenione jako `False`, proxy uznało błąd 503 za błąd fatalny i natychmiast wyemitowało go do klienta:
   `yield _chunk({"content": f"\n\n[Stream error: {err_str}]"})`.

### 🛡️ Rozwiązanie (v2.19)
1. **Rozszerzenie klasyfikacji błędów o `"unavailable"` i `"temporarily unavailable"`:**
   - W `server/services/proxy_service.py` w `_stream_gen` dodano frazy do krotki `is_rate`.
   - W `proxy_service.py` w `chat_completions` dodano frazy do `_RATE_ERRORS` oraz zapewniono porównanie `err_str.lower()`.
   - W `server/core/deepseek_client.py` w `send_interim_chunk` dodano `"unavailable"` do listy wykrywania rate-limit / błędu serwera.
2. **Łagodny jitter dla błędów przejściowej niedostępności (transient 503):**
   - Dla `"server is busy"` oraz `"unavailable"` stosowany jest krótki jitter (15–25s) zamiast pełnego 60–120s twardego rate-limitu konta.
3. **Automatyczny `STREAM BACKOFF` na tej samej sesji:**
   - Gdy do klienta nie wysłano jeszcze treści (`not content_already_sent`), strumień wchodzi w pętlę retry `[3, 6, 12, 20]` sekund na **tej samej sesji** (`chat_id`, `parent_id`), całkowicie ukrywając chwilową niedostępność węzła DeepSeek przed IDE.
4. **Zabezpieczenie przed duplikacją tekstu:**
   - Jeśli część treści asystenta zdążyła już trafić do IDE (`content_already_sent == True`), ponowienie nie jest wykonywane, a użytkownik otrzymuje czytelny komunikat błędu (zapobiega to zdublowaniu wygenerowanego kodu w oknie IDE).

---

## 14. Automatyczny Re-prompt przy przedwczesnym zamilknięciu agenta (Auto-reprompt on Premature Stop without Tool Calls)

### ⚠️ Problem: Model urywa wypowiedź po zapowiedzi intencji (np. `Let me run the test script.`) i zatrzymuje całą pętlę agenta
Podczas pracy autonomicznego agenta po odebraniu wyników wykonania narzędzia (`role: "tool"` lub `<tool_result>`), model DeepSeek generuje w buforze myślenia krótką zapowiedź intencji (np. *„Let me run the test script.”* lub *„Teraz utworzę kolejny plik”*), po czym oficjalny backend DeepSeek Web nagle przysyła sygnał:
```
response/status: SET FINISHED
```
bez wygenerowania fragmentu właściwej odpowiedzi (`RESPONSE`), ani bez wygenerowania wywołania narzędzia (`tool_calls`).

**Skutek braku obsługi przed v2.20:**
1. Proxy traktowało te kilkanaście znaków myśli (`thinking_fallback`) jako treść odpowiedzi asystenta.
2. Ponieważ w tekście nie było tagów XML `<tool_calls>`, proxy wysyłało do IDE treść z `finish_reason: "stop"`.
3. IDE (Cursor / Kiro / Trae) interpretowało to jako zamierzone zakończenie wypowiedzi asystenta sukcesem i natychmiast zatrzymywało autonomiczną pętlę agenta.
4. Użytkownik widział w oknie czatu urwany tekst (np. *„Let me run the test script.”*) i musiał ręcznie pisać ponaglenie do agenta.

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Pominięcie pętli agenta przy braku narzędzi:**  
   W `proxy_service.py` po zakończeniu strumienia, gdy `handler._had_tool_calls` było prawdziwe, a model nie wyemitował `FINAL ANSWER:`, kod jedynie logował ostrzeżenie:
   `[COMPLETION_CHECK] model had tool calls in history but did not output FINAL ANSWER — may need re-prompt`
   ale bezwarunkowo emitował `finish_reason: "stop"` do klienta.
2. **Przedwczesne `FINISHED` z DeepSeek Web:**  
   Gdy model zakończył myślenie na wczesnym etapie, faza `RESPONSE` w ogóle nie wystartowała (`response_started == False`), przez co klient IDE otrzymywał surowe myśli bez akcji narzędziowych.

### 🛡️ Rozwiązanie (v2.20)
Wprowadzono mechanizm **Automatycznego Re-promptu (`Auto-reprompt`)**:
1. **Detekcja przedwczesnego zatrzymania:**
   Gdy spełnione są warunki:
   - `_depth < 2` (maksymalnie 1 transparentne ponowienie),
   - `text_yielded_len == 0` (do klienta IDE nie wysłano jeszcze żadnego fragmentu tekstu),
   - Dostępne są narzędzia (`tools` niepuste),
   - Tura jest turą agenta (`role: "tool"` lub `<tool_result>` lub `handler._had_tool_calls`),
   - Brak `FINAL ANSWER:` w tekście oraz brak sparsowanych wywołań narzędzi,
2. **Natychmiastowy Re-prompt na tej samej sesji:**
   Proxy natychmiast wysyła do DeepSeeka na tej samej sesji (z `parent_id` ustawionym na węzeł ostatniej odpowiedzi `resp_msg_id`) komunikat wymuszający:
   ```
   CRITICAL: You stated your intent ('Let me run the test script.'), but you did not output any tool call.
   You are an autonomous coding agent with tools. You MUST immediately output the tool call in XML format:
   <tool_calls>
     <invoke name="ToolName">
       <parameter name="param1">value1</parameter>
     </invoke>
   </tool_calls>
   ```
3. **Płynna kontynuacja w IDE:**
   Model w drugim kroku natychmiast emituje właściwe wywołanie narzędzia XML (`<tool_calls><invoke name="Shell">...`), które StreamHandler przesyła do IDE z `finish_reason: "tool_calls"`. Pętla autonomiczna agenta w IDE nie zatrzymuje się ani na sekundę.

---

## 15. Zabezpieczenie przed fałszywym sukcesem przy pustym ponowieniu strumienia (Empty Stream Guard in Retry)

### ⚠️ Problem: Ponowienie po błędzie przejściowym zwraca 0 tokenów, a proxy wysyła `finish_reason: "stop"`
Gdy podczas generowania odpowiedzi wystąpi błąd przejściowy węzła DeepSeek (np. `Server is temporarily unavailable.`), proxy uruchamia procedurę `STREAM BACKOFF` (czekając 3s, 6s, 12s, 20s) i wywołuje zagnieżdżony `_stream_gen`.
Jeśli węzeł DeepSeek po pierwszych 3 sekundach nie był jeszcze w pełni zresetowany, iterator SSE natychmiast wyczerpuje się bez zwrócenia jakichkolwiek tokenów:
```
[DS_END] stream iterator exhausted (response_started=False, content_buffer_chars=0, total_yielded=0)
```
**Skutek przed v2.21:**
1. Zagnieżdżony `_stream_gen` traktował wyczerpanie strumienia jako normalny koniec odpowiedzi i wysyłał do klienta `finish_reason: "stop"` z pustą treścią.
2. Linia wywołująca `yield from _stream_gen(...)` uznawała to za pomyślne zakończenie i natychmiast wychodziła (`return`), pomijając kolejne próby backoffu (6s, 12s, 20s)!
3. W efekcie IDE odbierało treść wygenerowaną w pierwszej próbie (np. myśli o treści *„The user wants me to continue. I need to run the debug script... Let me just run it.”*), po czym otrzymywało pusty sygnał `stop`, co zrywało pętlę agenta.

### 🛡️ Rozwiązanie (v2.21)
1. **Empty Stream Guard (`_depth > 0`):**
   W `server/services/proxy_service.py` na końcu `_stream_gen`:
   Jeśli `_depth > 0` (jesteśmy wewnątrz zagnieżdżonego ponowienia retry) i strumień nie wygenerował ani jednego tokena (`not text_buffer and not thinking_fallback and text_yielded_len == 0`), zgłaszany jest jawny wyjątek:
   ```python
   raise RuntimeError(f"Retried stream on account {account_idx} was empty (0 tokens)")
   ```
2. **Propagacja wyjątku do nadrzędnej pętli backoffu:**
   W bloku `except Exception as e:` w `_stream_gen` dodano `if _depth > 0: raise`. Dzięki temu nadrzędna pętla `_STREAM_BACKOFF` natychmiast rejestruje nieudaną próbę i automatycznie przechodzi do kolejnego kroku backoffu (np. 6s, 12s), zamiast fałszywie zamykać turę z `finish_reason: "stop"`.

---

## 16. Zapobieganie dublowaniu promptu w trybie Resume (`is_resume` Guard w `NEW_SESSION_FIX` & Delta Consecutive User Dedup)

### ⚠️ Problem: Serwer wysyła podwójny blok promptu w trybie Resume i duplikuje zapytania na tym samym `parent_id`
W trybie kontynuacji rozmowy (Resume) w oknie IDE (Cursor / Trae), w wysyłanym promptcie pojawiała się podwójna zawartość:
`[User]: <open_and_recently_viewed_files>... <system_reminder>... Continue working on the task`
powtórzona dwukrotnie w jednym requeście. Dodatkowo, przy błędach przejściowych DeepSeeka (np. 503) retry pod tym samym rodzicem tworzyło dwa identyczne rodzeństwa w drzewie DeepSeek, a model zatrzymywał się po myśleniu bez wywołania narzędzia.

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Pomyłkowe uruchomienie `NEW_SESSION_FIX` w Resume:**
   W `_extract_prompt_parts` istniał mechanizm scalający kolejne wiadomości użytkownika na początku nowej sesji (`NEW_SESSION_FIX`):
   ```python
   if history and all(msg.get('role') == 'user' for msg in history):
       all_user_parts = [msg['content'] for msg in history] + ([user_message] if user_message else [])
       user_message = '\n\n'.join(p for p in all_user_parts if p)
       history = []
   ```
   W trybie **Resume** (`is_resume=True`) lista `msgs_to_send` zawiera wyłącznie wiadomości delty (`delta_msgs`). Gdy IDE wysłało np. stan otwartych plików oraz komendę użytkownika, obie wiadomości miały `role: "user"`. W efekcie warunek `all(msg['role'] == 'user')` był spełniony, a proxy błędnie uznało turę za **Nową Sesję** i scaliło obie wiadomości w jeden zdublowany blok promptu!
2. **Dodawanie zduplikowanych wiadomości `user` w pętli delty:**
   Gdy IDE wysyłało dwie wiadomości użytkownika o tym samym rdzeniu (`_user_core`), mechanizm deduplikacji zamieniał drugą na `_sys_tag_match + "\nContinue working on the task"`, lecz nadal dodawał OBA elementy do `msgs_to_send`.
3. **Zbyt wąski warunek `AUTO_REPROMPT`:**
   Auto-reprompt (v2.20) sprawdzał `is_agentic_turn = last_is_tool or handler._had_tool_calls`. Gdy użytkownik wysyłał "kontynuuj", ostatnia wiadomość miała rolę `user`, a model zamilkł zanim wyemitował tool calls. W efekcie `is_agentic_turn` wynosiło `False`, proxy nie repromptowało modelu i wypluwało myśli do IDE jako tekst odpowiedzi.

### 🛡️ Rozwiązanie (v2.22)
1. **Flaga `is_resume` w `_extract_prompt_parts`:**
   `NEW_SESSION_FIX` może wykonać się **WYŁĄCZNIE** gdy `not is_resume`. W trybie resume scalanie jest całkowicie zablokowane:
   ```python
   if not is_resume and history and all(msg.get('role') == 'user' for msg in history):
   ```
2. **Deduplikacja kolejnych wiadomości `user` w `delta_msgs`:**
   Jeśli kolejna wiadomość w delcie to wiadomość `user` o tym samym `_user_core` co poprzednia wiadomość `user`, nie dodajemy drugiego obiektu do `msgs_to_send`, lecz łączymy ewentualny nowy `<system-reminder>` z istniejącą wiadomością.
3. **Uogólnienie warunku `AUTO_REPROMPT` na wszystkie sesje z narzędziami:**
   Gdy `tools` jest włączone, a model zamilkł bez wyemitowania tekstu odpowiedzi (`text_yielded_len == 0`), bez wyemitowania `tool_calls` i bez `FINAL ANSWER:`, auto-reprompt wykonuje się **zawsze**, wymuszając natychmiastowe podanie narzędzia lub odpowiedzi, niezależnie od roli `messages[-1]`.

---

## 17. Automatyczny Session Rollover przy przeciążeniu kontekstu sesji DeepSeek (>250k tokenów) lub persistent 503

### ⚠️ Problem: Sesja osiąga 270k tokenów i każde zapytanie jest natychmiast ubijane przez DeepSeeka po 0.5s błędem `Server is temporarily unavailable.`
Po kilkudziesięciu turach audytu/pracy agenta w pojedynczej sesji DeepSeek Web akumuluje się gigantyczne drzewo kontekstu:
`accumulated_token_usage: 272106` (ponad 440 wiadomości w wątku).
Gdy sesja przekracza możliwości klastra DeepSeeka, backend DeepSeek Web natychmiast po 0.4–0.8 sekundy od wysłania zapytania zrywa połączenie SSE błędem:
```
[ERROR] DeepSeek SSE error mid-stream: Server is temporarily unavailable.
```
W tym ułamku sekundy model zdążył wyemitować jedynie 1 zdanie myśli (np. *„The user wants me to continue the task. I need to run the debug_put_home_payment.py script... Let me execute it.”*), po czym strumień jest odcinany.

**Skutek braku obsługi przed v2.23:**
Proxy podejmowało 4 próby retry w `STREAM BACKOFF` (3s, 6s, 12s, 20s) na **dokładnie tej samej, uszkodzonej sesji**. Ponieważ sesja miała 272k tokenów, każda kolejna próba również natychmiast kończyła się błędem 503, zmuszając użytkownika do czekania minutę na błąd 429 lub zatrzymując agenta na uciętych myślach.

### 🔍 Przyczyna źródłowa (Root Cause)
- Brak mechanizmu odświeżenia sesji na tym samym koncie. Dotychczasowa migracja (`STREAM MIGRATE`) szukała wyłącznie innych kont (`alt_pool`). Gdy użytkownik korzysta z pojedynczego konta (slot 0), proxy nigdy nie tworzyło świeżej sesji, lecz w nieskończoność męczyło przeciążoną sesję 272k tokenów.

### 🛡️ Rozwiązanie (v2.23)
Wprowadzono **Session Rollover (Automatyczne odświeżenie przeciążonej sesji)** w `server/services/proxy_service.py`:
1. Gdy wszystkie próby backoffu na danej sesji zakończą się niepowodzeniem (lub klaster odrzuca sesję błędem 503):
2. Proxy automatycznie:
   - Czyści martwą sesję z cache i stanu (`conv_state`),
   - Tworzy natychmiast **nową, czystą sesję DeepSeek** na tym samym koncie (`new_chat_id = ds.create_session(account_idx)`),
   - Odbudowuje prompt z ostatnich 20 wiadomości (`messages`), włączając pełny system prompt i schematy narzędzi,
   - Uruchamia strumieniowanie w nowej sesji bez jakiejkolwiek przerwy widocznej dla IDE.
3. W nowej sesji nie ma 272k tokenów balastu – DeepSeek odpowiada natychmiast, a agent bez przeszkód kontynuuje wykonywanie kodu.

---

## 18. Całkowity zakaz wycieku myśli jako odpowiedzi asystenta (`thinking_fallback` suppression w trybie narzędzi) i odblokowanie retry (`content_already_sent`)

### ⚠️ Problem: Model urywa generowanie po etapie myślenia, a proxy wypluwa jego myśli do IDE i zamyka turę ze statusem `stop`
W pętli autonomicznej agenta IDE (Cursor / Kiro / Trae), gdy model w buforze myślenia generuje zamiar (np. *„Let me run the test script.”* lub *„The user wants me to continue. I need to run the debug script...”*), oficjalny backend DeepSeek Web potrafi zakończyć strumień po fazie myślenia (przed otwarciem fazy `RESPONSE`) lub zgłosić błąd 503 `Server is temporarily unavailable.`.

**Skutki przed v2.24:**
1. **Fałszywy `content_already_sent` blokujący ponowienia:**
   Warunek `content_already_sent = text_yielded_len > 0 or len(text_buffer) > 0` uznawał, że skoro w buforze `text_buffer` zebrało się kilka znaków, treść została już wysłana do klienta. Ponieważ klient IDE nie otrzymał jeszcze ani jednego bajtu (`text_yielded_len == 0`), zablokowanie retry/backoff/rollover było krytycznym błędem – proxy odrzucało naprawę i natychmiast wysyłało komunikat błędu do czatu.
2. **Wyciek myśli jako odpowiedź asystenta:**
   W liniach 780–785 proxy sprawdzało: `if not text_buffer.strip(): yield _chunk({"content": thinking_fallback})`. W efekcie proces myślowy modelu trafiał do okna IDE jako finalna odpowiedź asystenta, po czym proxy wysyłało `finish_reason: "stop"`. IDE interpretowało to jako zakończenie pracy przez asystenta sukcesem i zatrzymywało pętlę agenta.
3. **Fałszywy sukces w `_depth > 0`:**
   Gdy ponowienie retry wygenerowało wyłącznie myśli, warunek `if _depth > 0 and not text_buffer and not thinking_fallback and text_yielded_len == 0:` nie zgłaszał wyjątku pustego strumienia (bo `thinking_fallback` nie był pusty), uznając próbę za udaną i emitując `stop`.

### 🔍 Przyczyna źródłowa (Root Cause)
- Zrównanie bufora serwera (`text_buffer`) z danymi fizycznie wyemitowanymi do klienta (`text_yielded_len`).
- Brak bezwzględnego zakazu emitowania `thinking_fallback` do klienta w trybie narzędziowym (`tools`). W trybie agentic myśli modelu nigdy nie stanowią odpowiedzi asystenta.

### 🛡️ Rozwiązanie (v2.24)
1. **Prawdziwy `content_already_sent`:**
   `content_already_sent = text_yielded_len > 0`. Jeśli do IDE nie wysłano żadnego tokena, proxy zawsze bezpiecznie restartuje strumień, wchodzi w `STREAM BACKOFF` lub wykonuje `SESSION ROLLOVER`.
2. **Bezwzględna supresja myśli w trybie `tools`:**
   Gdy `tools` jest włączone, a model zakończył generowanie bez wywołania narzędzi i bez tekstu odpowiedzi:
   - Proxy nigdy nie wysyła myśli jako treści odpowiedzi asystenta.
   - Jeśli ponaglenie (`AUTO_REPROMPT`) nie poskutkowało, zgłaszany jest wyjątek `Premature stop: model stopped after thinking without tool call or response`, który wchodzi w mechanizm `STREAM BACKOFF` oraz `SESSION ROLLOVER`, dając modelowi nową próbę na wygenerowanie wywołania narzędzi.
3. **Prawidłowy Empty/Incomplete Stream Guard w Retry:**
   W `_depth > 0`, jeśli strumień nie dostarczył żadnych tokenów dla klienta i nie wygenerował tekstu odpowiedzi, obecność myśli (`thinking_fallback`) w trybie `tools` nie blokuje zgłoszenia `RuntimeError` – nadrzędna pętla retry przechodzi do kolejnego kroku backoffu lub odświeżenia sesji.
4. **Niezależne śledzenie liczników:**
   Dodano `_reprompt_depth` oraz `_rollover_depth`, dzięki czemu zagnieżdżone ponowienia nie blokują auto-repromptu ani nie wpadają w pętle.

---

## 19. Natywny mechanizm Continue (`POST /api/v0/chat/continue`) oraz obsługa fragmentów RESPONSE w obiekcie SSE

### ⚠️ Problem: Model ucinał generowanie po myśleniu, wywołania narzędzi były ignorowane, a sztuczny Auto-Reprompt psuł sesję
Zaobserwowano powtarzające się zatrzymywanie generowania po etapie myślenia (np. na intencji *"The user wants me to continue. I need to run the debug script..."* lub *"Let me run the test script."*). Proxy zgłaszało `Premature stop`, rzucało błędy lub wysyłało sztuczny prompt `CRITICAL: You stated your intent...`.

### 🔍 Przyczyna źródłowa (Root Cause - odkrycie na podstawie analizy `chat.deepseek.com.har`)
1. **Ignorowanie fragmentów `RESPONSE` w inicjalnym obiekcie SSE (`deepseek_client.py`):**
   Gdy DeepSeek zwracał zdarzenie:
   `data: {"v": {"response": {"message_id": 6, "fragments": [{"id": 2, "type": "THINK", ...}, {"id": 3, "type": "RESPONSE", "content": "<"}]}}}`
   kod w `deepseek_client.py` wykonywał bezwarunkowe `if "response" in item["v"]: continue`.
   W efekcie `response_started` pozostawało `False`. Wszystkie kolejne przychodzące chunki wywołań narzędzi (DSML) nie były emitowane do klienta, lecz trafiały do bufora `thinking_fallback`. Proxy uznawało to za brak odpowiedzi (`text_yielded_len == 0`)!
2. **Sztuczny Auto-Reprompt zamiast natywnego Continue:**
   Zamiast wznowić tę samą wiadomość, proxy tworzyło nową turę użytkownika z agresywnym promptem `CRITICAL: You stated your intent...`. Powodowało to rozjechanie drzewa wiadomości DeepSeeka, błędy 422 (`UUID parsing failed` / `invalid type`), restart myślenia od zera i duplikowanie odpowiedzi.

### 🛡️ Rozwiązanie (v2.26)
1. **Ekstrakcja fragmentów RESPONSE z `item["v"]["response"]`:**
   Parser SSE w `_build_stream_iterator` natychmiast wykrywa fragmenty typu `RESPONSE` w obiekcie startowym. Ustawia `response_started = True` i niezwłocznie yielduje początkowy content (np. `<`). Kolejne przychodzące tagi `<｜｜DSML｜｜ calls>...` są natychmiast przekazywane do IDE.
2. **Wdrożenie natywnego endpointu `POST /api/v0/chat/continue`:**
   W klasie `DeepSeek` dodano metodę `stream_continue`:
   ```python
   def stream_continue(self, slot: int, chat_session_id: str, message_id: int, ...):
       # POST https://chat.deepseek.com/api/v0/chat/continue
       # Body: {"chat_session_id": chat_session_id, "message_id": message_id, "fallback_to_resume": True}
   ```
3. **Zastąpienie sztucznego Auto-Reprompt natywnym `continue` w `proxy_service.py`:**
   Gdy po fazie myślenia model zatrzyma się przed wygenerowaniem tekstu lub narzędzi (`text_yielded_len == 0 aand tools and not has_final_answer`), proxy nie wstrzykuje żadnego sztucznego tekstu promptu, lecz wywołuje `ds.stream_continue(account_idx, chat_id, resp_msg_id)`. DeepSeek natychmiast wznawia generowanie dokładnie w przerwanej wiadomości asystenta.

---

## 20. Obsługa multimodalna OpenAI Vision (Ekstrakcja obrazów, upload do DeepSeek Web i `ref_file_ids`)

### ⚠️ Problem: IDE wysyła zapytania z obrazami (OpenAI Vision API), których format nie jest kompatybilny z webowym interfejsem DeepSeek
Nowoczesne środowiska IDE (Cursor, Trae, Kiro) pozwalają użytkownikowi na wklejanie zrzutów ekranu i plików graficznych. Wiadomości te są formatowane w standardzie OpenAI Chat Completions Vision:
```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "Co jest nie tak na tym screenie?"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
      }
    }
  ]
}
```
DeepSeek Web API nie przyjmuje jednak w ciele promptu stringów base64. Wymaga uprzedniego uploadu pliku na dedykowany endpoint storage (`POST /api/v0/file/upload`), a następnie przekazania identyfikatora pliku w tablicy `ref_file_ids: [file_id]`. Pozostawienie base64 w tekście promptu doprowadziłoby do natychmiastowego przekroczenia limitu kontekstu, zablokowania hash-matching w `state_service` oraz błędów 413 po stronie serwera.

### 🛡️ Rozwiązanie (`server/core/image_processor.py` & `proxy_service.py`)
1. **Ekstrakcja i sanitizacja treści (`image_processor.py`):**
   - Funkcja `extract_images_from_messages(messages)` skanuje listę wiadomości i wyodrębnia wszystkie elementy `type: "image_url"`.
   - Obsługuje zarówno obrazy inline data URI (`data:image/<format>;base64,<data>`), jak i zewnętrzne adresy URL (`http://` / `https://`).
   - Dane graficzne są dekodowane do czystych bajtów (`image_bytes`), rozpoznawany jest typ MIME (`image/png`, `image/jpeg` itp.) oraz generowana jest bezpieczna nazwa pliku.
   - **Krytyczne:** W treści wiadomości blok z base64 jest zastępowany zwięzłą adnotacją tekstową: `[Image attached: image_0.png]`. Dzięki temu hash sesji w `state_service` pozostaje stabilny, a tokeny kontekstu nie są marnowane na miliony znaków base64.
2. **Asynchroniczny upload do DeepSeek Web API (`deepseek_client.py`):**
   - W klasie `DeepSeek` dodano metodę `upload_file(slot, file_bytes, mime_type, file_name)` uderzającą w `POST https://chat.deepseek.com/api/v0/file/upload`.
   - Żądanie zawiera rozwiązanie Proof-of-Work (PoW) specyficzne dla uploadu plików.
   - DeepSeek zwraca strukturę z identyfikatorem pliku: `{"data": {"biz_data": {"id": "file-12345"}}}`.
3. **Wstrzyknięcie `ref_file_ids` do completion:**
   - W `proxy_service.py` uzyskana lista identyfikatorów `ref_file_ids` jest przekazywana bezpośrednio do `ds.stream_completion(..., ref_file_ids=ref_file_ids)`.
   - Model DeepSeek w interfejsie webowym widzi obraz jako natywny załącznik czatu i poprawnie analizuje jego zawartość.

---

## 21. Multi-Part Chunked Prompt Injection (Obsługa gigantycznych promptów w `prompt_chunker.py`)

### ⚠️ Problem: Przekroczenie limitów pojedynczego żądania HTTP przy bardzo długich promptach
W przypadku załączania przez IDE wielu plików naraz, olbrzymich logów terminala lub rozbudowanych zestawów reguł systemowych, wygenerowany prompt może przekroczyć 120 000 – 200 000 znaków. Backend DeepSeek Web odrzuca takie żądania statusem `413 Request Entity Too Large` lub połączenie SSE ulega zerwaniu.

### 🛡️ Rozwiązanie: Podział na łańcuch pionowy (Interim Chunks)
1. **Moduł `server/services/prompt_chunker.py`:**
   - Definiuje stałą `PROMPT_CHUNK_THRESHOLD = 120_000` znaków.
   - Funkcja `split_prompt_payload(full_prompt)` dzieli zawartość na mniejsze segmenty (np. wstępny kontekst historyczny/narzędziowy oraz finalną instrukcję użytkownika).
2. **Orkiestracja w `proxy_service.py` (`_orchestrate_chunks_if_needed`):**
   - Jeśli prompt przekracza threshold, proxy nie wysyła go w całości w jednym requeście.
   - Zamiast tego wysyła segmenty pośrednie jako kolejne tury konwersacji z syntetyczną odpowiedzią asystenta potvrzającą odbiór (np. *"Understood, waiting for remaining context"*).
   - **Krytyczne:** Zachowywany jest bezwzględnie **łańcuch pionowy rodzic-dziecko** (`P0 -> R1 -> P1 -> R2 -> ...`). Zapobiega to powstawaniu węzłów-rodzeństwa i switchera wersji `< 1 / N >` w UI DeepSeeka.
   - Po zarejestrowaniu ostatniego chunka, główna pętla strumieniowania kontynuuje zapytanie od najświeższego węzła `parent_id`.

---

## 22. Optymalizacja PoW (Proof-of-Work) i wielotargetowy Cache w `deepseek_client.py`

### ⚠️ Problem: Zmienne wymagania PoW dla różnych endpointów i opóźnienia startu strumieniowania
DeepSeek Web stosuje zabezpieczenie antyscrapingowe oparte o Proof of Work (PoW). Różne akcje (np. `create_session`, `completion`, `upload_file`, `continue`) mogą generować odrębne wyzwania kryptograficzne. Przeliczanie PoW od zera przy każdym żądaniu generowało zauważalny narzut czasowy (TTFT - Time To First Token).

### 🛡️ Rozwiązanie: Wielotargetowy Cache & Auto-Invalidation
1. **Moduł `deepseek_client.py` & `pow.py`:**
   - Wdrożono mechanizm `_pow_cache` indeksowany kluczem slotu konta oraz ścieżki docelowej (`target_path`).
   - Jeśli poprzednie wyzwanie jest wciąż ważne, serwer natychmiast używa gotowego rozwiązania, eliminując niepotrzebne cykle procesora.
2. **Detekcja `INVALID_POW_RESPONSE`:**
   - W przypadku unieważnienia tokena PoW przez serwery DeepSeeka, klient natychmiast czyści cache dla danego slotu/targetu, pobiera nowe wyzwanie z nagłówka odpowiedzi i ponawia zapytanie bez przerywania sesji klienta IDE.

---

## 23. Unifikacja Rate Limiter oraz usunięcie długu technicznego i martwego kodu (v2.27)

### ⚠️ Problem: Rozjazd stanów `rate_limited_until` i nagromadzony martwy kod
W trakcie ewolucji kodu serwera powstał szereg duplikatów i nieużywanych komponentów, które utrudniały analizę i wprowadzały subtelne błędy:
1. **Dwa niezależne stany `rate_limited_until`:**
   - W `server/services/state_service.py` istniała globalna lista `rate_limited_until = [0.0] * 3`, która NIGDY nie była aktualizowana.
   - W `server/services/rate_limiter.py` istniał prawdziwy singleton `RateLimiter`.
   - Moduły `account_selector.py` i `session_manager.py` importowały martwą listę ze `state_service`, w efekcie czego sprawdzały same zera i ignorowały rzeczywiste nałożone ograniczenia czasowe kont po błędach 429!
2. **Duplikacja budowania promptów:**
   - W projekcie obok nowoczesnego `PromptBuilder` (`server/core/prompt_builder.py`) znajdował się stary, częściowo zdezaktualizowany moduł `prompt_service.py`.
3. **Nieskalowalny `FlushFileHandler`:**
   - W `state_service.py` działał customowy handler `FlushFileHandler`, zapisujący każdy krok do pliku `debug_state.log` bez rotacji (plik osiągał setki megabajtów), dublując systemowy logger.
4. **Pozostałości w katalogu `archive/` i nieużywane stałe:**
   - Stare skrypty testowe i wczesne monolity (`proxy.py`, `server.py`) leżały w repozytorium, zaciemniając przeszukiwanie kodu.

### 🛡️ Rozwiązanie (v2.27)
1. **Jedyny autorytatywny `RateLimiter`:**
   - Usunięto całkowicie `rate_limited_until` oraz `rate_limit_lock` ze `state_service.py` oraz `proxy_service.py`.
   - `account_selector.py` korzysta wyłącznie z metod instancji `rate_limiter.get_until(account_idx)`.
   - Usunięto martwe metody: `SessionManager._find_least_loaded` oraz `AccountSelector.find_slot_with_capacity`.
2. **Całkowite usunięcie `prompt_service.py`:**
   - Usunięto plik `server/services/prompt_service.py` oraz jego testy `tests/test_prompt_service.py`. Całość logiki generowania promptu spoczywa w `PromptBuilder`.
   - Z `PromptBuilder` usunięto nieużywaną, martwą metodę prywatną `_tools_not_in_system_prompt` oraz stałą `_DSML_TOOL_PATTERNS`.
3. **Standardowe logowanie:**
   - Usunięto `FlushFileHandler` oraz dedykowany `debug_log` ze `state_service.py` – moduł korzysta ze standardowego mechanizmu `server.logging`.
4. **Wyczyszczenie konfiguracji i archiwum:**
   - Usunięto 15 nieużywanych stałych z `server/config/__init__.py`.
   - Usunięto katalog `deepseek-proxy/archive/` oraz osierocone skrypty testowe (`test_orphaned.py`).
   - Poprawiono import `CloudflareBypasser` w `server/services/auth_service.py`.

---

## 24. Usunięcie martwych helperów stanu, nieużywanych importów i metod AccountPool (v2.28)

### ⚠️ Problem: Pozostałości po historycznych refaktoryzacjach
W trakcie migracji architektury do wyspecjalizowanych serwisów (`StateService`, `AccountSelector`, `StreamHandler`) w kodzie pozostały stare metody i obiekty, które nie były nigdzie wywoływane w pipeline produkcyjnym:
1. **Martwe helpery w `state_service.py`:**
   - Obiekt `request_dedup` (oraz regex `_PROXY_UUID_RE`) z czasów monolitycznego `proxy.py`.
   - Nieużywany mechanizm `_save_timer` i `_save_lock` (komentarz wskazywał "Legacy - now saves immediately", ale obiekty wciąż wisiały w pamięci).
   - Pozostałości synchronicznych aliasów backward compatibility: `_extract_watermark`, `_hash_last_user_message_sync`, `_make_state_sync`.
2. **Martwe metody w `AccountPool` (`deepseek_client.py`):**
   - `pick_for_conv()` oraz `clear_conv_state()` – logika wyboru konta oraz zarządzania konwersacją została dawno przeniesiona do dedykowanych serwisów (`AccountSelector` i `StateService`). Metody te wprowadzały mylne wrażenie, że pula kont sama zarządza stanem sesji.
   - Nieużywane importy (`MAX_PARALLEL_TOOL_CALLS`).
3. **Nieużywane importy w `image_processor.py`:**
   - `BytesIO` oraz `urlparse`.

### 🛡️ Rozwiązanie (v2.28)
1. **Wyczyszczenie `state_service.py`:**
   - Usunięto przestarzałe aliasy i obiekty `request_dedup`, `_PROXY_UUID_RE`, `_save_timer`, `_save_lock`, `_extract_watermark`, `_hash_last_user_message_sync`, `_make_state_sync`.
   - Poprawiono i zabezpieczono `_flush_conv_state()` z jawnym logowaniem ewentualnych błędów zapisu.
2. **Wyczyszczenie `AccountPool` w `deepseek_client.py`:**
   - Usunięto martwe metody delegujące `pick_for_conv` oraz `clear_conv_state`, upraszczając interfejs klasy wyłącznie do zarządzania surowymi klientami HTTP.
3. **Konfiguracja `.gitignore`:**
   - Dodano filtr `*.har`, zapobiegając przypadkowemu śledzeniu logów sieciowych HAR z przeglądarki.
4. **Synchronizacja zestawu testów:**
---

## 25. Usunięcie martwego modelu ChatRequest, zbędnych stałych konfiguracyjnych i nieużywanych importów (v2.29)

### ⚠️ Problem: Nieużywane modele pydantic, martwe stałe i śmieciowe importy
W miarę ujednolicania architektury żądania HTTP z IDE są bezpośrednio przetwarzane z surowego payloadu JSON (FastAPI `Request`) przez `ProxyService` i `InputParser`. W repozytorium pozostały:
1. **Martwy model `server/core/models.py` (`ChatRequest`):**
   - Nigdy nie był używany w endpointach produkcyjnych (`routes.py` używa `raw_request: Request`).
   - Jedynym miejscem użycia był pojedynczy test jednostkowy (`test_image_upload.py`), który wyłącznie mockował `ChatRequest.model_dump()`.
2. **Nieużywana metoda w `RateLimiter`:**
   - `rate_limiter.find_available()` – zdublowana logika; faktyczny wybór konta realizuje wyłącznie `AccountSelector._find_least_loaded()`.
3. **Martwe i zdublowane stałe w `server/config/__init__.py`:**
   - Stałe takie jak `_MIN_BASE_DELAY`, `_MAX_JITTER`, `_STREAM_BACKOFF`, `_BACKOFF_DELAYS`, `_MAX_CAPTURE_BUF_SIZE`, `_DRAIN_TIMEOUT`, `MAX_PROMPT_LEN`, `TOOL_RESULT_MAX_CHARS`, `WATERMARK_MARKER`, `DEEPSEEK_CHAT_URL`, `DEEPSEEK_CREATE_SESSION`, `MAX_RETRIES` były zadeklarowane jako re-eksporty, lecz żaden komponent produkcyjny z nich nie korzystał (komponenty mają własne zdefiniowane wartości lub korzystają bezpośrednio z instancji `settings`).
4. **Zdublowany regex w `tool_parser.py` oraz `_FINAL_ANSWER_MARKER` i martwy logger w `prompt_builder.py`:**
   - `_CONTENT_STRIP_PATTERN` w `tool_parser.py` był martwym duplikatem.
   - W `prompt_builder.py` zadeklarowano `_FINAL_ANSWER_MARKER` oraz obiekt `logger`, które nigdy nie były wywoływane.
5. **Nieużywane importy w wielu modułach:**
   - `server/services/proxy_service.py`: nieużywany import `parse_dsml_tool_calls`.
   - `server/services/session_manager.py`: nieużywany `MAX_ACCOUNTS`.
   - `server/core/input_parser.py`: nieużywany `Any`.
   - `server/services/prompt_chunker.py`: nieużywany `List`.
   - `server/dashboard/contracts.py`: nieużywany `Literal`.
   - `server/main.py`: nieużywany `json`.
   - `server/core/stream_handler.py`: importy `os` i `json` umieszczone w środku pliku (przeniesione na początek zgodnie z PEP 8).

### 🛡️ Rozwiązanie (v2.29)
1. **Całkowite usunięcie `server/core/models.py`:**
   - Usunięto nieużywany plik modelu. W teście `tests/test_image_upload.py` zastąpiono go czystym słownikiem deserializowanym do JSON.
2. **Wyczyszczenie `RateLimiter` i `tool_parser.py`:**
   - Usunięto `find_available()` z `RateLimiter` oraz `_CONTENT_STRIP_PATTERN` z `tool_parser.py`.
3. **Uporządkowanie `server/config/__init__.py` i testów konfiguracji:**
   - Usunięto 12 zbędnych stałych.
   - W testach `test_config.py` i `test_toolcall_fix_edge_cases.py` zaktualizowano asercje i importy na bezpośrednie odwołania do `settings`.
4. **Wyczyszczenie importów i standardy PEP 8:**
   - Usunięto nieużywane importy ze wszystkich wymienionych modułów oraz uporządkowano importy w `stream_handler.py`.
5. **Weryfikacja:**
   - Wszystkie 592 testy jednostkowe przechodzą pomyślnie (2 xfailed).

---

## 26. Natywny stop_stream dla Interim Chunków i ochrona kontekstu Smart Context Retention (v2.30)

### ⚠️ Problem: Blokady klastra przy dzieleniu promptów oraz utrata kontekstu przy rolloverze
W analizie zrzutów sieciowych ([stop.har](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/stop.har)) oraz logów produkcyjnych (ponad 13 800 błędów 503) zidentyfikowano dwa krytyczne wąskie gardła:
1. **Niedomknięty stan `WIP` interim chunków:**
   Przy dzieleniu gigantycznego promptu na mniejsze segmenty (`send_interim_chunk`), proxy po odczytaniu `response_message_id` z pierwszego pakietu SSE zamykało lokalne gniazdo HTTP (`r.close()`). Węzeł klastra DeepSeeka nie otrzymywał sygnału przerwania generowania i w tle nadal generował zbędną odpowiedź ze statusem `WIP`. Kolejny chunk wstrzykiwany po 1.2s uderzał w wciąż zajęty węzeł, wywołując kolizję stanów (`invalid message status`) i błędy 503.
2. **Amnezja agenta przy rolloverze (`msg_limit = 6`):**
   Dotychczasowa procedura odświeżania sesji (`SESSION ROLLOVER`) brutalnie ucinała historię do ostatnich 6 wiadomości. W efekcie wycinane było oryginalne polecenie użytkownika z Tury 1, architektura zadania i wytyczne projektowe. Agent w nowej sesji tracił orientację i pytał o cel zadania od zera.

### 🛡️ Rozwiązanie (v2.30)
1. **Implementacja `DeepSeek.stop_stream(slot, chat_session_id, message_id)`:**
   - Wzorowana bezpośrednio na oficjalnym protokole webowym zarejestrowanym w `stop.har`.
   - Wysyła żądanie `POST https://chat.deepseek.com/api/v0/chat/stop_stream` z payloadem `{"chat_session_id": chat_id, "message_id": message_id}` bez narzutu PoW.
   - **Krytyczna uwaga (v2.30 fix):** `stop_stream` NIE MOŻE być wywoływany w milisekundzie 0 na pustym interim chunku (zaraz po odebraniu `ready` przed wygenerowaniem treści). Backend DeepSeek Web traktuje stop na pustej wiadomości jako natychmiastowe anulowanie/drop zapytania i usuwa parę wiadomości z sesji, co powoduje, że kolejny chunk dostaje `biz_code: 26, biz_msg: "invalid message id"`. W `send_interim_chunk` proxy pobiera `response_message_id`, zamyka socket klienta i daje 1.0s settle delay, dzięki czemu węzeł bezpiecznie zostaje utrwalony w chmurze jako rodzic kolejnego chunka.
2. **Smart Context Retention:**
   - W procedurze rolloveru całkowicie usunięto prymitywny `msg_limit = 6`.
   - Zawsze zachowywany jest nienaruszony system prompt oraz oryginalne zapytanie użytkownika z Tury 1 (pełny cel zadania).
   - Wszystkie polecenia użytkownika i decyzje asystenta ze wszystkich tur pozostają zachowane.
   - Kompresji ulegają wyłącznie przestarzałe wyniki narzędzi (`tool_result`) sprzed okna ostatnich 8 wiadomości, co redukuje rozmiar promptu z 250k do ~20k tokenów bez utraty wiedzy o zadaniu.
4. **Weryfikacja:**
   - Dodano dedykowany zestaw testów `tests/test_stop_stream.py`. Pełny pakiet 597 testów przechodzi pomyślnie (2 xfailed).

---

## 27. Aktualizacja nagłówków i payloadu do protokołu DeepSeek Web v2.5.0 (v2.31)

### ⚠️ Problem: Rozbieżność protokołu między proxy a oficjalnym webappem DeepSeek
Po szczegółowym audycie zrzutu komunikacji HAR (`rozmowa.har`) z oficjalnej aplikacji webowej `chat.deepseek.com` zidentyfikowano szereg rozbieżności w sygnaturze żądań HTTP, które mogły powodować wzmożone błędy klastra i desynchronizację stanu:
1. **Nagłówki żądań:**
   - W proxy wysyłano anachroniczną wersję `x-client-version: 2.0.0` oraz usunięty z webappa nagłówek `x-app-version: 2.0.0`.
   - Brakowało nagłówków obecnych we wszystkich oficjalnych żądaniach: `x-client-bundle-id: com.deepseek.chat`, `x-client-timezone-offset: 7200`, `x-device-id`, `x-device-model: ""`.
   - Nagłówek `referer` w żądaniach completion był statyczny (`https://chat.deepseek.com/`), podczas gdy oficjalny klient wysyła `https://chat.deepseek.com/a/chat/s/<chat_session_id>`.
2. **Payload `completion` (`model_type` w kolejnych turach):**
   - Oficjalny webapp wysyła `model_type: "default"` (lub wskazany model) **wyłącznie w pierwszej wiadomości nowej sesji** (`parent_message_id is None`).
   - W kolejnych turach (resume / continuations, `parent_message_id is not None`), `model_type` jest wysyłany jako `None` (`null` w JSON), ponieważ model jest już zdefiniowany w sesji. Nadpisywanie `model_type` w każdej turze wymuszało niepotrzebną re-inicjalizację stanu modelu na klastrze.
3. **Payload `chat_session/create`:**
   - Webapp wysyła czyste `{}` zamiast zbędnego `{"character_id": None}`.

### 🛡️ Rozwiązanie (v2.31)
1. **Pełna zgodność z protokołem v2.5.0 w `deepseek_client.py`:**
   - Zaktualizowano `x-client-version` do `2.5.0`.
   - Usunięto nieistniejący już nagłówek `x-app-version`.
   - Dodano stabilny `x-device-id` (generowany deterministycznie z `auth_token` przez `uuid.uuid5` lub pobierany z sesji) oraz `x-client-bundle-id: com.deepseek.chat`.
   - Ustawiono dynamiczny nagłówek `referer`: wskazuje na `/a/chat/s/<chat_session_id>` dla zapytań powiązanych z sesją.
2. **Warunkowy `model_type` w `stream_completion`:**
   - `req_model_type = model_type if parent_message_id is None else None`.
3. **Weryfikacja:**
   - Zaktualizowano asercje testów w `tests/test_headers_anti_mute.py` oraz `tests/test_payload_and_resume_states.py`.
   - Pełny zestaw testów: **597 passed, 2 xfailed** w 36s.

---

## 28. Samonaprawiający się stan sesji i autokorekta Parent ID (Self-Healing Session State & `biz_code: 26`) (v2.32)

### ⚠️ Problem: Desynchronizacja `parent_id` i błąd `biz_code: 26 (invalid message id)`
W środowiskach IDE (Trae / Kiro / Cursor), gdy lokalny cache proxy posiadał zapamiętane `parent_id` (np. 6), a w chmurze DeepSeek sesja zakończyła się na wcześniejszym węźle (np. 4) wskutek przerwania połączenia lub wcześniejszego błędu, kolejne zapytania (w tym interim chunki przy promptach >80k znaków) były odrzucane przez serwer DeepSeek z błędem biznesowym:
```json
{"code":0,"msg":"","data":{"biz_code":26,"biz_msg":"invalid message id","biz_data":null}}
```
Proxy ponawiało próbę 3 razy z rzędu z tym samym nieistniejącym `parent_id`, po czym rzucało `RuntimeError`, co zwracało błąd `500 Internal Server Error` do IDE.

### 🛡️ Rozwiązanie (v2.32)
1. **Pobieranie historii i wykrywanie rzeczywistego węzła (`get_last_message_id`):**
   - Dodano metodę `DeepSeek.get_last_message_id(slot, chat_session_id)` odpytującą `GET /api/v0/chat/history_messages?chat_session_id={chat_session_id}`.
   - Metoda zwraca najwyższy zatwierdzony `message_id` w sesji w chmurze DeepSeek.
2. **Automatyczna autokorekta w `send_interim_chunk` oraz `stream_completion`:**
   - Gdy backend DeepSeek zwróci `biz_code: 26` lub `invalid message id`, proxy nie rzuca błędu, lecz natychmiast sprawdza historię sesji w chmurze.
   - Jeśli `real_last_id != parent_message_id`, proxy autokoryguje `parent_message_id = real_last_id` i automatycznie ponawia zapytanie z poprawnym rodzicem (`[PARENT_AUTOCORRECT]`).
3. **Automatyczny fallback Session Rollover w `_orchestrate_chunks_if_needed`:**
   - Jeśli sesja w chmurze została trwale uszkodzona lub skasowana przez użytkownika i nie posiada żadnych wiadomości, proxy w `chat_completions` natychmiast tworzy nową sesję (`ds.create_session`), ustawia `parent_id = None` i ponawia wstrzyknięcie chunków bez zwracania błędu 500 do IDE.
4. **Weryfikacja:**
   - Dodano test jednostkowy `tests/test_parent_autocorrect.py`.
   - Wszystkie 598 testów przechodzi pomyślnie (2 xfailed).

---

## 29. Deterministyczne interim chunky z ACK i Repetition Loop Guard (v2.33)

### ⚠️ Problem: Niepożądane wywołania narzędzi na interim chunkach i zapętlenie modelu na ostatnim parcie
Przy dzieleniu dużych promptów (>35k znaków) na kolejne segmenty (Part 1 of N, Part 2 of N):
1. **Tool calle w tle między partami:**
   `send_interim_chunk` wysyłało żądania z `thinking_enabled: True`. Model DeepSeek R1 ignorował adnotację `Do NOT answer or generate response yet`, uruchamiał wielosekundowy proces myślenia, widział fragmenty kodu i generował wywołania narzędzi (np. `Read`, `RunCommand`). Ponieważ proxy zamykało tylko lokalny socket, serwer DeepSeek w tle utrwalał te wywołania w drzewie sesji.
2. **Rozjazd drzewa konwersacji:**
   Kolejne party (Part 2, Part 3) trafiały do chmury jako wiadomości użytkownika w momencie, gdy model oczekiwał wyników wcześniejszych wywołań. W sesji powstawała niespójna sekwencja (niezrealizowany tool call -> kolejny chunk usera -> kolejny tool call).
3. **Pętla degeneracji autoregresyjnej na Part 3:**
   Na ostatnim parcie model ulegał destabilizacji i wpadał w pętlę generowania powtarzających się setki razy uszkodzonych tagów `</｜｜DSML｜｜ parameter>`.

### 🛡️ Rozwiązanie (v2.33)
1. **Deterministyczne potwierdzenie `ACK` w interim chunkach (`prompt_chunker.py`):**
   - W nagłówku chunka pośredniego (`not is_last`) jednoznacznie zdefiniowano polecenie: `Do NOT execute any tools or analyze yet. Reply ONLY with: ACK`.
   - Na końcu chunka dołączono twardą dyrektywę i stopkę asystenta:
     ```
     [SYSTEM DIRECTIVE: Interim buffer chunk {part_num}/{total_chunks}. Reply ONLY with the exact word 'ACK'.]

     [Assistant]:
     ACK
     ```
2. **Wyłączenie myślenia i domykanie węzła w `deepseek_client.py`:**
   - W `send_interim_chunk` ustawiono `thinking_enabled: False`.
   - Model w trybie czatu V3 bez fazy R1 reasoning natychmiast (w ułamku sekundy) emituje token `ACK`.
   - Proxy czeka na odebranie tokenu `ACK` (lub do 5 tokenów), dzięki czemu węzeł w chmurze ma status `FINISHED` i treść `ACK` bez jakichkolwiek wywołań narzędzi, a po przejściu do kolejnego chunka drzewo sesji jest w 100% spójne.
3. **Repetition Loop Guard (`stream_handler.py` & `proxy_service.py`):**
   - Dodano funkcję `detect_repetition_loop(text)` monitorującą strumień generowany przez asystenta.
   - Wykrywa ona powtórzenia uszkodzonych tagów zamykających (np. 4+ pod rząd `</｜｜DSML｜｜ parameter>`) lub zapętlenie dowolnego podciągu (8-80 znaków) powtórzonego >= 4 razy.
   - W przypadku wykrycia pętli strumień jest natychmiast bezpiecznie przerywany (`break`), chroniąc klienta IDE przed zalaniem setkami tysięcy bezużytecznych znaków.
4. **Weryfikacja:**
   - Test jednostkowy `tests/test_prompt_chunker.py` zaktualizowany i przechodzący pomyślnie.
   - Nowe testy jednostkowe `test_detect_repetition_loop` w `tests/test_stream_handler.py`.
   - Pełny zestaw testów: **599 passed, 2 xfailed** w 41s.

---

## 30. Likwidacja opóźnień orkiestracji interim chunków i nagłówki antybuforujące SSE (v2.34)

### ⚠️ Problem: 40-sekundowe wiszenie gniazda TCP i gubienie wywołań narzędzi w IDE
W logach produkcyjnych zaobserwowano, że mimo poprawnego wygenerowania tool calli przez model w chmurze DeepSeek, IDE (Trae / Kiro / Cursor) odbierało je z ogromnym opóźnieniem (>42s) lub wcale:
1. **Sztuczne uśpienia throttle w interim chunkach:**
   Każdy segment orkiestracji wieloczęściowej wywoływał pełny `self._throttle(slot)`, narzucający 14-17 sekund synchronicznego `time.sleep` dla każdego parta oraz kolejne 14 sekund dla finalnego parta. Łącznie proxy wisiało zablokowane na `time.sleep` przez 30-40 sekund, zanim w ogóle zwróciło nagłówki HTTP do IDE.
2. **Timeout bezczynności socketu w klientach IDE:**
   Ponieważ endpoint `/v1/chat/completions` nie wysyłał żadnych bajtów ani nagłówków HTTP przez ponad 40 sekund, klient HTTP IDE (oparty na Node.js / Electron) wchodził w stan idle timeout (zazwyczaj 30s) i uznawał połączenie za zerwane lub buforował dane.
3. **Brak roli `"role": "assistant"` w delcie tool calli:**
   W pierwszym chunku strumienia OpenAI, w którym zwracane były `tool_calls`, brakowało pola `"role": "assistant"`. Maszyna stanów w niektórych parserach IDE nie inicjalizowała nowego obiektu wiadomości asystenta bez tego pola, przez co odebrane tool calle nie trafiały do interfejsu.
4. **Brak nagłówków zapobiegających buforowaniu SSE:**
   `StreamingResponse` nie posiadało nagłówków `Cache-Control: no-cache`, `Connection: keep-alive` oraz `X-Accel-Buffering: no`, co pozwalało stosowi sieciowemu na buforowanie małych pakietów końcowych.

### 🛡️ Rozwiązanie (v2.34)
1. **Lekki throttle dla segmentów interim (`is_interim=True`):**
   - W `deepseek_client.py` zaktualizowano `_throttle(slot, is_interim=True)` z minimalnym targetem `1.0s` (zamiast 15s).
   - W `_orchestrate_chunks_if_needed` skrócono settling delay do `0.2s` i wprowadzono flagę `was_chunked`.
   - `stream_completion` otrzymało flagę `is_chunk_continuation=was_chunked`, eliminując 14-sekundowe uśpienie przed startem finalnego strumienia.
   - **Efekt:** Czas przygotowania i orkiestracji chunków spadł z **35 sekund do 2 sekund**.
2. **Inicjalizacja roli asystenta w delcie wywołań narzędzi:**
   - W `proxy_service.py` przy emisji `tc_list` (linie 608, 722, 785) chunk zawsze zawiera `{"role": "assistant", "tool_calls": tc_list}`.
   - W `server/utils/helpers.py` funkcja `_chunk` gwarantuje poprawną serializację delty zawierającej `"role"`.
3. **Nagłówki antybuforujące w `StreamingResponse`:**
   ```python
   headers={
       "Cache-Control": "no-cache",
       "Connection": "keep-alive",
       "X-Accel-Buffering": "no",
   }
   ```
4. **Skrócenie timeoutu drainowania strumienia:**
   - `_DRAIN_TIMEOUT` zredukowano z 30.0s do 5.0s, zapobiegając zawieszaniu odpowiedzi po wygenerowaniu narzędzi.
5. **Weryfikacja:**
   - Zaktualizowano testy w `tests/test_multi_part_injection.py`.
   - Pełny zestaw testów: **599 passed, 2 xfailed** w 26.7s.

---

## 31. Strategia załączania dokumentów z limitem 100 MB per plik (Document Attachment Strategy) (v2.35)

### 🚨 Problem: Kosztowne wieloetapowe interim chunky dla ogromnych wyników narzędzi
Gdy model lub IDE odczytuje bardzo duże pliki źródłowe (`read_file`), logi komend lub rozbudowane diffy gita, pojedynczy blok `<tool_result>` potrafi osiągnąć 50k–500k znaków. Poprzednio mechanizm `prompt_chunker.py` musiał dzielić taki payload na 2–10 kolejnych interim chunków, wymuszając sekwencyjne zapytania z ACK i settling delay, co zajmowało 2–10 sekund na samą orkiestrację przed wygenerowaniem odpowiedzi przez model.

Ponadto DeepSeek Web UI natywnie oferuje mechanizm:
`Upload docs or images (Max 50, 100MB each)` poprzez endpoint `/api/v0/file/upload_file`.

### 🛡️ Rozwiązanie (v2.35)
Wprowadzono dedykowaną usługę `DocumentAttachmentService` (`server/services/document_attachment_service.py`) zintegrowaną bezpośrednio z `ProxyService`:

1. **Limit 100 MB per plik oraz automatyczny split:**
   - Stała `MAX_DOCUMENT_SIZE_BYTES = 100 * 1024 * 1024` (100 MB).
   - Maksymalna liczba załączników: 50.
   - Jeśli treść bloku przekracza 100 MB, zostaje deterministycznie podzielona na części: `tool_result_{call_id}_part1.md`, `_part2.md`, itd.
2. **Semantyczna ekstrakcja zamiast arbitralnego cięcia:**
   - **Wyniki narzędzi:** Bloki `<tool_result>` są pakowane do plików `tool_result_{call_id}.md` z odnośnikiem wewnątrz bloku XML.
   - **Reguły projektu:** Wielkie bloki `<rules>` oraz `<always_applied_workspace_rules>` (np. 34 KB `python rules.md`) są pakowane do pliku `project_rules.md`. Model otrzymuje instrukcję o przestrzeganiu reguł z tego załącznika.
   - **Wcześniejsza historia:** Jeśli przy starcie sesji payload zawiera długą wcześniejszą historię tur (`[Assistant]: ... [User]:`), zostaje ona spakowana do pliku `conversation_history.md`.
   - **ZAKAZ arbitralnego ucinania promptu:** Nigdy nie wolno uciąć promptu w połowie definicji systemowych i narzędzi do jednego pliku `context_payload.md`.
3. **Podział ról (Prompt Inline vs Załączniki):**
   - **Inline w prompcie:** Core System Prompt (tożsamość agenta, formatowanie `<invoke>`), schematy narzędzi oraz bieżące zapytanie użytkownika. Gwarantuje to nadrzędną uwagę sterującą (steering) LLM i bezbłędne generowanie wywołań narzędzi.
   - **W załącznikach (`ref_file_ids`):** Wyniki narzędzi (`tool_result_{call_id}.md`), reguły projektowe (`project_rules.md`), długa historia (`conversation_history.md`).
4. **Błyskawiczny upload i przekazanie `ref_file_ids`:**
   - W `proxy_service.py` pliki dokumentów są wgrywane przez `ds.upload_file(...)` równolegle z obrazami Vision.
   - Zwrócone identyfikatory `file_id` (np. `file-xxxx`) trafiają bezpośrednio do parametru `ref_file_ids` w `stream_completion`.
   - Zredukowany prompt (`< 35k`) natychmiast omija orkiestrację chunkera, skracając czas odpowiedzi do **~1 sekundy**.
5. **Weryfikacja testowa:**
   - Testy jednostkowe: `tests/test_document_attachment_service.py` (6 testów jednostkowych).
   - Test integracyjny: `tests/test_document_attachment_integration.py`.
   - Testy hashowania: `tests/test_msg_hash_stability.py` (17 testów).
   - Pełny zestaw testów projektu: **609 passed, 2 xfailed**.

---

## 32. Pełne zachowanie historii konwersacji z IDE w `conversation_history.md` i likwidacja sztucznego obcinania wiadomości (v2.36)

### 🚨 Problem: Utrata długiej historii czatu z IDE przy nowej sesji
Gdy użytkownik prowadzi długą sesję w IDE (np. 120–150 wiadomości), a z jakiegoś powodu proxy zakłada nową sesję DeepSeek (np. po restarcie serwera, wyczyszczeniu stanu lub po przekroczeniu TTL sesji):
1. **Sztuczne obcinanie (`[MSG CAP]`):** Archaiczny blok w `proxy_service.py` obcinał całą listę wiadomości do ostatnich 20 (`msg_limit = 20`), bezpowrotnie wyrzucając ponad 100 wcześniejszych wiadomości z IDE!
2. **Brutalne czyszczenie (`NEW_SESSION_FIX_V2`):** Następnie kod wykonywał `history = []`, kasując wszystkie odpowiedzi asystenta, wywołania narzędzi i ich wyniki, pozostawiając model w całkowitej niewiedzy o przeszłości.
3. **Naiwny fallback `context_payload.md`:** Prompt pozbawiony historii, ale zawierający 19 definicji narzędzi JSON schema przekraczał próg, a fallback uciekał się do ucięcia promptu w połowie (od 15 000 znaku) i wrzucał resztę do `context_payload.md` (40.88 KB), ucinając narzędzia i zapytanie usera.

### 🛡️ Rozwiązanie (v2.36)
1. **Całkowita likwidacja limitu 20 wiadomości (`[MSG CAP]`):**
   - Wszystkie wiadomości przesyłane przez IDE (`msgs_to_send = list(parsed.messages)`) są zachowywane w całości.
2. **Automatyczne pakowanie historii wieloturowej do `conversation_history.md`:**
   - Jeśli nowa sesja DeepSeek (`not parsed.is_resume`) otrzymuje historię zawierającą wcześniejsze tury dialogowe (`has_prior_dialogue`), funkcja `create_history_attachments(history)` formatuje całą przeszłość do czytelnego dokumentu Markdown:
     - Nagłówki tur: `## Turn {idx} - User`, `## Turn {idx} - Assistant`, `### Tool Calls`, `## Turn {idx} - Tool (tool_name)`.
     - Plik jest dzielony na party do 100 MB per plik (limit DeepSeek Web).
     - Dokument jest dołączany do `doc_attachments`, wgrywany przez `ds.upload_file` i przekazywany jako `ref_file_ids`.
3. **Lekki, bezpieczny prompt inline:**
   - W prompcie inline wysyłanym do DeepSeek umieszczana jest czytelna instrukcja:
     `[Full prior conversation history from IDE ({len(history)} turns) is attached in document(s): conversation_history.md. Please carefully review the attached history to understand prior context and fulfill the user's latest request below.]`
   - Oraz najnowsze zapytanie użytkownika (`user_message`).
   - `history` dla sesji DeepSeek zostaje wyczyszczone, dzięki czemu prompt mieści się swobodnie w bezpiecznym limicie (<30k znaków) i nie ulega żadnemu ucięciu.
4. **Weryfikacja testowa:**
   - Testy jednostkowe: `tests/test_document_attachment_service.py`.
   - Test zachowania 120 wiadomości: `tests/test_conversation_history_preservation.py`.
   - Wszystkie testy pakietu przechodzą w 100%.

---

## 33. Eliminacja catastrophic backtracking (ReDoS) w `_sanitize_for_structure` i natychmiastowy bail-out w `_is_capture_complete` (v2.37)

### 🚨 Problem: 100% CPU lockup na głównym wątku podczas streamingu dużych plików
W trakcie generowania przez model dużych fragmentów kodu wewnątrz parametru `<parameter name="content">...`, serwer proxy całkowicie zamarł (15 minut 100% CPU, brak reakcji na żądania HTTP na porcie 4570).

Zrzut stack trace (`py-spy dump --pid 9824`) wykazał:
```
Thread 27844 (active+gil): "MainThread"
    _sanitize_for_structure (server\parser\dsml_sieve.py:722)
    _is_capture_complete (server\parser\dsml_sieve.py:732)
    _try_finish_capture (server\parser\dsml_sieve.py:892)
    feed (server\parser\dsml_sieve.py:272)
```

**Przyczyny awarii:**
1. **Catastrophic Backtracking (ReDoS) w regexie parametrów:**
   W `_sanitize_for_structure` wzorzec:
   `r'<(?:\|?(?:TOOL|DSML)\|?)?parameter(?:\s+[^>]*?)?\s+name=["\'][^"\']*["\'](?:\s+[^>]*?)?>.*?</(?:\|?(?:TOOL|DSML)\|?)?parameter\s*>'`
   posiadał zagnieżdżone, nakładające się kwantyfikatory (`(?:\s+[^>]*?)?\s+`). Gdy do buforu trafiał kod (zawierający cudzysłowy, spacje, operatory relacyjne `<`), a tag zamykający `</parameter>` jeszcze nie nadszedł z sieci, silnik regex wykonywał wykładniczą liczbę nawrotów (backtracking) przy każdym nowo przybyłym pakiecie SSE!
2. **Kompilacja regexu w pętli każdego chunka:** `re.compile(...)` było wołane setki razy na sekundę na rosnącym buforze.
3. **Brak szybkiego wyjścia (Fast Bail-out):** `_is_capture_complete` wykonywało pełną procedurę sanityzacji i regexów na buforze, nawet gdy w buforze nie było jeszcze żadnego tagu zamykającego (`</`, `]`, ani `}`).

### 🛡️ Rozwiązanie (v2.37)
1. **Szybki bail-out w `_is_capture_complete`:**
   ```python
   if "</" not in buf and "]" not in buf and "}" not in buf and "`" not in buf:
       return False
   ```
   Dopóki w buforze nie pojawi się jakikolwiek delimiter zamykający, funkcja zwraca `False` w ułamku mikrosekundy, omijając całą obróbkę tekstu.
2. **Bezpieczny regex na poziomie modułu (`_PARAM_BLOCK_RE`):**
   ```python
   _PARAM_BLOCK_RE = re.compile(
       r"<(?:\|?(?:TOOL|DSML)\|?)?parameter\b[^>]*>.*?</(?:\|?(?:TOOL|DSML)\|?)?parameter\s*>",
       re.DOTALL | re.IGNORECASE,
   )
   ```
   Wyeliminowano zagnieżdżone kwantyfikatory białości znaków. Czas dopasowania jest w 100% liniowy $O(N)$.
3. **Fast exit w `_sanitize_for_structure`:**
   Jeśli w buforze nie występują jednocześnie ciągi `"parameter"` i `"</"`, funkcja natychmiast zwraca oryginalny bufor bez uruchamiania silnika regex.
4. **Weryfikacja testowa:**
   Dodano test obciążeniowy `test_sieve_large_unclosed_parameter_no_catastrophic_backtracking`, sprawdzający przepływ 50 000 znaków kodu bez tagu zamykającego w czasie < 0.2s (wynik: <0.05s). Wszystkie 49 testów sieve przechodzi w 2 sekundy.

---

## 34. Eliminacja Double Throttling, ochrona pętli asyncio przed time.sleep oraz bezbłędny keep-alive retry bez kodu 429 (v2.38)

### ⚠️ Problem: Serwer "zakurwia się" (zawiesza na 5+ minut) przy kolejkowaniu requestów lub rate-limicie
Gdy użytkownik aktywnie korzystał z IDE (Cursor/Trae), serwer w pewnym momencie całkowicie przestawał odpowiadać. Nawet prosty endpoint `/health` zawieszał się na ponad 5 minut, a IDE zgłaszało `Connection reset` lub `Timeout`.

### 🔍 Przyczyny źródłowe (Root Causes)
1. **Podwójny Throttle (Double Throttling):**
   W `proxy_service.py` przed wywołaniem API DeepSeeka wołano asynchroniczne `await ds.async_throttle(account_idx)`. Funkcja ta odczekiwała wymagany interwał (~17s) i aktualizowała znacznik czasu `self._last_request_time[slot] = time.time()`.
   Zaraz po tym wywoływano `ds.stream_completion(...)`, które wewnątrz `deepseek_client.py` bezwarunkowo wywoływało synchroniczne `self._throttle(slot)`.
   Ponieważ znacznik czasu został zaktualizowany ułamek milisekundy wcześniej, synchroniczne `_throttle` stwierdzało, że `elapsed = 0.0s < 17.6s` i nakazywało **kolejne 17–20 sekund snu przez synchroniczne `time.sleep`**!
2. **Zamrożenie głównego wątku pętli `asyncio`:**
   W FastAPI/Uvicorn endpointy `async def` wykonują się w głównym wątku event loopa asyncio. Każde synchroniczne `time.sleep(18)` całkowicie zamrażało cały serwer. Wszystkie przychodzące zapytania (w tym `/health` oraz kolejne równoległe zapytania z IDE) czekały w nieskończoność.
3. **Zrywanie rozmowy kodem HTTP 429:**
   Gdy konto DeepSeek zwracało `Messages too frequent. Try again later.`, proxy podnosiło `DeepSeekRateLimitError`, a priming generatora zamieniał go na `HTTPException(429, Retry-After=...)`. Po otrzymaniu kodu 429 IDE natychmiast przerywało rozmowę i wyświetlało błąd w oknie czatu, niszcząc płynność pracy agenta.

### 🛡️ Rozwiązanie (v2.38)
1. **Flaga `throttle: bool = True` we wszystkich metodach klienta (`deepseek_client.py`):**
   Metody `stream_completion`, `stream_continue`, `create_session` i `interim_chat` przyjmują opcjonalny parametr `throttle: bool = True`. Po wykonaniu `await ds.async_throttle(account_idx)` w `proxy_service.py` przekazywane jest `throttle=False`. Eliminuje to podwójny throttle i zbędne 20 sekund oczekiwania.
2. **Asyncio Loop Guard w `_throttle`:**
   W `deepseek_client.py` wewnątrz `_throttle`:
   ```python
   try:
       asyncio.get_running_loop()
       in_async_loop = True
   except RuntimeError:
       in_async_loop = False

   if in_async_loop and wait > 0.5:
       logger.warning(f"[THROTTLE GUARD] Prevented blocking time.sleep({wait:.1f}s) inside running asyncio loop for account={slot}.")
   ```
   Uniemożliwia to jakiekolwiek zablokowanie pętli zdarzeń asyncio synchronicznym snem.
3. **Płynny Retry z SSE `: keep-alive\n\n` bez rzucania kodu 429:**
   W `_stream_gen` przy wykryciu `is_rate and not content_already_sent`:
   Zamiast rzucać błąd i przerywać rozmowę kodem 429:
   - Proxy wchodzi w pętlę oczekiwania (do 25s), emitując co 2 sekundy komentarze SSE `: keep-alive\n\n`.
   - Podtrzymuje to połączenie HTTP z IDE bez generowania tekstu.
   - Po minięciu cooldownu ponawia próbę zapytania (`stream_continue` lub `stream_completion`).
   - W przypadku ostatecznego wyczerpania prób emitowany jest delikatny komunikat informacyjny w strumieniu bez rzucania 429, dzięki czemu sesja w IDE nie ulega przerwaniu.

---

## 35. Multi-Account Authentication & Dynamic Account Rotation (Slot 0 + Slot 1) (v2.39)

### 🎯 Cel
Pula kont DeepSeek Web (`AccountPool`) pozwala na równoległe korzystanie z wielu niezależnych sesji przeglądarkowych. Każdy slot posiada własną izolację plików cookies, tokenów (`session_{slot}.json`), katalogu profilu przeglądarki (`.chrome_slot/slot_{slot}`) oraz oddzielny licznik rate limitu.

### 🚀 Procedura logowania kolejnego konta:
1. Endpoint `POST /v1/login?slot={slot_idx}`:
   - Sprawdza cooldown logowania na dany slot (60s).
   - Czyści pamięć podręczną slotu (`ap.reset_slot(slot)`).
   - Uruchamia izolowane okno przeglądarki Chrome ze stealth-patchami i automatycznym ominięciem Cloudflare Turnstile.
2. Przechwycenie sesji:
   - Po zalogowaniu w oknie DeepSeek token `userToken` oraz pliki cookie są zapisywane w pliku `server/session_{slot}.json`.
   - Resetowana jest sesja HTTP curl_cffi oraz ewentualny stan rate limitera dla tego slotu.
3. Dynamiczna rotacja:
   - `AccountSelector` automatycznie rozdziela zapytania między aktywne, ważne konta (`valid: true`), a w przypadku chwilowego wyczerpania limitu na jednym koncie przekierowuje ruch na kolejne dostępne konto.

---

## 36. Płynny Account Failover, Session Rollover i 100% historii w conversation_history.md (v2.40)

### ⚠️ Problem: Przedwczesne zamykanie rozmów i brak migracji w trwających dialogach
1. **Sztuczna blokada migracji (`parent_id is None`):**
   - Poprzednia implementacja `STREAM MIGRATE` sprawdzała warunek `parent_id is None`. W efekcie migracja konta działała tylko w pierwszej wiadomości nowej rozmowy. W trakcie trwania dialogu (Turn 2+) serwer nie potrafił zmienić konta.
2. **Przedwczesny `finish_reason: "stop"` po 3 próbach:**
   - Gdy DeepSeek Web zwracał `Server is temporarily unavailable.`, proxy poddawało się po 3 próbach (~60s), wysyłając tekst informacyjny i zamykając turę w edytorze.
3. **Utrata kontekstu i brak załącznika:**
   - Poprzedni mechanizm migracji i rolloveru obcinał starsze wiadomości tekstowo (`[middle context trimmed]`), ryzykując przekroczenie limitu promptu (>35k znaków) i utratę istotnych ustaleń.

### 🛡️ Rozwiązanie (v2.40)
1. **`_prepare_new_session_payload` z pełnym pakowaniem do `conversation_history.md`:**
   - Każde utworzenie nowej sesji w trakcie dialogu (Account Failover lub Session Rollover) automatycznie pakuje całą dotychczasową historię z IDE do pliku `conversation_history.md` bez jakiegokolwiek obcinania.
   - Plik jest uploadowany na docelowy slot przez `ds.upload_file`, a `ref_file_id` przekazywany do `ds.stream_completion`. Sam prompt tekstowy pozostaje lekki (<5k znaków).
2. **Płynny Account Failover w dowolnym momencie dialogu:**
   - Usunięto ograniczenie `parent_id is None`. Przy wystąpieniu rate limitu lub błędu klastra, proxy natychmiast przenosi zapytanie na drugie sprawne konto ze świeżą sesją i załączoną historią.
3. **Session Rollover przy powtarzającym się `Server is temporarily unavailable`:**
   - Jeśli na danej sesji błąd klastra występuje ponownie (`_rate_retry >= 1`), proxy automatycznie zakłada nową sesję z historią w pliku, eliminując zawieszony worker klastra DeepSeek.
4. **Zwiększony limit prób (do 10) i ciągłe `: keep-alive`:**
   - Pętla rate retry podtrzymuje połączenie i weryfikuje dostępność alternatywnego konta przed ponowieniem.

---

## 37. Automatyczne wykrywanie uciętych odpowiedzi i bezszwowe Auto-Continue (v2.41)

### ⚠️ Problem: Model urywał generację kodu/tekstu/narzędzi i nie wysyłał Continue
W trakcie długich odpowiedzi (generowanie dużych funkcji, specyfikacji lub bloków wywołań narzędzi XML) odpowiedź modelu była ucinana w połowie przez limit tokenów wyjściowych interfejsu DeepSeek Web. Proxy nie uruchamiało procedury /api/v0/chat/continue, zamykając turę ze statusem sukcesu (inish_reason: "stop").

**Przyczyny źródłowe:**
1. **Sztywna blokada text_yielded_len == 0 oraz wymóg and tools:**
   - Wcześniejsza logika uruchamiała stream_continue tylko wtedy, gdy proxy nie wysłało jeszcze ani jednego znaku tekstu do IDE (text_yielded_len == 0). Gdy model wygenerował np. 1000 słów i uciął w pół zdania, warunek był fałszywy i proxy zamykało strumień.
   - Zapytania bez narzędzi (lub gdy IDE nie przekazało schematu tools) były bezwarunkowo ignorowane przez wymóg and tools.
2. **Brak flagi zakończenia is_finished w parserze SSE:**
   - Gdy strumień kończył się ucięciem bez pakietu response/status: SET FINISHED, klient DeepSeek nie przekazywał tego faktu do result_meta.
3. **Brak detekcji uciętego Markdowna i tagów XML:**
   - Nieparzysta liczba potrójnych grawisów (otwarty blok kodu) lub niedomknięte tagi <invoke> / <tool_call> nie były rozpoznawane jako ucięta odpowiedź.
4. **Rozbicie kontekstu handlera i bufora tekstu:**
   - Dotychczasowe rekurencyjne wywołanie _stream_gen resetowało StreamHandler i bufor tekstu, co uniemożliwiało dokończenie uciętych w połowie wywołań narzędzi XML.

---

### 🛡️ Rozwiązanie (v2.41)
1. **Śledzenie flagi is_finished w _build_stream_iterator (deepseek_client.py):**
   - Flaga result_meta["is_finished"] przyjmuje wartość True wyłącznie po odebraniu oficjalnego pakietu response/status: SET FINISHED.
2. **Zaawansowana detekcja ucięć w _is_response_truncated (proxy_service.py):**
   - Wykrywa brak is_finished,
   - Wykrywa nieparzystą liczbę potrójnych grawisów (otwarty blok Markdown),
   - Wykrywa niedomknięte tagi wywołań narzędzi (<invoke>, <tool_call>, <tool_calls>) przy użyciu granic słów \b.
3. **Bezszwowa pętla kontynuacji z zachowaniem StreamHandler i text_buffer:**
   - Gdy odpowiedź jest ucięta (_is_response_truncated), proxy nie kończy strumienia ani nie tworzy nowego pustego handlera.
   - Wywołuje ds.stream_continue, a przychodzące tokeny są płynnie przekazywane przez **ten sam** StreamHandler i doklejane do istniejącego text_buffer.
   - Tokeny są w czasie rzeczywistym yieldujące do IDE w ramach jednego spójnego strumienia SSE OpenAI.
4. **Inteligentna kompresja dawnych tur w document_attachment_service.py:**
   - W przypadku bardzo długich historii dialogu (>120k znaków, >25 tur), funkcja format_history_to_markdown automatycznie kompaktuje dawne wyniki narzędzi (starsze niż 20 ostatnich tur), zachowując w 100% pierwsze tury (założenia projektu) oraz najświeższe 20 tur. Chroni to klaster DeepSeek przed błędem Server is temporarily unavailable.

---

---

## 38. Twardy limit budżetowy załącznika historii (95 KB ceiling) i eliminacja OOM klastra (v2.42)

### ⚠️ Problem: 160 187 tokenów w załączniku i pętla Server is temporarily unavailable
Gdy konwersacja z IDE przekraczała 150–300 tur, plik conversation_history.md osiągał prawie 500 KB (496 082 bajty).
Oficjalny parser DeepSeek Web liczył z tego załącznika aż **160 187 tokenów**, podczas gdy limit okna kontekstowego modelu wynosi 128k (131 072 tokeny)!
Model próbował przetworzyć załącznik przekraczający okno kontekstowe, po czym po 15 sekundach zwracał w strumieniu SSE błąd:
`json
{"type": "error", "content": "Server is temporarily unavailable."}
`
Proxy próbowało ratować sytuację migracją na drugie konto (STREAM MIGRATE), uploadowało ten sam plik 496 KB, drugie konto dostawało ten sam błąd i serwer wpadał w nieskończoną pętlę failoveru między Slot 0 a Slot 1.

**Przyczyna źródłowa:**
1. Wcześniejsza funkcja ormat_history_to_markdown nie przycinała argumentów args w 	ool_calls. Dawne wywołania edycji plików (write_to_file, 
eplace_file_content) zawierały dziesiątki kilobajtów kodu per tura, kumulując 450 KB w samej historii wywołań.
2. Brakowało twardego budżetu rozmiaru pliku.

---

### 🛡️ Rozwiązanie (v2.42)
1. **Twardy limit budżetu MAX_HISTORY_DOC_BYTES = 95_000 (~95 KB / ~25k tokenów):**
   - Plik conversation_history.md NIGDY nie może przekroczyć 95 KB, co gwarantuje token usage rzędu ~25 000 tokenów i pozostawia ponad 100 000 wolnych tokenów dla myślenia i generowania odpowiedzi.
2. **Kompaktowanie argumentów args i wyjść narzędzi w dawnych turach:**
   - W turach dawnych (starszych niż 12 ostatnich): args przycinane do 300 znaków, a content do 400 znaków.
   - W turach najnowszych (ostatnie 12): args i content przycinane do 2500 znaków.
3. **Dwuetapowa gwarancja budżetowa (Two-Phase Window Budgeting):**
   - Jeśli po wstępnym sformatowaniu łączny rozmiar przekracza 95 KB:
     - Gwarantowane zachowanie Turn 1 i Turn 2 (wymagania startowe, workspace).
     - Wypełnienie pozostałego budżetu najświeższymi turami idąc od końca.
     - Wstawienie czytelnej notatki: > [!NOTE] N intermediate turns omitted to fit within model context capacity.

---

## 39. Bezwzględny priorytet POST /api/v0/chat/continue w trwających sesjach, likwidacja niechcianych nowych konwersacji i zachowanie 100% historii (v2.43)

### ⚠️ Problem: Tworzenie się wielu nowych rozmów w trakcie dialogu, pomijanie POST /continue i ucinanie kontekstu
1. Podczas dłuższej konwersacji proxy przy błędzie klastra (np. `Server is temporarily unavailable.`) tworzyło zupełnie nowe sesje czatu w DeepSeek (`CREATE SESSION`), zamiast kontynuować dialog na dotychczasowym wątku.
2. Endpoint `POST /api/v0/chat/continue` (`stream_continue`) ani razu nie był wywoływany w sytuacjach awaryjnych lub ucięciach odpowiedzi.
3. W historii konwersacji (`conversation_history.md`) dochodziło do pomijania pośrednich tur, co obcinało modelowi kluczowy kontekst.

---

### 🔍 Przyczyna źródłowa (Root Cause)
1. **Niszczycielski blok `SESSION ROLLOVER` i kasowanie `conv_state`:**
   - W `server/services/proxy_service.py` blok obsługi błędu 503 wykonywał `SESSION ROLLOVER`, który usuwał wpis z `conv_state`:
     `dead_keys = [k for k, v in conv_state.items() if v.get("chat_id") == chat_id]; conv_state.pop(k)`.
   - W rezultacie przy następnym requeście z IDE funkcja `get_conv(messages)` nie znajdowała stanu sesji (`None`). Serwer błędnie klasyfikował żądanie jako nową rozmowę (`is_resume=False`), tworzył kolejny czat w UI DeepSeek (`create_session`), uploadował pliki od nowa i tworzył kolejne zbędne czaty.
2. **`STREAM MIGRATE` i `is_rate` blokowały `stream_continue`:**
   - Kod wykonujący retry przez `stream_continue` (`POST /api/v0/chat/continue`) w pętli `_STREAM_BACKOFF` znajdował się za blokami migracji konta, a warunki `if not is_rate` uniemożliwiały jego wykonanie przy błędach obciążeniowych klastra.
   - W efekcie `stream_continue` był martwym kodem (`DEAD CODE`) i proxy zamiast kontynuować przerwany strumień, porzucało sesję lub migrowało na drugie konto z nową sesją.
3. **Sztuczne pomijanie tur w `format_history_to_markdown`:**
   - Poprzednia wersja wprowadzała agresywne okienkowanie pomijające środkowe tury (`omitted intermediate turns`), przez co model tracił wiedzę o wynikach wcześniejszych narzędzi.

---

### 🛡️ Rozwiązanie (v2.43)
1. **Zasada Nienaruszalności Trwającej Sesji (`is_existing_session`):**
   - Zdefiniowano stan istniejącej konwersacji: `is_existing_session = (parent_id is not None) or (active_resp_id is not None)`.
   - W trakcie trwającego dialogu (Turn 2+) serwer ma **bezwzględny zakaz**:
     - tworzenia nowych sesji DeepSeeka (`create_session`),
     - kasowania stanu z `conv_state` (`conv_state.pop`),
     - porzucania dotychczasowego `chat_id`.
2. **Bezwzględny priorytet `stream_continue` na TEJ SAMEJ sesji:**
   - Przy wystąpieniu błędu strumienia lub ucięciu odpowiedzi, serwer w pierwszej kolejności wykonuje retry z odstępami (2s, 4s, 8s, 12s) wysyłając pakiety `: keep-alive\n\n` do IDE, aby zapobiec timeoutowi połączenia.
   - Jeśli `active_resp_id` jest znane, proxy natychmiast wywołuje `ds.stream_continue(account_idx, chat_id, active_resp_id)` (`POST /api/v0/chat/continue`), wznawiając generowanie od ostatniego tokena bez rozbijania sesji.
   - Jeśli `active_resp_id` nie jest znane, proxy ponawia `ds.stream_completion` z tym samym `parent_id` na tej samej sesji.
   - `STREAM MIGRATE` z tworzeniem nowego czatu jest dozwolone **wyłącznie** przy nowej sesji (`parent_id is None` i `active_resp_id is None`).
3. **Zachowanie 100% historii konwersacji bez ucinania kontekstu:**
   - `format_history_to_markdown` w `server/services/document_attachment_service.py` zachowuje 100% tur (Turn 1..N) bez jakiegokolwiek pomijania, formatując pełną treść i wywołania narzędzi.

---

## 40. Eliminacja zamarzania odpowiedzi na myśleniu, zakaz wycieku `thinking_fallback` w trybie narzędzi oraz odporność reprompt na błędy klastra (v2.44)

### ⚠️ Problem: Model urywał generację na fazie myślenia, a proxy wypluwało myśli do IDE i kończyło turę statusem `stop`
W trakcie pracy autonomicznej model zatrzymywał się po wygenerowaniu bufora myślenia (np. *"wants me to review the project structure and clean up... Let me do parallel exploration"*). W oknie czatu IDE pojawiał się czysty tekst myśli, model nie wykonywał żadnych narzędzi, a turę zamykał status `finish_reason: "stop"`, co powodowało zamrożenie pracy agenta.

**Przyczyny źródłowe:**
1. **Wyciek myśli jako odpowiedzi w trybie narzędzi (`proxy_service.py`):**
   Gdy model zamilkł po fazie myślenia i reprompt nie wygenerował tekstu ani narzędzi, proxy emitowało `thinking_fallback` jako treść asystenta do IDE. IDE traktowało to jako zakończenie wypowiedzi sukcesem.
2. **Cichy pożar w `ALREADY_FINISHED_REPROMPT`:**
   Gdy `POST /continue` zwracało `biz_code: 22` (`invalid message status`, wiadomość już ukończona na serwerze), proxy wysyłało ponaglenie `stream_completion`. Gdy w trakcie tego ponaglenia klaster DeepSeeka zwrócił błąd 503 (`Server is temporarily unavailable.`), blok `except Exception: break` po cichu połykał błąd, uniemożliwiając wejście w retry backoff.
3. **Pętla martwego `stream_continue` w `STREAM RESILIENCE`:**
   `STREAM RESILIENCE` próbowało wznawiać przez `stream_continue` wiadomość, która miała już status `FINISHED` lub `already_finished`, co w kółko powodowało błąd i wyczerpywało limit ponowień.

---

### 🛡️ Rozwiązanie (v2.44)
1. **Całkowita likwidacja wycieku `thinking_fallback` w trybie narzędzi:**
   - W trybie `bool(tools)` proxy ma bezwzględny zakaz wysyłania bufora myśli jako treści odpowiedzi asystenta.
   - Gdy model kończy bez tekstu i bez narzędzi, zgłaszany jest `RuntimeError("Premature stop: ...")`, co uruchamia nadrzędny mechanizm `STREAM RESILIENCE`.
2. **Propagacja błędów klastra w `ALREADY_FINISHED_REPROMPT`:**
   - Usunięto cichy `break` przy błędach reprompt – błąd jest rzucany wyżej (`raise`), dzięki czemu nadrzędna pętla `_STREAM_BACKOFF` wykonuje retry z odstępami 2s, 4s, 8s, 12s wysyłając pakiety `: keep-alive\n\n`.
3. **Strażnik `can_continue` w `STREAM RESILIENCE`:**
   - `stream_continue` jest dozwolone wyłącznie, gdy wiadomość NIE jest oznaczona jako `is_finished`, `already_finished` oraz nie posiada `thinking_fallback`.
   - Jeśli wiadomość jest sfinalizowana, ponowienie odbywa się wyłącznie za pomocą `stream_completion` z odpowiednim `parent_id`.

---

## 41. Automatyczny Account Failover / Session Rollover po wyczerpaniu STREAM BACKOFF i eliminacja błędu rl_time (v2.45)

### 💥 Problem
Gdy trwająca sesja na klastrze DeepSeeka ulegnie degradacji (np. zgromadzone >40k tokenów, 40+ wiadomości w drzewie, powtarzający się błąd 503 `Server is temporarily unavailable.` lub model milknący po fazie myślenia):
1. Mechanizm `STREAM RESILIENCE` wykonuje 4 próby ponowień (backoff 2s, 4s, 8s, 12s).
2. Po wyczerpaniu wszystkich 4 prób, kod nie podejmował żadnych działań naprawczych dla trwającej sesji (`is_existing_session == True`), lecz przepuszczał błąd na sam dół generatora SSE, co skutkowało wyrzuceniem w IDE komunikatu:
   `[Stream error: Premature stop: model stopped after thinking without tool call or response (intent: "...")]`.
3. Dodatkowo w gałęzi `STREAM RATE_LIMIT_RETRY` (`proxy_service.py:1448`) zmienna `rl_time` nie była zdefiniowana, powodując `NameError: name 'rl_time' is not defined`.
4. W procedurze `SESSION DEAD ROLLOVER` wcześniejsza implementacja obcinała ręcznie wiadomości do ostatnich 15 zamiast korzystać z centralnej procedury `_prepare_new_session_payload` ze standardem załącznika `conversation_history.md`.

---

### 🛡️ Rozwiązanie (v2.45)
1. **Automatyczny ratunek po wyczerpaniu `STREAM BACKOFF` (`proxy_service.py`):**
   - Gdy wszystkie 4 próby ponowień na istniejącej sesji zakończą się niepowodzeniem i do IDE nie wysłano jeszcze treści (`not content_already_sent` i `_rollover_depth < 2`):
     - Sprawdzana jest dostępność alternatywnego konta (`alt_acc`, np. Slot 0 gdy pracujemy na Slot 1).
     - Jeśli alternatywne konto jest sprawne i nie ma nałożonego limitu: wykonywany jest natychmiastowy **Account Failover** z załączeniem pełnej historii konwersacji jako `conversation_history.md`.
     - Jeśli brak alternatywnego konta lub drugie konto jest niedostępne: wykonywany jest natychmiastowy **Session Rollover** na bieżącym koncie z pełną historią w `conversation_history.md`.
     - IDE użytkownika nie otrzymuje żadnego błędu strumienia, a nowa sesja DeepSeeka przejmuje obsługę żądania z zachowaniem 100% kontekstu.
2. **Naprawa błędu `rl_time`:**
   - Wartość opóźnienia pobierana jest bezpiecznie jako `int(getattr(e, 'retry_after', 20))`, zabezpieczając proces przed niekontrolowanym wyjątkiem `NameError`.
3. **Standaryzacja `SESSION DEAD ROLLOVER`:**
   - W przypadku `is_session_dead` (gdy sesja wygasła lub została usunięta na serwerze DeepSeek), rollover odbywa się teraz w 100% za pośrednictwem `_prepare_new_session_payload`, eliminując sztuczne ucinanie promptu.

---

## 42. Prawidłowe zachowanie resp_msg_id i natychmiastowe wznawianie uciętych odpowiedzi (POST /continue) bez blokady myślenia (v2.46)

### 💥 Problem
W pliku `continue.har` użytkownik zarejestrował rzeczywisty przypadek z interfejsu DeepSeek Web:
Gdy strumień odpowiedzi zostanie przerwany (np. przez błąd klastra `Server is temporarily unavailable` w trakcie fazy myślenia lub generowania), na serwerze DeepSeeka wiadomość ma status `INCOMPLETE`. W interfejsie webowym użytkownik klika przycisk „Kontynuuj” (`POST /api/v0/chat/continue`), a model w 300 ms wznawia strumień i natychmiast emituje wywołania narzędzi (`｜｜DSML｜｜ calls`).

W proxy proces ten zawodził z dwóch krytycznych powodów:
1. **Bezwzględne kasowanie `resp_msg_id` po błędzie SSE (`deepseek_client.py:942`):**
   Gdy w trakcie strumienia wystąpił błąd `Server is temporarily unavailable.`, klient wykonywał `result_meta.pop("resp_msg_id", None)`. Przez to `active_resp_id` w proxy stawało się `None`, proxy uznawało sesję za nienawiązaną i porzucało ją tworząc nową pustą sesję na innym koncie (`[STREAM MIGRATE] New session failed on account 0, switching to account 1`), pozostawiając na klastrze nieukończoną wiadomość (`INCOMPLETE`)!
2. **Sztuczna blokada `and not stream_meta.get("thinking_fallback")` w `can_continue` (`proxy_service.py:1298`):**
   Gdy wiadomość została ucięta w fazie myślenia, `stream_meta["thinking_fallback"]` zawierało fragment myśli. Warunek w kodzie zakazywał wywołania `stream_continue`, zmuszając proxy do wołania `stream_completion`, co tworzyło nową gałąź w drzewie i desynchronizację parent_id.
3. **Sztuczne opóźnienie throttle (16 sekund):**
   Wywołania continue i reprompt wchodziły w pętlę opóźnienia `_throttle`, podczas gdy przeglądarka wysyła `POST /continue` natychmiast.

---

### 🛡️ Rozwiązanie (v2.46)
1. **Ochrona `resp_msg_id` przy błędach SSE (`deepseek_client.py`):**
   `resp_msg_id` jest usuwane wyłącznie, gdy pakiet błędu z serwera DeepSeek zawiera explicite `clear_response: True`. W każdym innym przypadku (np. transient 503) ID wiadomości zostaje nienaruszone w `result_meta["resp_msg_id"]`.
2. **Odblokowanie `stream_continue` dla uciętego myślenia (`proxy_service.py`):**
   Usunięto warunek `and not stream_meta.get("thinking_fallback")` z `can_continue`. Jeśli wiadomość nie została oznaczona jako `is_finished` na serwerze, proxy natychmiast wywołuje `POST /api/v0/chat/continue` z `throttle=False`, dokładnie tak jak robi to przeglądarka po kliknięciu „Kontynuuj”.
3. **Płynne dokończenie odpowiedzi bez tworzenia niepotrzebnych sesji:**
   Ucięty strumień natychmiast podejmuje generowanie z klastra DeepSeeka i emituje bloki narzędzi bezpośrednio do IDE.

---

## 43. Priorytetyzacja kontenerów tool_calls w Sieve i likwidacja 15s opóźnienia throttle w pętli narzędziowej (v2.47)

### 💥 Problem
Po wykonaniu kilku pierwszych narzędzi agent zaczynał się „zacinać” i zatrzymywać co chwilę:
1. **Sztuczne zamrażanie na 15–20 sekund (`deepseek_client.py` i `proxy_service.py`):**
   Przed wysłaniem każdego żądania w pętli narzędziowej proxy wywoływało `await ds.async_throttle(account_idx)`. Funkcja ta miała stały `target = 15.0s + jitter`, który został pierwotnie zaprojektowany wyłącznie dla tworzenia nowych sesji, a nie dla kontynuacji (`is_resume`). W rezultacie po każdym wykonanym narzędziu agent czekał 13–18 sekund przed kolejnym krokiem.
2. **Przedwczesne rozcinanie kontenerów `<tool_calls>` w `dsml_sieve.py`:**
   W procedurze `_is_capture_complete()` sprawdzanie zbalansowanych tagów `<invoke>` (`_opens == _closes`) znajdowało się przed sprawdzaniem kontenera nadrzędnego `<tool_calls>`. Gdy model wygenerował kontener zawierający wiele wywołań narzędzi, Sieve po zamknięciu pierwszego `<invoke>` natychmiast uznawał przechwytywanie za zakończone (`True`), odcinając resztę bufora. W rezultacie parser zwracał `calls=None`, surowy XML wyciekał do IDE jako tekst, a IDE przerywało pracę wysyłając powiadomienia `<system_reminder>Please continue</system_reminder>`.

---

### 🛡️ Rozwiązanie (v2.47)
1. **Likwidacja opóźnienia w pętli narzędziowej (`deepseek_client.py` & `proxy_service.py`):**
   Wprowadzono flagę `is_resume=True` do metod `_throttle` oraz `async_throttle`. Dla tur kontynuacji konwersacji po tool results opóźnienie docelowe wynosi zaledwie `1.0s` (zamiast 15–20s), co eliminuje wielosekundowe zamrażanie agenta i zapewnia płynną pracę.
2. **Bezwzględny priorytet kontenerów nadrzędnych w `dsml_sieve.py`:**
   Sprawdzanie obecności i domknięcia kontenerów `<tool_calls>`, `<tool_dispatch>` oraz `<|DSML|calls` zostało przeniesione na sam początek `_is_capture_complete()`. Capture nie może zostać zakończony, dopóki nie nadejdzie zamykający tag kontenera `</tool_calls>`, co gwarantuje prawidłowe sparsowanie wszystkich zawartych w nim wywołań narzędzi bez rozcinania i gubienia parametrów.

---

## 44. Naprawa błędu NameError w async_throttle, ochrona awaitable i jawne logowanie błędów strumienia (v2.48)

### 💥 Problem
Po wprowadzeniu flagi `is_resume` w v2.47 serwer natychmiast przestawał odpowiadać po zbudowaniu promptu (`[TIMING] t2-prompt_built: ...`), a klient IDE otrzymywał błąd HTTP 502 Bad Gateway:
1. **Zmienna lokalna `is_resume` zamiast `parsed.is_resume` w `proxy_service.py:2357`:**
   Wywołanie `await ds.async_throttle(account_idx, is_resume=is_resume)` odwoływało się do nieistniejącej zmiennej lokalnej `is_resume` (w zasięgu `chat_completions` flaga ta znajduje się w obiekcie `parsed.is_resume`). W rezultacie Python rzucał natychmiastowy `NameError: name 'is_resume' is not defined`.
2. **Cichy błąd bez logowania w logach serwera:**
   Blok `except Exception as e` w pętli retry rzucał `HTTPException(502, ...)` bez uprzedniego wywołania `logger.error()`, przez co w `server_stdout.log` request urywał się bez widocznego śladu błędu.
3. **Konflikt mocków w testach jednostkowych (`await MagicMock`):**
   W testach mockujących klienta `ds` jako `MagicMock()`, wywołanie `await ds.async_throttle(...)` rzucało `TypeError: object MagicMock can't be used in 'await' expression`.

---

### 🛡️ Rozwiązanie (v2.48)
1. **Prawidłowe przekazanie `parsed.is_resume`:**
   W `proxy_service.py` poprawiono odwołanie na `is_resume=parsed.is_resume`.
2. **Ochrona awaitable przez `inspect.isawaitable`:**
   Zabezpieczono oczekiwanie na `ds.async_throttle`:
   ```python
   throttle_res = ds.async_throttle(account_idx, is_resume=parsed.is_resume)
   if inspect.isawaitable(throttle_res):
       await throttle_res
   ```
   Dzięki temu środowisko produkcyjne zachowuje pełne asynchroniczne throttlowanie bez blokowania pętli asyncio, a testy jednostkowe z mockami wykonują się bezbłędnie.
3. **Jawne logowanie błędów strumienia:**
   Przed podniesieniem `HTTPException(502, ...)` dodano `logger.error(f"[STREAM_FAILED] attempt={attempt} account={account_idx} chat_id={...}: {err_str}")`, co gwarantuje pełną transparentność awarii.

---

## 45. Automatyczny Reprompt przy uszkodzonym XML znaczników narzędzi (unparsed_tool_markup) i rozszerzona naprawa direct tags (v2.49)

### 💥 Problem
W niektórych turach konwersacji agent w IDE niespodziewanie zamilkł i zatrzymywał się:
1. **Wycofywanie uszkodzonego bloku narzędzia jako tekstu (`calls=None`):**
   Gdy model wyemitował znaczniki narzędzi (np. `<tool_calls>...`), ale parser `parse_dsml_tool_calls` nie był w stanie wyodrębnić narzędzia (np. ucięty fragment, niestandardowy tag `<Shell>`, brak tagu `<invoke>`), Sieve uznawał blok za zakończony i zwracał go jako `SieveEvent("text", prefix_text)`. W rezultacie surowy XML wyciekał do IDE jako zwykła treść wiadomości asystenta.
2. **Przedwczesne `finish_reason: "stop"` zamiast wywołania narzędzia:**
   Ponieważ do IDE trafiło kilkaset znaków tekstu, warunek `silent_model` był fałszywy, a `_is_intent_without_action` nie sprawdzał obecności tagów XML. W efekcie proxy kończyło strumień ze statusem `stop`, a IDE czekało na użytkownika zamiast wykonać narzędzie.
3. **Brak domykania `<invoke>` i `<tool_calls>` w `repair_tier3`:**
   Dotychczasowa implementacja `repair_tier3` domykała wyłącznie tagi `<tool_call>` (w liczbie pojedynczej), ignorując ucięte tagi `<invoke>` i `<tool_calls>`.
4. **Brak obsługi direct tool tags (`<Shell>...` / `<Read .../>`):**
   Gdy model używał nazwy narzędzia bezpośrednio jako tagu XML, brakowało konwersji do formatu `<invoke name="...">`.

---

### 🛡️ Rozwiązanie (v2.49)
1. **Wykrywanie `unparsed_tool_markup` w `proxy_service.py`:**
   Wprowadzono strażnika sprawdzającego, czy wyemitowany tekst zawiera znaczniki narzędzi bez sparsowanego wywołania:
   ```python
   unparsed_tool_markup = bool(
       tools
       and not handler._had_tool_calls
       and not has_final_answer
       and re.search(
           r"<(?:\|?(?:TOOL|DSML)\|?)?(?:tool_calls?|tool_dispatch|tool_call|toolcall|invoke)\b",
           text_buffer,
           re.IGNORECASE,
       )
   )
   ```
2. **Automatyczny agentic reprompt:**
   Włączenie `unparsed_tool_markup` do `should_continue` i `should_reprompt` wymusza natychmiastowe wysłanie reprompt do DeepSeeka z żądaniem ponownego wygenerowania narzędzia w ścisłym formacie DSML XML, bez zatrzymywania się w IDE.
3. **Rozszerzenie `repair_tier3` o domykanie `<invoke>` i `<tool_calls>`:**
   Automatyczne domykanie niedomkniętych tagów `<invoke>`, `<tool_calls>` oraz `<tool_dispatch>` przy uciętych strumieniach.
4. **Konwersja direct tool tags w `repair_tier1` (`_fix_direct_tool_tags`):**
   Obsługa bezpośrednich znaczników `<Shell>`, `<Read file_path="..."/>` itp. poprzez automatyczną transformację do standardowego `<invoke name="...">`.
5. **Uzupełnienie parametrów w `repair_tier2`:**
   Dodano `"Shell": "command"` oraz `"AwaitShell": "shell_id"` do `_TOOL_PARAM_MAP`.

---

## 46. Natychmiastowy Session Rollover i Account Failover przy Length limit reached na najmniej używanym koncie z załączeniem conversation_history.md (v2.50)

### 🔴 Problem
Gdy trwająca sesja na DeepSeek API przekraczała limit długości kontekstu modelu, DeepSeek zwracał błąd:
`{"event": "[STREAM ERROR] DeepSeek error: Length limit reached. Please start a new chat.", "service": "deepseek-proxy", "timestamp": "2026-09-19T23:17:44.814078+00:00", "level": "error"}`.
Wcześniejszy kod serwera proxy:
1. **Wpadał w 4-krotną pętlę ponowień `_STREAM_BACKOFF` (2s, 4s, 8s, 12s) na TEJ SAMEJ SESJI**:
   Warunek retry sprawdzał tylko `not is_session_dead`, zapominając o `not is_len`. W efekcie proxy ponawiało próbę 4 razy na sesji, która była już trwale przepełniona i odrzucała każde zapytanie.
2. **Kaskada opóźnień (Throttling + Backoff > 35s)**:
   Każde ponowienie na przepełnionej sesji natychmiast kończyło się błędem i dodatkowym opóźnieniem throttle (np. 12-18s), w efekcie czego klient IDE (Kiro/Trae) zrywał połączenie HTTP lub wyświetlał błąd użytkownikowi zanim proxy zdążyło przejść do procedury rescue.
3. **Pominięcie `is_len` w natychmiastowym rolloverze**:
   Blok natychmiastowego ratowania obsługiwał wyłącznie `is_session_dead`, ignorując fakt, że `is_len` jest błędem tak samo definitywnym i trwałym.
4. **Brak inteligentnego wyboru najmniej obciążonego konta**:
   Przy rolloverze proxy wybierało to samo konto lub brało pierwsze lepsze z listy (`alts[0]`), zamiast wybrać slot o najmniejszej liczbie aktywnych sesji i najdłuższym odpoczynku od ostatniego zapytania.
5. **Blokada rolloveru w `chat_completions` dla `is_resume`**:
   W pętli zewnętrznej `chat_completions` warunek brzmiał `if is_len_e and attempt == 0 and not parsed.is_resume:`, co uniemożliwiało wykonanie rolloveru, gdy błąd wystąpił w trybie wznawiania.

---

### 🛡️ Rozwiązanie (v2.50)

1. **Inteligentny selektor najmniej obciążonego konta (`_select_least_loaded_account`)**:
   Wprowadzono funkcję pomocniczą wybierającą optymalne konto dla nowej sesji:
   - Pomija konta z aktywnym statusem rate-limit.
   - Preferuje konto alternatywne wobec konta, na którym nastąpiło przepełnienie (`exclude_slot`).
   - Sortuje kandydatów według najmniejszej liczby aktywnych sesji (`session_manager.get_count`) oraz najdłuższego czasu bezczynności od ostatniego zapytania (`ds._last_request_time`).
2. **Natychmiastowy Session Rollover & Account Failover w `_stream_gen`**:
   Gdy wystąpi błąd `is_len` (lub `is_session_dead`), proxy nie marnuje czasu na retry:
   ```python
   if (is_session_dead or is_len) and not content_already_sent and _depth < 4:
       cause_name = "LENGTH LIMIT EXCEEDED" if is_len else "SESSION DEAD"
       # 1. Wyczyszczenie stanu starej sesji
       clear_conv_by_messages(messages)
       # 2. Wybór najmniej obciążonego konta
       target_slot = _select_least_loaded_account(exclude_slot=account_idx)
       # 3. Utworzenie nowej sesji
       new_chat_id = ds.create_session(target_slot)
       # 4. Spakowanie 100% historii do conversation_history.md (limit 95 KB)
       full_prompt, file_ids = _prepare_new_session_payload(
           target_slot=target_slot,
           messages=messages,
           tools=tools,
           model_type=model_type or "default",
       )
       # 5. Strumieniowanie nowej sesji do klienta IDE
       gen_roll, meta_roll = ds.stream_completion(target_slot, new_chat_id, full_prompt, None, ref_file_ids=file_ids, ...)
       yield from _stream_gen(...)
       return
   ```
3. **Bezwzględny zakaz retry na tej samej sesji dla `is_len`**:
   Do warunku `_STREAM_BACKOFF` dodano `and not is_len`:
   ```python
   if is_existing_session and not is_session_dead and not is_len and not content_already_sent and _depth < 4:
   ```
4. **Obsługa rolloveru w `chat_completions` dla `is_resume`**:
   Gdy błąd `is_len_e` zostanie przechwycony na poziomie `chat_completions` przy `parsed.is_resume=True`, proxy czyści stary stan sesji, wybiera `target_slot` przez `_select_least_loaded_account`, przygotowuje payload z `conversation_history.md` i kontynuuje przetwarzanie w nowej sesji bez zwracania błędu 502 do IDE.

---

## 47. Eliminacja blokady pętli asyncio przy streamingu, usunięcie przedwczesnych keep-alive oraz kompaktowanie dawnych tur historii (v2.51)

### ⚠️ Problem: Pozorny freeze po `[CLEAR_CONV]`, timeouty połączenia HTTP i 900k tokenów w historii
Podczas automatycznego rolloveru przy błędzie `Length limit reached` proces serwera wydawał się zatrzymywać dokładnie na linii:
`{"event": "[CLEAR_CONV] Cleared state for hash='...' chat_id='...'"}`, po czym klient IDE zgłaszał błąd połączenia (`Stream interrupted` / `ERR_CONNECTION_TIMEDOUT`), a endpoint `/health` przestawał odpowiadać.

**Zidentyfikowane przyczyny źródłowe:**
1. **Blokujący `next(gen)` w głównym wątku asyncio (`proxy_service.py`):**
   W funkcji `async def chat_completions(...)` wywoływano `first_chunk = next(gen)` w celu „primingu” generatora. W trybie rolloveru `next(gen)` uruchamiało synchronicznie: PoW, upload załączników, polling statusu plików oraz inicjalizację DeepSeek — blokując główny wątek pętli event loop asyncio FastAPI na 10–35 sekund! Przez ten czas serwer nie odsyłał do klienta nagłówków HTTP 200 OK, co powodowało timeout socketu po stronie IDE.
2. **Przedwczesne komentarze SSE `: keep-alive\n\n` przed wysłaniem danych OpenAI:**
   W bloku rolloveru wywoływano surowe `yield ": keep-alive\n\n"`. Klienty IDE (Kiro/Trae) oparte na parserze OpenAI Chat Completions po otrzymaniu surowego komentarza SSE zamiast `data: {...}` traktowały to jako błąd protokołu i natychmiast zrywały socket TCP, przerywając generator Starlette.
3. **Niekontrolowany rozrost `conversation_history.md` (2.88 MB / 909 601 tokenów):**
   Przy 1500+ turach formatowanie pełnych zrzutów narzędzi (zwłaszcza odczytów plików i diffów) generowało plik o rozmiarze prawie 3 MB, co powodowało token usage na poziomie ~910k tokenów i drastycznie wydłużało upload oraz przetwarzanie przez klaster DeepSeek.

---

### 🛡️ Wdrożone rozwiązania (v2.51)

1. **Natychmiastowy zwrot `StreamingResponse` bez blokowania pętli asyncio:**
   W trybie `parsed.stream=True` funkcja `chat_completions` natychmiast zwraca `StreamingResponse(gen, ...)`. Nagłówki HTTP 200 OK są wysyłane do klienta IDE w pierwszej milisekundzie, a generator synchroniczny `gen` jest wykonywany przez Starlette w puli wątków (`anyio.to_thread.run_sync`), zachowując 100% responsywności pętli asyncio serwera i endpointu `/health`.
2. **Usunięcie surowych komentarzy `: keep-alive\n\n` z procedury rolloveru:**
   Zlikwidowano przedwczesne `yield ": keep-alive\n\n"`. Generator czeka na rzeczywisty strumień chunków z nowej sesji DeepSeek i natychmiast przekazuje prawidłowe chunki formatu OpenAI `data: {"choices": ...}`.
3. **Inteligentne kompaktowanie dawnych tur w `document_attachment_service.py`:**
   Dla tur starszych niż 15 ostatnich:
   - `content` jest przycinany do 400 znaków (z dopiskiem `... [truncated for brevity]`),
   - `fargs` wywołań narzędzi są przycinane do 250 znaków.
   Wszystkie tury (100% historii konwersacji) pozostają w pliku, ale rozmiar załącznika spada z 2.88 MB do ~400 KB, redukując zużycie tokenów i przyspieszając upload oraz przetwarzanie o ponad 80%.

---

## 48. Zwolnienie połączenia curl_cffi w bloku `finally` i granularne logowanie kroków Rolloveru (v2.52)

### ⚠️ Problem: Trwały deadlock puli TLS libcurl/curl_cffi po przerwaniu strumienia na błędzie `Length limit reached`
Podczas wystąpienia błędu `Length limit reached. Please start a new chat.`, generator strumienia SSE w `deepseek_client.py` rzucał wyjątek `RuntimeError`. Z powodu braku bloku `finally: r.close()` obiekt odpowiedzi `curl_cffi` (`r = requests.post(..., stream=True)`) pozostawał otwarty w pamięci libcurl.
Na systemach Windows libcurl współdzieli wewnętrzny kontekst sesji TLS/WSA socketów. Porzucenie nieodczytanego do końca strumienia HTTP/2 lub HTTP/1.1 z otwartym uchwytem gniazda powodowało, że dowolne kolejne synchroniczne wywołanie `r = self._http[slot].post(f"{self.BASE_URL}/api/v0/chat_session/create")` zawieszało się na nieokreślony czas wewnątrz kodu natywnego biblioteki C, ignorując nawet parametr `timeout=30`. W efekcie po logu:
`[CLEAR_CONV] Cleared state for hash='...' chat_id='...'`
serwer zastygał w zupełnej ciszy bez żadnego błędu ani timeoutu.

---

### 🛡️ Wdrożone rozwiązania (v2.52)

1. **Bezwzględne `finally: r.close()` w `_stream()` (`deepseek_client.py`):**
   W metodzie `_build_stream_iterator` w wewnętrznym generatorze `_stream()` dodano blok `finally:`, który gwarantuje wywołanie `r.close()` niezależnie od tego, czy strumień zakończył się sukcesem, wyjątkiem (`RuntimeError`, `DeepSeekRateLimitError`), czy przerwaniem przez konsumenta generatora:
   ```python
   finally:
       try:
           r.close()
       except Exception:
           pass
   ```
   Zapewnia to natychmiastowe zwolnienie gniazda i kontekstu TLS do systemu operacyjnego, eliminując deadlocki libcurl przy kolejnych żądaniach HTTP.

2. **Zabezpieczenie `stream_continue` przed wyciekiem gniazda przy Rate Limit:**
   Przed rzuceniem `DeepSeekRateLimitError` w strumieniu kontynuacji dodano jawne zamknięcie `r.close()`.

3. **Granularne logowanie STEP 1–5 procedury Rolloveru (`proxy_service.py`):**
   W bloku rolloveru po wyczyszczeniu stanu sesji dodano logowanie każdego etapu z osobna:
   - `STEP1: selected target_slot=... (excluded account_idx=...)`
   - `STEP2: creating session on slot=... (throttle=False)...`
   - `STEP3: session created ..., preparing payload with conversation_history.md...`
   - `STEP4: payload ready (prompt_len=..., file_ids=...), starting stream_completion...`
   - `STEP5: stream started, delegating to _stream_gen...`

---

## 49. Eliminacja samoblokady (Self-Deadlock) na `threading.Lock` w `clear_conv_by_messages` i przejście na `threading.RLock` (v2.53)

### ⚠️ Problem: Całkowite zamarznięcie procesu serwera po logu `[CLEAR_CONV]`
W logach produkcyjnych zaobserwowano, że po wystąpieniu błędu klastra DeepSeek `Length limit reached. Please start a new chat.` i wejściu w procedurę rolloveru:
```
{"event": "[LENGTH LIMIT EXCEEDED ROLLOVER] Session ... Immediately rolling over to fresh session with conversation_history.md..."}
{"event": "[CLEAR_CONV] Cleared state for hash='...' chat_id='...'"}
```
serwer zastygał bezpowrotnie. Żadne logi `STEP0`, `STEP1` ani żaden wyjątek nie pojawiały się, a kolejne żądania przychodzące z IDE zawieszały się natychmiast po `[RAW FIRST MSG FULL]`.

---

### 🔍 Przyczyna źródłowa (Root Cause Analysis)
1. **Niereentrantny `threading.Lock` w `state_service.py`:**
   Obiekt synchronizacji stanu konwersacji był zdefiniowany jako:
   ```python
   conv_lock = threading.Lock()
   ```
2. **Zagnieżdżona próba pozyskania zamka (Self-Deadlock) w `clear_conv_by_messages`:**
   W funkcji `clear_conv_by_messages` wątek generatora pobierał zamek `with conv_lock:`, a następnie wewnątrz tego samego bloku wywoływał `_flush_conv_state()`:
   ```python
   with conv_lock:
       ...
       logger.info(f"[CLEAR_CONV] Cleared state for hash={h!r} chat_id={chat_id!r}")
       _flush_conv_state()  # <-- BŁĄD ARCHITEKTONICZNY!
       return h
   ```
   Funkcja `_flush_conv_state()` również zawierała blok `with conv_lock:`. Ponieważ `threading.Lock` w Pythonie nie jest reentrantny, ten sam wątek próbując powtórnie zająć posiadany już przez siebie zamek wpadał w permanentną samoblokadę (**Self-Deadlock**) w jądrze systemu operacyjnego.
3. **Kaskadowy paraliż kolejnych żądań:**
   Zablokowany `conv_lock` nigdy nie był zwalniany. Każde kolejne żądanie z IDE (np. kolejne wywołanie `/v1/chat/completions`) dochodziło do linii `state = get_conv(messages)`, gdzie próba wejścia w `with conv_lock:` powodowała natychmiastowe zawieszenie wątku w kolejce do zablokowanego mutexu.

---

### 🛡️ Wdrożone rozwiązania (v2.53)

1. **Reentrantny zamek `threading.RLock()` w `state_service.py`:**
   Zastąpiono zwykły mutex zamkiem reentrantnym:
   ```python
   conv_lock = threading.RLock()
   ```
   Umożliwia to temu samemu wątkowi bezpieczne, wielokrotne zagnieżdżanie bloków `with conv_lock:` bez ryzyka deadlocka.

2. **Wyprowadzenie `_flush_conv_state()` poza blok zamka w `clear_conv_by_messages`:**
   Dla zachowania czystości i minimalizacji czasu trzymania blokady pamięci podręcznej, zapis na dysk `_flush_conv_state()` został przeniesiony po zwolnieniu `with conv_lock:` (wzorzec tożsamy z `set_conv`):
   ```python
   cleared = False
   with conv_lock:
       if h in conv_state:
           ...
           logger.info(f"[CLEAR_CONV] Cleared state for hash={h!r} chat_id={chat_id!r}")
           cleared = True

   if cleared:
       _flush_conv_state()
       return h
   ```

3. **Weryfikacja automatyczna:**
   - Test jednostkowy sprawdzający czyszczenie stanu i brak deadlocka przeszedł pomyślnie.
   - Wszystkie testy regresyjne (`tests/test_stream_gen.py`, `tests/test_history_in_file_and_migrate.py`) zakończone 100% sukcesem (28/28 passed).
   - Zrestartowany proces proxy poprawnie odpowiada na `/health` i jest gotowy do obsługi ruchu.

---

**Ostatnia aktualizacja:** 2026-09-20  
**Wersja dokumentu:** 2.53  

**Autor:** Antigravity AI Assistant

**⚠️ UWAGA DLA WSZYSTKICH AGENTÓW:**
Jeśli pracujesz nad `deepseek-proxy`, **MUSISZ** przeczytać sekcję "RESUME NIGDY NIE JEST POCZĄTKIEM ROZMOWY" na początku tego dokumentu. To najczęstszy błąd prowadzący do problemów z tools schema.










