# Baza Wiedzy i Dokumentacja Inżynierska: DeepSeek Proxy Clean

> **Status repozytorium:** Produkcyjnie ustabilizowane, zwalidowane deterministycznymi testami symulacyjnymi i testami obciążeniowymi na żywym backendzie DeepSeek Web.
> **Przeznaczenie:** Repozytorium prawdy architektonicznej, dowodów empirycznych na poziomie bitów oraz protokołów inżynierii wstecznej dla inżynierów systemów rozproszonych i modeli AI.

---

## 📚 Spis Treści Bazy Wiedzy

| Plik Dokumentacji | Rola i Zawartość |
|---|---|
| [`HISTORIA_AWARII_I_DLACZEGO_JUZ_DZIALA.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/HISTORIA_AWARII_I_DLACZEGO_JUZ_DZIALA.md) | **Główna Historia Projektu i Pełny Post-Mortem:**<br>• Chronologiczna historia awarii, sekcja zwłok prób naprawy przez poprzednie modele AI.<br>• Dokładna analiza zrzutów `deeo.txt`, Request #448 i 32 bugów systemowych.<br>• Wyjaśnienie, dlaczego proxy działa teraz w 100% niezawodnie. |
| [`DOWODY_EMPIRYCZNE_I_BENCHMARKI.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/DOWODY_EMPIRYCZNE_I_BENCHMARKI.md) | **Twarde Dowody Empiryczne i Pomiary Żywego Backend:**<br>• Dowód awarii Request #448 (`deeo.txt`) i odcięcie loop guarda na 215. znaku.<br>• Wykrycie fizycznego sufitu DeepSeek Web (twardy drop przy 163k znaków / 40k tokenów).<br>• Badanie limitów sesji wieloturowych i sliding-window rate-limitingu.<br>• Dowody odporności na 90 ucięć bajtowych znaków UTF-8 (ą, ę, ś, ź, ł, ｜). |
| [`STRESS_TESTY_I_TELEMETRIA.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/STRESS_TESTY_I_TELEMETRIA.md) | **Inżynierska Telemetria i Wyniki Obciążeniowe:**<br>• 10-turowa narastająca sesja subagentów z 10 schematami narzędzi Trae (6.5k znaków schematów).<br>• Eskalacja monolitów User vs Tool (10k do 250k znaków).<br>• Fuzzing 50 losowych punktów ucięć w locie.<br>• 50 iteracji Monte Carlo (1.1 ms / iterację). |
| [`first_principles_analiza_i_architektura.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/first_principles_analiza_i_architektura.md) | **Architektura First Principles i Maszyna Stanów:**<br>• Rozwiązanie fundamentalnej niezgodności: Trae IDE (OpenAI Tool Calling) vs DeepSeek Web (Czat Tekstowy).<br>• Maszyna Stanów Strumienia (Stream State Machine) i separacja fazy myślenia (`THINK` vs `RESPONSE`).<br>• Matematyka dynamicznego budżetowania promptu (`MAX_PROMPT_LEN = 35000`). |
| [`protokol_deepseek_web.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/protokol_deepseek_web.md) | **Inżynieria Wsteczna Protokołu Web SSE:**<br>• Format ramek JSON SSE, mechanika Proof-of-Work (PoW) w WASM.<br>• Nagłówki przeglądarkowe (`x-client-version: 2.3.0`, `x-client-bundle-id`).<br>• Formaty tagów narzędziowych: DSML, XML oraz natywny format DeepSeek. |
| [`AUTOKRYTYKA_I_GRANICE_SYSTEMU.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/AUTOKRYTYKA_I_GRANICE_SYSTEMU.md) | **Red Teaming i Analiza Ograniczeń:**<br>• Bezkompromisowy audyt ryzyk darmowego backendu.<br>• Zachowanie Auto-Continue przy konwersacyjnych wstawkach modelu (`"Kontynuuję: ..."`).<br>• Architektura blokad wycieków w `generate()` fallback. |
| [`architektura_i_ustalenia.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/architektura_i_ustalenia.md) | **Historia Projektu i Ustalenia Operacyjne:**<br>• Stabilizacja `conv_key`, tryby pracy proxy (`auto`, `free`, `biedny`, `clean`), zarządzanie pulą 6 kont. |
| [`AUDYT_NIEZALEZNY_2026-08-16.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/WIEDZA/AUDYT_NIEZALEZNY_2026-08-16.md) | **Niezależny Audyt Weryfikacyjny (asystent, 2026-08-16):**<br>• Potwierdzenie zmian w kodzie z numerami linii (`_detect_loop`, `_has_unclosed_tool_call`, `MAX_PROMPT_LEN`, `_compress_tool_results`).<br>• Odtworzone wyniki stress testu (3 336 / 3 338 / 3 339 ch) niezależnie od deklaracji Gemini.<br>• Pozostałe zastrzeżenia: retoryka „100% deterministyczny", liczba 163 840, brak walidacji formatu DSML na żywo. |

