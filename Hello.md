# Zapoznaj się z projektami

> **Workspace:** c:\Users\Ksawier\Pictures\Screenshots

---

**User**

`/c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/cortex-app/ai_supervisor``/c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean` zapoznaj sie z tymi projektami. 
bo gemini zrobil rozpidziec, i glownym zajeciem bedzie ten superviso. ale on mnie srednio rozumie  izrobic tlyko poczatkowy design. wiec no potrzebuje troche poplanowac dalej. nie jestem techniczny, odpoisuj krotko

**Assistant**

Zapoznaję się z oboma projektami równolegle.








































## Analiza projektu Cortex / ai_supervisor

### 1. Struktura katalogów i główne pliki

Projekt `cortex-app` to aplikacja Electron + React. Kluczowy katalog **`ai_supervisor/`** zawiera wyłącznie 3 pliki:

- `PLAN_WDROZENIA.md` — dokument architektoniczny modułu nadzoru wielu łańcuchów AI (multi-pipeline)
- `schema.json` — formalny schemat JSON (JSON Schema draft-07) definiujący format pojedynczego kroku/zdarzenia łańcucha AI
- `showcase.html` — samodzielny, interaktywny prototyp HTML demonstrujący UI nadzoru

Poza `ai_supervisor/` aplikacja zawiera:

- `src/main/` — proces główny Electrona (`index.ts`), warstwa IPC (`ElectronIpcBridge.ts`), silnik zapisu JSON (`StorageEngine.ts`)
- `src/components/canvas/` — komponenty React: `NotesCanvas.tsx`, `CanvasHeader.tsx`, `CanvasFooter.tsx`, `MacroProjectCard.tsx`, `NoteCard.tsx`, `PortalCard.tsx`, `HelpModal.tsx`, warstwy linii, ikony, utils
- `src/shared/types/ipc.ts` — typowany mostek IPC
- `src/types.ts` — modele domenowe: `Projekt`, `ProjektyNode`, `ProjektyEdge`, `ProjektyNodeAnnotation`
- Konfiguracja: `electron.vite.config.ts`, `vite.config.ts`, `tsconfig.json`, `vitest.config.ts`, `package.json`, `.env.example`, `.npmrc.example`

**Brak pliku README** w całym projekcie — dokumentacją zastępczą jest `PLAN_WDROZENIA.md`.

### 2. Cel projektu

Projekt ma dwa zasadnicze cele:

