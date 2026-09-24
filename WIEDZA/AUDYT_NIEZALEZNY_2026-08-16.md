# Audyt Niezależny — Weryfikacja Pracy Gemini (2026-08-16)

> **Autor audytu:** asystent (niezależna weryfikacja po przerwie w pracy).
> **Powód:** Gemini wykonał dużą partię zmian w `server.py` i dokumentacji `WIEDZA/`. Niniejszy plik rejestruje, co **faktycznie** sprawdzono (uruchamiając testy i czytając kod), a nie tylko uznano za prawdę na podstawie dokumentacji.
> **Zasada:** żadna liczba z tego pliku nie pochodzi z deklaracji Gemini — każda została odtworzona niezależnie.

---

## 1. Metoda weryfikacji

Nie poprzestano na czytaniu plików `.md`. Wykonano:

1. Odczyty `server.py` w konkretnych zakresach linii (kod, a nie opis kodu).
2. Uruchomienie **4 deterministycznych testów** w `scratch/` (bez sieci).
3. Uruchomienie **pełnego stress testu** `scratch/stress_test_deep_engineering.py`.
4. Porównanie odtworzonych liczb z tabelami w `STRESS_TESTY_I_TELEMETRIA.md`.

---

## 2. Potwierdzone zmiany w kodzie (z numerami linii)

| Lokalizacja | Symbol | Co potwierdzono |
|---|---|---|
| [server.py:212](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L212) | `_detect_loop` | Przepisany strażnik pętli: `min_len=500`, `window=1500`, fragmenty `(100, 150, 200)`, próg `>= 4` powtórzeń. Zamiast łapania krótkich 15–50-znakowych fragmentów w oknie 300 znaków. |
| [server.py:270](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L270) | `_has_unclosed_tool_call` | Rozszerzony o znaki `｜` (U+FF5C), `│` (U+2502), markery DSML oraz kontener `tool_calls`. |
| [server.py:1185](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L1185) | `MAX_PROMPT_LEN` | Twardy budżet `35000` znaków. |
| [server.py:1187](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L1187) | `_compress_tool_results` | Domyślny `threshold=1500` znaków. Kompresja Read-like (3 pierwsze linie) i non-Read (500 pierwszych znaków). |
| [server.py:1341](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L1341) | `_crush_tool_results` | Osobna, agresywna kompresja dla odzyskiwania Web Chat (wszystko `> 200` znaków). Komentarz na linii 1343 **jest zgodny** z kodem (`threshold=1500 chars`). |
| [server.py:1389](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L1389) | `_build_prompt` | Kompresja historii (`rest[:keep_from]`, próg 1500) oraz bieżącej tury (tylko pojedyncze wyniki `> 25000` znaków, linia 1414). |
| [server.py:918](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L918) | `_write_crash_dump` | Zapis zrzutu awaryjnego. Wywołania: linie 3472, 3492, 3521. |
| [server.py:3519](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L3519) | tłumienie wycieku | `Suppressed unclosed tool call leakage` — blokada niedomkniętych tagów przed wysłaniem do Trae. |

---

## 3. Wyniki testów uruchomionych niezależnie

### 3.1 Testy deterministyczne w `scratch/` (wszystkie `PASSED`, exit code 0)

- `test_live_fullwidth_tool_call.py` — parser poprawnie obsługuje natywny format `<｜invoke name="...">` ze znakiem pełnej szerokości.
- `test_all_tool_call_formats.py` — 9 formatów narzędzi parsowanych poprawnie.
- `test_dsml_first_principles.py` — parsowanie DSML first-principles.
- `test_loop_guard_false_positive.py` — strażnik pętli **nie** reaguje na legalne tagi DSML.

### 3.2 Stress test — odtworzenie liczb z dokumentacji

Uruchomiono `scratch/stress_test_deep_engineering.py`. Wynik: **WSZYSTKIE 4 FAZY `PASSED` w 0.08 s**.

Odtworzone liczby z Fazy 2 (monolit `TOOL`), porównanie z `STRESS_TESTY_I_TELEMETRIA.md`:

| Surowy rozmiar | Wynikowy prompt (odtworzony) | Dokumentacja | Zgodność |
|---:|---:|---:|:---:|
| 50 000 | 3 336 | 3 336 | ✅ |
| 100 000 | 3 338 | 3 338 | ✅ |
| 250 000 | 3 339 | 3 339 | ✅ |

Faza 1 (10-turowa sesja): końcowy prompt **27 079 znaków** ≤ 35 000 — zgodne z dokumentacją (27 079).

---

## 4. Punkt, który wzbudził wątpliwość — i jak się rozstrzygnął

Wstępna hipoteza audytora: „komentarz w kodzie mówi `>500k`, a dokumentacja `threshold=1500` — możliwa niespójność".

**Rozstrzygnięcie po weryfikacji:** hipoteza **błędna**.

- Aktualny komentarz [server.py:1343](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L1343) brzmi: `"Unlike _compress_tool_results (which only compresses above threshold=1500 chars)..."` — **zgodny** z kodem.
- Mechanizm kompresji działa dokładnie tak, jak opisuje dokumentacja: historia `> 1500` znaków kompresowana, bieżąca tura `> 25 000` kompresowana, reszta nietknięta (widać to w tabeli: `25k → 24 428` nietknięty, `50k → 3 336` skompresowany).

---

## 5. Pozostałe zastrzeżenia (uczciwe, po weryfikacji)

1. **Retoryka „100% deterministyczny / niezniszczalny" jest nadużyciem.** Cały pierwotny problem polega na tym, że DeepSeek **zmienia format DSML** (natywnie trenowany). Deklaracja „niezniszczalny" to pułapka — przy kolejnej zmianie formatu parser znów może nie nadążyć. Poprawniej: „działa na wszystkie *znane* formaty".
2. **„Fizyczny limit 163 840 znaków" to podejrzanie czysta liczba** (= 160 × 1024). Dane binary search w `DOWODY_EMPIRYCZNE_I_BENCHMARKI.md` pokazują granicę *gdzieś między 162k a 164k*, a nie dokładnie 163 840. Może być prawdziwe, ale nie wynika wprost z przytoczonych pomiarów.
3. **Stress test jest offline.** Sprawdza poprawność *budowania promptu* (że ≤ 35 000 znaków), a **nie** to, czy DeepSeek faktycznie dobrze odpowiada w prawdziwej, wieloturowej rozmowie na żywo. To kluczowa luka — deterministyczne testy nie pokrywają niestabilności formatu DSML w rzeczywistym strumieniu.

---

## 6. Werdykt

Praca Gemini jest **rzetelna technicznie**: zmiany w kodzie są realne, testy przechodzą, a udokumentowane liczby dają się niezależnie odtworzyć. Jedyne istotne zastrzeżenia mają charakter retoryczny (przesadna pewność) oraz zakresowy (brak walidacji „na żywo" niestabilnego formatu DSML), a nie merytoryczny.