---

## 🧪 Oficjalny Pakiet Testów Pytest (`tests/`)

W katalogu [`tests/`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests) znajduje się **27 profesjonalnych testów jednostkowych, integracyjnych i żywych `pytest`** z pełnym zestawem fixtures żądań IDE i odpowiedzi modelu:
- [`conftest.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/conftest.py): Fixtures zapytań IDE (10 schematów narzędzi Trae, ciężka historia >80k, monolity 100k, vision) oraz surowych wyjść DeepSeek Web (DSML `deeo.txt`, XML, JSON, native, reasoning CoT).
- [`test_openai_request_transformation.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/test_openai_request_transformation.py): Testy transformacji wejścia, budżetowania promptu i kompresji.
- [`test_model_response_translation.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/test_model_response_translation.py): Testy parsowania 9 formatów narzędzi, detekcji ucięć, loop-guarda i izolacji CoT.
- [`test_e2e_streaming_sse_chunks.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/test_e2e_streaming_sse_chunks.py): Testy sekwencji strumienia SSE chunk-by-chunk, `delta.tool_calls`, `finish_reason: "tool_calls"`.
- [`test_sse_spec_compliance.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/test_sse_spec_compliance.py): Ścisła zgodność z kontraktem OpenAI i obsługa znaków UTF-8.
- [`test_live_deepseek_web.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/tests/test_live_deepseek_web.py): Testy na żywo z prawdziwym klastrem DeepSeek Web (PoW, sesja, streaming i realne generowanie narzędzia `Read`).

Uruchomienie:
```bash
pytest -v tests/
```

---

## 🏛️ 5 Praw Determinizmu Proxy

1. **Kontrakt Trae IDE jest binarny:** Klient wymaga ramki SSE `delta.tool_calls` i `finish_reason: "tool_calls"`. Jakikolwiek surowy tag tekstowy lub status `"stop"` powoduje przerwanie tury asystenta i śmierć subagenta.
2. **DeepSeek Web nie zna pojęcia `tool_calls` na poziomie HTTP:** Zwraca czysty strumień znaków z tagami DSML/XML. Proxy jest jedyną warstwą odpowiedzialną za maszynę stanów, buforowanie i bezstratną translację.
3. **Zakaz niszczących mikro-heurystyk:** Strażnik pętli (`_detect_loop`) sprawdza wyłącznie potężne zapętlenia całych bloków tekstu ($\ge 100$ znaków, $\ge 4$ powtórzenia) i nigdy nie reaguje na legalne tagi strukturalne.
4. **Transparentne Auto-Continue:** Każde urwanie strumienia wewnątrz bloku narzędzia wyzwala natychmiastowe wysłanie `"KONTYNUUJ"` z `parent_message_id`, doklejając brakujące tokeny przed zakończeniem żądania.
5. **Sztywny budżet promptu ($\le 35 000$ znaków):** Dynamiczne odliczanie wagi schematów narzędzi Trae i agresywna kompresja historii narzędzi gwarantują ponad 4.5-krotny margines bezpieczeństwa względem fizycznego limitu DeepSeek Web (~163 000 znaków).