1. **Cortex — aplikacja notatkowa wizualna (canvas)** — główna część działająca. Umożliwia tworzenie projektów („tablic"), notatek jako kartek na nieskończonym płótnie, łączenie ich krawędziami, grupowanie w tzw. portale (wydzielanie gałęzi do nowego projektu) oraz zarządzanie projektami w widoku makro.

2. **ai_supervisor — moduł nadzoru wielu łańcuchów AI** — faza projektowa/prototypowa. Koncepcja zakłada dodanie do Cortex modułu nadzorującego wiele niezależnych łańcuchów AI (np. Generator Ofert B2B, Weryfikator Umów, Analiza Faktur). Użytkownik widzi oś kroków (timeline) dla wybranego łańcucha i inspektora kroku z 3 zakładkami: *Prompty Wejściowe*, *Pliki i Źródła*, *Myśli & Rozmowa*. Kroki mogą mieć statusy (`WYKONANO`, `W_TOKU`, `CZEKA_NA_CZLOWIEKA`, `W_KOLEJCE`, `BLAD`) oraz flagę `wymaga_akceptacji` (bramka). Istnieje przełącznik trybu akceptacji: `Ręczny (Bramki)` / `Automatyczny (Auto-Approve)`.

### 3. Użyte technologie

- **Electron 42** + **electron-vite 4** (trzy targe-ty: main, preload, renderer)
- **React 19** + **React DOM 19**
- **TypeScript ~5.8** (strict, ES2022, `moduleResolution: bundler`)
- **Vite 6** + `@vitejs/plugin-react`
- **Tailwind CSS 4** (przez `@tailwindcss/vite`)
- **Vitest 4** + Testing Library (React, DOM, user-event) + `jsdom` — testy
- **electron-builder 26** — budowanie instalatorów NSIS/DMG/AppImage
- **esbuild**, **concurrently**, **rimraf**
- **IPC Electron** z `contextIsolation: true`, `sandbox: false`, preload z `contextBridge` — bezpieczny mostek `nexusBridge`
- **Storage** — własny `StorageEngine` oparty na plikach JSON (atomowy zapis tmp → rename + backup `.bak`)

### 4. Co działa, a co jest niekompletne / szkicowe

**Działa:**
- Pełny interfejs canvas z notatkami, projektami, krawędziami i portalami (komponenty React kompletne)
- Persistencja do JSON przez StorageEngine + IPC bridge
- Testy komponentów (np. `NotesCanvas.test.tsx`)
- Dwa tryby uruchomienia: `npm run dev` (Electron) i `npm run dev:renderer` (czysty web na porcie 3000)
- Build produkcyjny Electron + instalator NSIS

**Niekompletne / szkicowe — „początkowy design":**
- **Moduł ai_supervisor NIE jest zintegrowany z resztą aplikacji.** To wyłącznie koncepcja + statyczny prototyp HTML. Nie ma żadnego kodu React/TypeScript implementującego nadzór pipeline'ów, nie ma IPC handlеrów ani storage dla pipeline'ów.
- `showcase.html` to czysto frontendowy mock-up: dane łańcuchów są **zaszyte na sztywno w JS** (`pipelinesDatabase`), przyciski akcji (`Przerwij cały proces`, `Cofnij krok wstecz`) tylko wywołują `notify()` — nie wykonują realnych operacji. Zatwierdzanie kroku (`approveCurrentStep`) jedynie mutuje lokalny obiekt i zmienia statusy.
- `PLAN_WDROZENIA.md` opisuje, że AI samo dodaje łańcuch do `data/pipelines/*.json` a Cortex „automatycznie wykrywa" pliki — **to jeszcze nie istnieje**.
- `schema.json` definiuje format jednego zdarzenia/kroku, ale nie format całego łańcucha (brak pola `steps` na poziomie pipeline'a).
- W `src/App.tsx` jedynym komponentem jest `NotesCanvas` — brak jakiegokolwiek wejścia dla nadzorcy AI.
- Brak README, brak testów dla ai_supervisor, brak typów w `src/types.ts` dla pipeline'ów.

### 5. Główne komponenty / moduły

**Warstwa Electron (main process):**
- `src/main/index.ts` — bootstrap aplikacji; tworzy `StorageEngine` + `ElectronIpcBridge`, ustawia CSP (umożliwia połączenia do Gemini/DeepSeek/OpenRouter), obsługuje single-instance lock, ładowanie renderera (dev: `http://localhost:3000`, prod: plik `out/renderer/index.html`).
- `src/main/storage/StorageEngine.ts` — zarządza zapisem projektów, węzłów, krawędzi i adnotacji jako pojedynczych plików JSON w `data/projekty/{projects,nodes,edges,annotations}`.
- `src/main/ipc/ElectronIpcBridge.ts` — rejestruje 12 handlerów IPC dla CRUD projektów, węzłów, krawędzi i adnotacji.
- `src/main/preload.ts` — wystawia typowany obiekt `nexusBridge` przez `contextBridge`.

**Warstwa Renderer (React):**
- `NotesCanvas.tsx` — główny kontener canvas; zarządza stanem, ładowaniem danych, widokiem makro/mikro, trybem łączenia, edycją, zaznaczaniem, klawiaturą i skrótami.
- `CanvasHeader.tsx` — nagłówek: selektor projektów, breadcrumbs, przyciski akcji.
- `CanvasFooter.tsx` — pasek podpowiedzi i akcji zależny od widoku (makro/mikro).
- `MacroProjectCard.tsx` — karta projektu na tablicy makro.
- `NoteCard.tsx` — pojedyncza notatka; edycja inline, bionic reading, usuwanie, łączenie przez Tab.
- `PortalCard.tsx` — specjalny węzeł grupujący połączone notatki i pozwalający przenieść je do nowej tablicy.
- `ConnectionLinesLayer.tsx` / `ConnectedIslandsLayer.tsx` — rysowanie krawędzi i wysp.
- `HelpModal.tsx` — modal ze skrótami klawiszowymi.

**Konfiguracja / tooling:**
- `electron.vite.config.ts` — konfiguracja trzech celów builda, alias `@`, podmiana CSP (usuwanie `crossorigin`), Tailwind + React plugin.
- `vite.config.ts` — alternatywna konfiguracja czystego renderera dla web dev.
- `package.json` — skrypty dev/build/test, zależności, konfiguracja electron-builder (NSIS, DMG, AppImage).
- `vitest.config.ts`, `tsconfig.json`, `.env.example` (Gemini API Key, APP_URL), `.npmrc.example` (ścieżka Pythona).

### Najważniejsze wnioski

1. **Ai_supervisor to w 100% faza koncepcyjna/prototypowa** — dokument planu, schema i statyczny showcase HTML. Nie ma ani jednej linii produkcyjnego kodu integrującego nadzór AI z aplikacją Electron/React. Wszystkie przyciski w `showcase.html` są atrapami.

2. **Rdzeń aplikacji (canvas notatek) jest jednak rozbudowany i dopracowany** — z pełną warstwą storage, IPC, bezpiecznym preload, testami i konfiguracją builda. To solidna baza, na której można zbudować moduł nadzorczy.

3. **Brak spójnej typizacji i integracji pipeline'ów** — `schema.json` definiuje pojedynczy krok, ale w `src/types.ts` nie ma typów `Pipeline`/`PipelineStep`, nie ma również żadnych struktur do przechowywania łańcuchów w StorageEngine.

4. **Dokumentacja planu jest ambitna** — zakłada auto-wykrywanie plików `data/pipelines/*.json` przez AI i dynamiczne dodawanie łańcuchów do selektora UI. To wymaga implementacji od zera: warstwy detekcji plików, IPC, stanów kroków, trybu auto-approve i realnych akcji zatwierdzania/wstrzymywania.

5. **Środowisko AI jest już przygotowane w CSP** — nagłówek `Content-Security-Policy` w `src/main/index.ts` zezwala na połączenia do `generativelanguage.googleapis.com` (Gemini), `api.deepseek.com` i `openrouter.ai`, co sugeruje planowaną integrację z zewnętrznymi modelami LLM w przyszłości.

## Analiza projektu `deepseek-proxy-clean`

### 1. Struktura katalogów i główne pliki

```
deepseek-proxy-clean/
├── server.py                    # GŁÓWNY serwer proxy (FastAPI/uvicorn, port 4570, ~4000 linii)
├── official_api.py              # Klient oficjalnego DeepSeek API (api.deepseek.com)
├── pow.py                       # Solver Proof-of-Work (WASM sha3, wasmtime)
├── CloudflareBypasser.py        # Omijanie Cloudflare Turnstile (DrissionPage)
├── login.py / login_slot.bat    # Logowanie kont
├── debounce.py                  # Deduplikacja wyników narzędzi
├── conversation_tracker.py      # Podsumowania rozmów / ostrzeżenia rotacji
├── subagent_isolation.py        # Statystyki subagentów
├── monitor.py                   # Monitor sesji (active/slow/dead + auto-restart)
├── mcp_server.py                # Serwer MCP (FastMCP) wystawiający DeepSeek jako narzędzia
├── requirements.txt             # curl_cffi, fastapi, uvicorn, pydantic, wasmtime, DrissionPage
├── pytest.ini / tests/          # 27 oficjalnych testów pytest
├── session_0..5.json            # Pula 6 kont DeepSeek Web
├── conv_state.json              # Stan rozmów (atomic)
├── start.bat / zmien_tryb.bat
├── gemini_proxy/                # DRUGI niezależny moduł: proxy Gemini Web UI
│   ├── server.py                # FastAPI, port 8045 (OpenAI-compatible)
│   ├── run.py / login.py
│   ├── gemini_browser.py        # Automatyzacja Playwright (Gemini Web UI)
│   ├── tool_parser.py           # Parser XML↔JSON tool-calli
│   ├── deep_research.py / run_deep_research.py
│   ├── models.py / config.py
│   └── tests/
├── WIEDZA/                      # 9 dokumentów inżynierskich (architektura, historia, dowody)
├── bugi/                        # Rejestr awarii (BUG-001, BUG-002)
├── DOKUMENTACJA_BUGOW_I_POSTMORTEM.md  # Katalog 32 bugów + reverse engineering
├── data/                        # logi, crash dumpy, snapshoty monitora, zrzuty strumieni
├── scratch/                     # ~50+ skryptów eksperymentalnych (fuzzery, benchmarki)
├── wasm/                        # Moduł WASM PoW
├── .chrome_slot/ i $R98O02X.chrome_slot/  # Profile Chrome (osobne sloty)
├── .agents/skills/deepseek-verify/SKILL.md
└── proxy_pakiet/                # Kopia dokumentacji + zmien_tryb.bat
```

**Brak głównego README.md** — istnieje tylko `Hello.md`, `README_TRAE_GEMINI.md` (ściągawka) i `WIEDZA/README.md` (spis treści). Brak `package.json` — to projekt czysto Python.

---

### 2. Cel projektu

**Główny cel:** Transparentny most (proxy) umożliwiający użycie **darmowego backendu webowego DeepSeek** (`chat.deepseek.com`) zamiast płatnych API w środowisku **Trae IDE**, które wymaga ścisłego protokołu OpenAI (`/v1/chat/completions` z JSON tool_calls i SSE `finish_reason: "tool_calls"`).

Fundamentalny problem (first principles): Trae wymaga natywnych JSON tool-calli w strumieniu SSE, a DeepSeek Web zwraca czysty tekst z tagami DSML/XML w czacie. Proxy tłumaczy oba światy.

**Drugi moduł (`gemini_proxy/`):** analogiczny most do **Gemini Web UI** (gemini.google.com/app) — z obsługą wizji, uploadu plików, przełączania modeli i autonomicznego Deep Research. Może służyć jako „oracle" dla Trae/DeepSeek (np. do analizy screenshotów).

**Trzeci komponent (`mcp_server.py`):** wystawia DeepSeek (przez lokalne proxy 4570) jako narzędzia MCP: `deepseek_autonomous_worker`, `deepseek_critical_verify`, `deepseek_deep_reasoning` — dla Gemini/Claude/Cursor/Antigravity.

---

### 3. Technologie

| Warstwa | Technologia |
|---|---|
| Serwer HTTP | FastAPI + uvicorn |
| Połączenia z DeepSeek Web | `curl_cffi` (impersonacja Chrome, ominięcie JA3) |
| Proof-of-Work | `wasmtime` + moduł WASM (sha3) |
| Omijanie Cloudflare | `DrissionPage` (automatyzacja Chromium) |
| Gemini Web UI | `playwright` (persistent context, anti-detection) |
| Schemy API | `pydantic` v2 |
| Oficjalne API DeepSeek | `requests` |
| MCP | `FastMCP` |
| Testy | `pytest` |
| Środowisko | Windows 10/11 x64, Python 3.13 |

---

### 4. Co działa, a co jest niekompletne

**Działa (wg dokumentacji i testów):**
- Pełny pipeline DeepSeek Web: sesje, PoW, streaming SSE, parsowanie 9 formatów tool-calli, auto-continue, heartbeat SSE (co 15 s), watchdog (180 s), chunked ingestion (>50k znaków), crash dump
- Oficjalne API DeepSeek dla głównego agenta (`deepseek-chat`, natywne JSON tool_calls)
- Hybrid routing (tryby: `auto`, `web`, `free`, `biedny`, `free_first`, `--clean`)
- Monitor sesji `active/slow/dead` z auto-restartem (snapshot do JSON co 5 s)
- Serwer MCP z auto-startem proxy w tle
- Gemini proxy z testami (routes, tool_parser, models) i automatyzacją Deep Research
- ~27 testów pytest + kilkadziesiąt skryptów w `scratch/`

**Niekompletne / problematyczne:**
1. **BUG-001 i BUG-002** w rejestrze `bugi/` mają status „Zdiagnozowany / Gotowy plan naprawy” — nie jest potwierdzone wdrożenie poprawek. BUG-001: pętla zagłady (4× redundant `Read macro_engine.py`, 17× puste wyszukiwania, **debounce całkowicie wyłączony** w kodzie produkcyjnym — zakomentowany jako `# DISABLED: debounce dedup has a bug`). BUG-002: zatrucie sesji, halucynacja tagów XML, 10× `git status`, cicha rotacja tworząca drugi czat DeepSeek.
2. **Chaos w `scratch/`** — dziesiątki jednorazowych skryptów eksploracyjnych i fuzzerów, brak porządku.
3. **Brak głównego README** — dokumentacja rozproszona (WIEDZA, bugi, DOKUMENTACJA_BUGOW, README_TRAE_GEMINI, TRANSKRYPCJA_SESJI).
4. **Niespójności liczbowe w dokumentacji** — np. limit DeepSeek Web podawany jako „~163 000 znaków” i „163 840” w różnych miejscach. Niezależny audyt (`AUDYT_NIEZALEZNY_2026-08-16.md`) kwestionuje retorykę „100% deterministyczny” i brak walidacji formatu DSML na żywo.
5. **Historyczne cykle awarii** — dokumentacja opisuje 32 bugi + sekcje zwłok poprzednich napraw przez modele AI (UnboundLocalError, martwy loop guard, zgubione tokeny, wyciek fazy THINK), co sugeruje iteracyjną, często awaryjną ewolucję.

---

### 5. Główne komponenty/moduły

1. **`server.py`** — serce systemu (port 4570, ~4000 linii):
   - `AccountPool` — pula do 100 slotów sesji, migracja starych sesji
   - `_stream()` / `_begin_phase()` / `_route_token()` — maszyna stanów strumienia z osobnymi buforami `content_buffer` (RESPONSE) i `thinking_buffer` (THINK, tłumione)
   - `generate()` — główna pętla z parsowaniem narzędzi, detekcją tagów, yieldowaniem chunków SSE
   - Auto-continue (KONTYNUUJ z `parent_message_id`), loop guard `_detect_loop()`, heartbeat, watchdog, chunked ingestion, crash dump
   - Wstrzykiwanie schematów Trae jako prompt; watermark sesji (usunięty z outputu)

2. **`official_api.py`** — klient `api.deepseek.com/v1/chat/completions`, natywne JSON tool_calls, bez limitu tur (używany dla main agenta w trybie `auto`).

3. **`pow.py`** — solver PoW DeepSeek przez WASM (`wasm_solve`), współdzielony moduł globalny.

4. **`CloudflareBypasser.py`** — omijanie Cloudflare Turnstile (shadow root + iframe, DrissionPage).

5. **`debounce.py` + `conversation_tracker.py` + `subagent_isolation.py`** — dedup narzędzi, podsumowania rozmów, statystyki subagentów.

6. **`monitor.py`** — monitor sesji z rozróżnieniem timeout vs martwy; snapshot JSON; auto-kill + restart po 60 s bez tokenu.

7. **`mcp_server.py`** — FastMCP serwer z 3 narzędziami; auto-uruchamia `server.py --clean` w tle (DETACHED_PROCESS) i czeka na port 4570.

8. **`gemini_proxy/`** — samodzielny moduł Gemini:
   - `server.py` — FastAPI/OpenAI-compatible (port 8045), streaming, tool calling, vision
   - `gemini_browser.py` — Playwright persistent context, stealth, czyszczenie locków profilu, MutationObserver do streamingu
   - `tool_parser.py` — wstrzykiwanie schematów XML i parser XML↔JSON
   - `deep_research.py` / `run_deep_research.py` — autonomiczny cykl Deep Research (aktywacja, plan, polling, eksport markdown)

9. **Testy:** `tests/` (27 oficjalnych) + `scratch/` (eksperymenty, fuzzery, benchmarki Monte Carlo, stress testy na żywym backendzie).

---

### Najważniejsze wnioski

- Projekt jest **dwuczęściowym systemem proxy**: (1) DeepSeek Web ↔ Trae IDE oraz (2) Gemini Web UI ↔ klienci OpenAI-compatible, plus serwer MCP spinający je jako „oracle".
- Rdzeń techniczny to **maszyna stanów strumienia SSE** w `server.py`, która rozwiązuje fundamentalną niezgodność: JSON tool_calls (Trae) vs tekstowe tagi DSML/XML (DeepSeek Web). Kluczowe linie definiują separację faz:
  ```python
  content_buffer = ""   # wyłącznie faza RESPONSE — to, co idzie do Trae
  thinking_buffer = ""  # wyłącznie faza THINK — reasoning, NIE idzie do Trae
  ```
- Projekt ma **bogatą, ale rozproszoną dokumentację inżynierską** (32 bugi w `DOKUMENTACJA_BUGOW_I_POSTMORTEM.md`, 9 plików w `WIEDZA/`, 2 nowe bugi w `bugi/`), opisującą reverse engineering protokołu (PoW, SSE, nagłówki, formaty tagów).
- **Niezamknięte problemy:** BUG-001 (wyłączony debounce, pętle) i BUG-002 (zatrucie sesji, rotacja) są zdiagnozowane, ale ich status naprawy nie jest jednoznacznie potwierdzony. Projekt deklaruje „100% deterministyczną stabilność”, ale niezależny audyt kwestionuje część tych twierdzeń.
- Architektura jest **iteracyjna i eksperymentalna** — duża ilość kodu w `scratch/`, historia wielokrotnych awarii i napraw, co sugeruje projekt bardziej badawczy niż produkcyjnie zamrożony.

Rozumiem. Oba projekty przejrzałem. Krótko:

**Cortex (ai_supervisor)** – to appka na notatki (Electron + React). Ai_supervisor to na razie tylko **prototyp HTML** + plan i schema JSON. Zero prawdziwego kodu. Wszystkie przyciski to atrapy (nic nie robią). To ten "początkowy design" od Gemini.

**deepseek-proxy-clean** – to osobna, działająca maszyna (proxy do DeepSeek/Gemini za darmo). Dużo kodu, ale bałagan i kilka niezamkniętych bugów.

---

Teraz kluczowe pytanie, żebym dobrze zaplanował dalej.


  [{"question": "Co ma robić ai_supervisor? (czym konkretnie jest ten 'supervisor')", "header": "Cel supervisor", "options": ["Nadzorować kilka łańcuchów AI naraz (jak w prototypie HTML)", "Nadzorować JEDEN proces AI krok po kroku", "Coś innego – opiszę po swojemu"], "multiSelect": false}, {"question": "Od czego chcesz zacząć planowanie?", "header": "Punkt startu", "options": ["Spisać prosty plan krok po kroku (bez kodu)", "Zacząć robić działający szkielet w aplikacji", "Najpierw uporządkować to, co zrobił Gemini"], "multiSelect": false}, {"question": "Czy ai_supervisor ma łączyć się z AI (Gemini/DeepSeek)?", "header": "Podłączenie AI", "options": ["Tak, ma realnie używać modeli AI", "Na razie nie – tylko interfejs i struktura", "Nie wiem / doradź mi"], "multiSelect": false}]

  [{"question": "Co ma robić ai_supervisor? (czym konkretnie jest ten 'supervisor')", "header": "Cel supervisor", "options": ["Nadzorować kilka łańcuchów AI naraz (jak w prototypie HTML)", "Nadzorować JEDEN proces AI krok po kroku", "Coś innego – opiszę po swojemu"], "multiSelect": false}, {"question": "Od czego chcesz zacząć planowanie?", "header": "Punkt startu", "options": ["Spisać prosty plan krok po kroku (bez kodu)", "Zacząć robić działający szkielet w aplikacji", "Najpierw uporządkować to, co zrobił Gemini"], "multiSelect": false}, {"question": "Czy ai_supervisor ma łączyć się z AI (Gemini/DeepSeek)?", "header": "Podłączenie AI", "options": ["Tak, ma realnie używać modeli AI", "Na razie nie – tylko interfejs i struktura", "Nie wiem / doradź mi"], "multiSelect": false}]
Dobra, nie pytam już – zakładam najprościej i proponuję plan. Możesz go poprawić.

**Moje założenia:**
- Supervisor = nadzoruje **kilka łańcuchów AI naraz** (jak w prototypie od Gemini)
- Na razie **bez podpinania prawdziwego AI** – najpierw sam interfejs + struktura
- Zaczynamy od **prostego planu**, potem krok po kroku

---

## Plan (krótko)

**Krok 1 – Uporządkować to, co jest.**
Prototyp Gemini (showcase.html) zostaje jako wzór wyglądu. Nic nie kasujemy.

**Krok 2 – Zrobić "kości" w aplikacji.**
Dodać do Cortex prosty widok supervisor, który na starcie pokazuje listę łańcuchów + oś kroków. Jeszcze bez prawdziwego AI – dane przykładowe zapisane lokalnie.

**Krok 3 – Zrobić, żeby kroki działały.**
Przyciski: zatwierdź krok, cofnij, wstrzymaj łańcuch, przełącz tryb auto/ręczny. Statusy: zrobione, w toku, czeka na człowieka, błąd.

**Krok 4 – Dopiero potem podłączyć AI.**
Jak interfejs będzie działał, podłączymy Gemini/DeepSeek (masz już proxy, które to umie).

---

Co zmienić? Mogę od razu zacząć od Kroku 1 (przejrzeć dokładnie prototyp, żeby nic nie zgubić), albo inny krok. Jak wolisz.Zaczynam Krok 1 – dokładnie przejrzę prototyp, plan i schema, żeby nic nie zgubić.


  








## 1. `showcase.html` — interaktywny prototyp UI

### Sekcje UI

**Header (górny pasek):**
- Blok brand: kropka akcentowa + napis "CORTEX"
- Selektory łańcucha: `<select id="pipelineSelect">` z 3 opcjami:
  - `oferty_b2b` → "1. Generator Ofert B2B"
  - `weryfikator_umow` → "2. Weryfikator Umów Prawnych"
  - `analiza_faktur` → "3. Automatyczna Analiza Faktur"
- Przełącznik trybu: `mode-switch-box` z dwoma przyciskami:
  - `btnModeManual` "Ręczny (Bramki)" — aktywny domyślnie
  - `btnModeAuto` "Automatyczny (Auto-Approve)"

**Main (dwie kolumny, grid 380px + 1fr):**

*Lewa kolumna — `timeline-pane`:*
- Nagłówek "Oś Kroków Procesu" + licznik `stepsCountLabel` (np. "12 kroków")
- Kontener `stepsContainer` renderowany dynamicznie; karty kroków (`.step-card`) z klasami: `active`, `gate` (dla kroków z `isGate: true` i trybem ręcznym), opacity 0.5 dla statusu `queue`. Każda karta zawiera nagłówek "Krok N: nazwa" + tag statusu + snippet.

*Prawa kolumna — `inspector-pane`:*
- `inspector-top-bar`: tytuł "Krok N: nazwa" (`inspectorHeaderTitle`) + `inspectorStepStatus` (kolor akcent przy `wait`, zielony przy innych)
- Zakładki (`inspector-tabs-nav`): 3 przyciski `tab-item-btn`:
  1. "1. Prompty Wejściowe" → `tab-prompts`
  2. "2. Pliki i Źródła" → `tab-files` (id przycisku `tabFilesBtn`, etykieta dynamiczna "2. Pliki (Brak)" lub "2. Pliki (N)")
  3. "3. Myśli & Rozmowa" → `tab-convo`
- Footer akcji (`inspector-footer`): `inspectorFooterHint` ("Wybrany krok: Krok N") + 3 przyciski w `footerActionsContainer`.

### Dane zaszyte w JS — `pipelinesDatabase`

Struktura obiektu:
```js
{
  [klucz_lancucha]: {
    name: string,
    steps: [
      {
        id: number,
        name: string,
        status: "done" | "wait" | "queue",
        statusTxt: string,       // np. "✓ Wykonano", "Czeka na Ciebie", "W Kolejce"
        snippet: string,
        isGate?: boolean,        // obecny gdy status="wait" i wymaga akceptacji
        hasFiles?: boolean,
        files?: [ { name: string, content: string } ]
      }
    ]
  }
}
```

Łańcuchy zaszyte:

**`oferty_b2b` (Generator Ofert B2B) — 8 kroków:**
1. Inicjalizacja i Odczyt Zlecenia — done, pliki: `zapytanie_ofertowe.txt`
2. Przeszukanie Bazy Wiedzy — done, brak plików
3. Kalkulacja Kosztów — done, brak plików
4. Generowanie Szkicu Oferty — done, pliki: `szkic_oferty.md`
5. Weryfikacja Marży i Decyzja — wait, `isGate: true`, snippet "Rabat 18.5% wymaga zatwierdzenia"
6. Formatowanie Dokumentu — queue
7. Eksport do PDF — queue, pliki: `oferta_finalna.pdf`
8. Wysyłka do Klienta — queue

**`weryfikator_umow` (Weryfikator Umów Prawnych) — 4 kroki:**
1. Wczytanie Umowy PDF — done, pliki: `umowa_nda.pdf`
2. Skanowanie Klauzul Ryzykownych — done
3. Zatwierdzenie Rekomendacji Prawnych — wait, `isGate: true`
4. Zapis Zmian do Pliku DOCX — queue, pliki: `umowa_poprawiona.docx`

**`analiza_faktur` (Automatyczna Analiza Faktur) — 4 kroki:**
1. Pobranie Faktur ze Skrzynki — done, pliki: `faktura_01.pdf`, `faktura_02.pdf`
2. OCR i Ekstrakcja NIP / Kwot — done
3. Weryfikacja na Białej Liście VAT — done
4. Zapis do Systemu Księgowego — wait, `isGate: true`

### Statusy kroków (w JS)
- `done` — tag `tag-done` (zielony), tekst "✓ Wykonano"
- `wait` — tag `tag-wait` (akcent), tekst "Czeka na Ciebie"; w trybie auto staje się `tag-done` z tekstem "✓ Auto-Zgoda"
- `queue` — tag `tag-queue` (szary), tekst "W Kolejce", karta z opacity 0.5

### Przyciski i akcje

| Przycisk / element | Akcja |
|---|---|
| `pipelineSelect` onchange `switchPipeline()` | Przełącza łańcuch; ustawia `currentStepId` na pierwszy krok `wait` (lub 1); aktualizuje licznik kroków; renderuje |
| `btnModeManual` / `btnModeAuto` → `setApprovalMode()` | Przełącza `isAutoApprove` (false/true); zmienia klasy aktywnych przycisków; renderuje ponownie |
| Karta kroku (`.step-card`) onclick `selectStep()` | Wybiera krok, aktualizuje inspektor, renderuje pliki |
| "Zapisz edycję promptu" | toast "Zapisano zmodyfikowany prompt..." |
| "Przetestuj krok ponownie" | toast "Uruchomiono ten krok ponownie!" |
| Przycisk pliku (`.file-item-btn`) | Podświetla aktywny plik, wypełnia `filePreviewArea` treścią |
| `btn-cortex-danger` "Przerwij cały proces" | toast "Zatrzymano proces..." |
| `btn-cortex-secondary` "Cofnij krok wstecz" | toast "Cofnięto wykonanie..." |
| `btn-cortex-primary` `btnApproveAction` → `approveCurrentStep()` | Jeśli wybrany krok ma `status === 'wait'`: zmienia na `done`, nadaje `statusTxt = '✓ Wykonano'`, następny krok przechodzi na `wait` + "Czeka na Ciebie", wybiera następny krok. Inaczej toast "został już wykonany" |
| `switchInspectorTab(tabId, btn)` | Przełącza aktywne zakładki |

### Oś kroków (timeline) — renderowanie
Funkcja `renderSteps()` tworzy w `stepsContainer` karty. Logika klas:
- `step-card active` gdy `step.id === currentStepId`
- `step-card gate` gdy `step.isGate && !isAutoApprove`
- `opacity: 0.5` gdy `status === 'queue'`
- Tag statusu: `tag-done` / `tag-wait` / `tag-queue`; dla `wait` w trybie auto → `tag-done` + "✓ Auto-Zgoda"; dla `wait` w trybie ręcznym → `tag-wait` + "Czeka na Ciebie"

### Zakładki inspektora

**Zakładka 1 — "1. Prompty Wejściowe" (`tab-prompts`):**
- `field-title` "System Prompt — Instrukcja dla modelu" + badge "SYSTEM"
- `slotSystemPrompt` (contenteditable) — wypełniany dynamicznie: `[SYSTEM_PROMPT DLA KROKU N]\nJesteś modułem...`
- `field-title` "User Message" + badge "USER INPUT"
- `slotUserPrompt` (contenteditable) — `[USER_PROMPT DLA KROKU N]`
- Przyciski: "Zapisz edycję promptu" i "Przetestuj krok ponownie"

**Zakładka 2 — "2. Pliki i Źródła" (`tab-files`):**
- Gdy pliki istnieją: `filesGrid` (grid 240px + 1fr) z listą przycisków plików (`filesButtonsList`) i panelem podglądu `filePreviewArea` + nazwa `previewFileName` + badge "UTF-8"
- Gdy brak plików: `emptyFilesBox` z tekstem "Brak plików w tym kroku"

**Zakładka 3 — "3. Myśli & Rozmowa" (`tab-convo`):**
- `field-title` "Co Model Pomyślał" + badge "THOUGHTS"
- `slotThoughts` — treść `<thought>...`
- `field-title` "Odpowiedź Wygenerowana przez Model" + badge "ODPOWIEDŹ MODELU"
- `slotConvo` — odpowiedź modelu

### Tryb auto/ręczny
- `isAutoApprove` (boolean, domyślnie `false`)
- `setApprovalMode('auto')` → `isAutoApprove = true`; karty `gate` tracą klasę `gate`; statusy `wait` renderują się jako `tag-done` "✓ Auto-Zgoda"; nagłówek statusu pokazuje "AUTO-ZATWIERDZONO"
- `setApprovalMode('manual')` → odwrotnie: gate wraca, statusy `wait` jako "Czeka na Ciebie"

---

## 2. `PLAN_WDROZENIA.md` — streszczenie

**Cel:** Uniwersalny moduł nadzoru nad wieloma łańcuchami AI w Cortex.

**Architektura Multi-Pipeline:**
- Dowolna liczba niezależnych łańcuchów AI (Generator Ofert, Weryfikator Umów, Analiza Faktur, Scraper Leadów...)
- Nagłówek: selektor łańcucha + przełącznik trybu akceptacji
- Układ dwupanelowy: lewa — oś kroków dla wybranego łańcucha; prawa — inspektor wybranego kroku

**Dodawanie nowego łańcucha przez AI:**
1. AI zapisuje plik `data/pipelines/nazwa_lancucha.json`
2. Cortex automatycznie wykrywa pliki w tym katalogu i dodaje do listy rozwijanej

**Kluczowe właściwości:**
1. Czysty UI — tylko 3 zakładki robocze: Prompty, Pliki, Myśli & Rozmowa (bez schematów technicznych)
2. Obsługa kroków bez plików (`"pliki": []` → stan informacyjny)
3. Przełącznik trybu: Ręczny (Bramki) — zatrzymuje na `wymaga_akceptacji: true`; Automatyczny (Auto-Approve) — wykonuje wszystko bez czekania
4. Skalowalność: 1 do 20+ kroków

**Pliki folderu `ai_supervisor/`:**
- `showcase.html` — interaktywny prototyp
- `schema.json` — schemat dla AI (struktura danych łańcucha i kroku)

**Integracja z Cortex:** Selektor w nagłówku aplikacji; auto-wykrywanie katalogu `data/pipelines/`.

---

## 3. `schema.json` — pola i typy

**Tytuł:** `CortexAIPipelineEvent` — standardowy format wymiany danych między łańcuchem AI a modułem nadzoru Cortex.

**Typ główny:** `object`
**Pola wymagane:** `krok_numer`, `krok_nazwa`, `status`

**Pola:**

| Pole | Typ | Opis | Ograniczenia |
|---|---|---|---|
| `krok_numer` | integer | Kolejny numer kroku | min 1, max 50 |
| `krok_nazwa` | string | Nazwa etapu | wymagane |
| `status` | string (enum) | Stan wykonania | `"WYKONANO"`, `"W_TOKU"`, `"CZEKA_NA_CZLOWIEKA"`, `"W_KOLEJCE"`, `"BLAD"` |
| `opis_kroku` | string | Jednozdaniowe podsumowanie | opcjonalne |
| `prompty` | object | Dane promptów | opcjonalne |
| `prompty.system` | string | Instrukcja systemowa | opcjonalne |
| `prompty.user` | string | Polecenie użytkownika / wejście | opcjonalne |
| `pliki` | array | Lista plików (może być pusta) | opcjonalne, items: object |
| `pliki[].nazwa` | string | Nazwa z rozszerzeniem | wymagane |
| `pliki[].typ` | string | Typ (np. `wejście`, `wyjście`, `baza_wiedzy`) | opcjonalne |
| `pliki[].tresc` | string | Pełna zawartość tekstowa | wymagane |
| `mysli_modelu` | string | Wewnętrzny strumień myślenia modelu | opcjonalne |
| `odpowiedz_modelu` | string | Odpowiedź modelu / pytanie do użytkownika | opcjonalne |
| `wymaga_akceptacji` | boolean | Czy krok wymaga kliknięcia zatwierdzenia | default `false` |

**Statusy (enum):** `WYKONANO`, `W_TOKU`, `CZEKA_NA_CZLOWIEKA`, `W_KOLEJCE`, `BLAD`

---

## Podsumowanie konwersji do React/TypeScript

**Kluczowe typy TS do utworzenia:**
- `PipelineEvent` (zgodny ze `schema.json`): `krok_numer`, `krok_nazwa`, `status`, `opis_kroku`, `prompty { system, user }`, `pliki { nazwa, typ, tresc }[]`, `mysli_modelu`, `odpowiedz_modelu`, `wymaga_akceptacji`
- `PipelineDefinition`: `name: string`, `steps: PipelineEvent[]`
- `PipelinesDatabase`: `Record<string, PipelineDefinition>`

**Statusy UI (z showcase):** `done`, `wait`, `queue` (mapują się na: `WYKONANO`, `CZEKA_NA_CZLOWIEKA`, `W_KOLEJCE`; brak `W_TOKU` i `BLAD` w prototypie, ale są w schemacie).

**Kluczowe komponenty:** Header (selektor + przełącznik trybu), TimelinePane (lista kroków), InspectorPane (top bar + 3 zakładki + footer z 3 przyciskami akcji), Toast.

---

