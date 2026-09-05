# BUG-025: Fałszywy Alarm Strażnika Pętli (`_detect_loop`) na Liniach Dekoracyjnych Komentarzy (`// =======`) i Zerwanie Zpisu Pliku `Write`

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** Zdiagnozowany / Wymaga Poprawki w `server.py`  
**Dotknięte komponenty:** `server.py` (`_detect_loop`, streaming narzędzia `Write`)  
**Plik zrzutu awaryjnego:** [`data/crashed_chats/crash_20260905_111650_jwt_leg_caoy_8af6b1f5.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/data/crashed_chats/crash_20260905_111650_jwt_leg_caoy_8af6b1f5.md)  
**Dowód wizualny:** [`media_1788599836199.png`](file:///C:/Users/Ksawier/.gemini/antigravity/brain/87701fc8-c77e-455c-831f-ebcd5eee55d0/.user_uploaded/media_1788599836199.png) (górny dymek)  

---

## 1. Objawy Awarii (Objawy Widoczne w GUI Trae)

Agent w Trae otrzymał zadanie migracji stanu czatu AI (`localStorage` → `StorageEngine`). W odpowiedzi zadeklarował:
> *"To duże zmiany. Wykonam je etapami z typecheckiem. Zaczynam od migracji localStorage → StorageEngine. Najpierw tworzę współdzielone typy czatu."*

Po 2 minutach i 18 sekundach pracy w dymku pojawił się czerwony alert:
> `[BŁĄD PROXY: Zapis pliku został ucięty przez limit tokenów. Plik NIE został zapisany na dysku. Ponów zapis.]`

Agent przerwał pracę, a plik `cortex-app/src/shared/types/aiChat.ts` nie został zapisany na dysku.

---

## 2. Dowody z Logów Proxy i Pliku Crash Dump

W logu [`proxy_output.log`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/proxy_output.log):
```text
[YIELD] safe lines: 'To duże zmiany. Wykonam je etapami z typecheckiem. Zaczynam od migracji localStorage → StorageEngine'
[LOOP GUARD] Detected exact repeating chunk (10 chars) -> aborting
[STREAM] Incomplete — returning partial content (625 chars). Next RESUME will continue.
[TIMING] DS stream done, resp_id=190 finished=False
[STREAM] Suppressed unclosed tool call leakage (0 chars not sent to chat)
[CRASH DUMP] Saved: data\crashed_chats\crash_20260905_111650_jwt_leg_caoy_8af6b1f5.md
```

W pliku zrzutu pamięci `crash_20260905_111650_jwt_leg_caoy_8af6b1f5.md`:
```typescript
To duże zmiany. Wykonam je etapami z typecheckiem. Zaczynam od migracji localStorage → StorageEngine. Najpierw tworzę współdzielone typy czatu.

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Write">
<｜｜DSML｜｜parameter name="file_path" string="true">c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/cortex-app/src/shared/types/aiChat.ts</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="content" string="true">// ============================================================================
// CORTEX — Typy czatu AI (współdzielone renderer <-> main)
// =========================================================================
```

Strumień został przerwany dokładnie w trakcie generowania drugiej linii separatora z powtórzonych znaków równości `=`.

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

W `server.py:L222-238` zaimplementowano funkcję wykrywania patologicznych zapętleń tekstu:
```python
def _detect_loop(content_buffer: str, min_len: int = 500, window: int = 1500) -> bool:
    if len(content_buffer) < min_len:
        return False
    tail = content_buffer[-window:]
    for chunk_size in range(10, 201):
        if len(tail) < chunk_size * 3:
            continue
        c1 = tail[-chunk_size:]
        c2 = tail[-2*chunk_size:-chunk_size]
        c3 = tail[-3*chunk_size:-2*chunk_size]
        if c1 == c2 == c3 and len(c1.strip()) > 3:
            print(f"[LOOP GUARD] Detected exact repeating chunk ({len(c1)} chars) -> aborting", flush=True)
            return True
    return False
```

### Mechanizm błędu:
1. Standardowy nagłówek pliku w TypeScript/JavaScript zawiera linie oddzielające, np. `// ============================================================================` (76 znaków `=`).
2. Pętla `chunk_size` rozpoczyna sprawdzanie od rozmiaru `chunk_size = 10`.
3. Dla ciągu `==============================`:
   - `c1 = "=========="`
   - `c2 = "=========="`
   - `c3 = "=========="`
4. Warunek `c1 == c2 == c3` jest w 100% spełniony, a `len(c1.strip()) == 10 > 3`.
5. Funkcja `_detect_loop` błędnie klasyfikuje zwykłą poziomą kreskę oddzielającą jako nieskończoną pętlę generowania tekstu i **bezwzględnie zabija strumień**.
6. Ponieważ strumień został przerwany w środku tagu `<invoke name="Write">`, narzędzie pozostało niedomknięte.
7. Bezpiecznik `e6b756c` poprawnie udaremnił zapisanie 3-linijkowego uszkodzonego pliku na dysku, ale wyemitował alert o ucięciu przez limit tokenów.

---

## 4. Wymagana Poprawka w Kodzie

W `_detect_loop` należy dodać filtr ignorujący powtórzenia znaków jednorodnych (linii dekoracyjnych):
```python
# Ignoruj linie dekoracyjne (np. =====, -----, *****, //////, ######)
if len(set(c1.strip())) <= 2:
    continue
```
Dzięki temu linie oddzielające nie będą powodowały fałszywych alarmów, podczas gdy rzeczywiste zapętlenia zdań lub funkcji będą nadal skutecznie wyłapywane.
