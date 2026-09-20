# DOWÓD ZAAWANSOWANEGO TESTU POLOWEGO PROXY DEEPSEEK

- **Data przeprowadzenia:** 2026-09-19 21:35:47 CEST
- **Liczba wykonanych żądań:** 12 (10 w teście polowym + 2 w teście multi-turn agent flow)
- **Skuteczność:** 12/12 (100%)
- **Zduplikowane wywołania narzędzi:** 0 (dokładnie 1 wywołanie per żądanie)
- **Wycieki DSML:** 0
- **Spam "kontynuuj" / pętle:** 0
- **Bany / wyciszenia slotów:** 0
- **Aktywne sloty produkcyjne:** `['7', '11', '12', '13']` (wszystkie `IDLE`, `is_muted: False`)

---

## 1. Tarcza Rate Limit / Pacing Shield w akcji

W proxy działają 3 poziomy ochrony przed banem:
1. **Global IP Pacer**: minimum 2.0s - 2.8s losowego odstępu między dowolnymi żądaniami z tego IP.
2. **Per-Account Anti-Ban Shield**: **19.0s - 22.0s** bezwzględnego cooldownu na danym koncie DeepSeek (`base_pacing = 18.0 + uniform(1.0, 4.0)`). Jeśli klient (np. Trae) wyśle wynik narzędzia natychmiast (np. po 0.7s), proxy automatycznie wstrzymuje żądanie i loguje:
   ```text
   [PACING] Pacing 18.66s na slocie 12 (TARCZA ANTY-BAN SLOTU 12 (19-22s) [mnożnik 1.00x: klaster stabilny], od zakończenia poprzedniego zadania minęło 0.7s)...
   ```
3. **Rotacja LRU**: Nowe konwersacje automatycznie trafiają do slotu o najdłuższym czasie bezczynności (`idle_seconds`), dzięki czemu konta rotują i naturalnie odpoczywają.

---

## 2. Wyniki Testu Polowego (10 żądań SSE)

| # | Typ scenariusza | Czas (s) | TTFT (s) | Wywołania narzędzi | Finish Reason | Status |
|---|-----------------|----------|----------|-------------------|---------------|--------|
| 1 | tool_trigger | 1.82 | 1.26 | 1 (unikalne=1) | tool_calls | PASS |
| 2 | polish_future | 4.95 | 1.62 | 0 | stop | PASS |
| 3 | tool_trigger_read | 2.56 | 1.59 | 1 (unikalne=1) | tool_calls | PASS |
| 4 | code_qa | 3.17 | 1.65 | 0 | stop | PASS |
| 5 | polish_conversational | 3.34 | 1.27 | 0 | stop | PASS |
| 6 | tool_trigger | 2.26 | 1.20 | 1 (unikalne=1) | tool_calls | PASS |
| 7 | polish_future | 5.96 | 1.27 | 0 | stop | PASS |
| 8 | tool_trigger_read | 1.81 | 0.85 | 1 (unikalne=1) | tool_calls | PASS |
| 9 | code_qa | 2.95 | 0.84 | 0 | stop | PASS |
| 10 | polish_conversational | 5.82 | 0.96 | 0 | stop | PASS |

---

## 3. Wyniki Testu Multi-Turn Trae (Zwrot wyniku narzędzia)

- **Krok 1 (User -> Assistant):** Zapytanie o `LS` -> model wyemitował dokładnie 1 wywołanie narzędzia `LS(path='...')`.
- **Krok 2 (Trae -> Proxy -> DeepSeek):** Trae zwrócił listę plików (`README.md`, `main.py`, `requirements.txt`, `data/`).
  - Tarcza Anty-Ban odczekała wymagany cooldown: `18.66s`.
  - Model podsumował pliki w czystym tekście.
  - Obecność `[BLOCKED]`: **False**
  - Obecność spamu `"kontynuuj"`: **False**
  - Kod zakończenia: `stop`

---

## 4. Stan Slotów po Testach

```json
{
  "7":  { "status": "IDLE", "is_muted": false, "total_requests": 4 },
  "11": { "status": "IDLE", "is_muted": false, "total_requests": 3 },
  "12": { "status": "IDLE", "is_muted": false, "total_requests": 7 },
  "13": { "status": "IDLE", "is_muted": false, "total_requests": 3 }
}
```
**Podsumowanie testu natychmiastowego:** Wszystkie 4 sloty produkcyjne w momencie zakończenia testu były w 100% sprawne i nie dostały natychmiastowego bana.

---

## 5. AUDYT NOCNY: BAN PO CZASIE (Nocny Batch Sweep DeepSeek o 00:27)

> [!WARNING]
> **Kluczowa obserwacja:** DeepSeek nie nakłada blokad natychmiast w trakcie testu. Przeprowadza asynchroniczną analizę telemetryczną raz na dobę (ok. północy).

### Dowód z logów serwera i oficjalnego API:
- **Slot 12 (`p.awelkowalkp@gmail.com`):** Nałożono karę 72h dokładnie o **`2026-09-20 00:27:09 CEST`**.
- **Slot 11 (`pawelkowal.kp@gmail.com`):** Nałożono karę 72h dokładnie o **`2026-09-20 00:27:39 CEST`** (30 sekund później).

### Przyczyna:
Sam benchmark (12 żądań) był poprawny, ale **kumulacja z całego dnia**:
- **Slot 12:** łącznie **108 zapytań** (w tym potężna lawina 162 wywołań w 19s z sesji `magazyn` przed poprawkami)
- **Slot 11:** łącznie **93 zapytania** (w tym wcześniejsze intensywne testy)

Przekroczyły one dobowy próg tolerancji darmowych kont webowych DeepSeek (~80 zapytań/dobę).

### Dlaczego Slot 13 (`pawel.kowal.kp@gmail.com`) NIE DOSTAŁ BANA?
- **Zaledwie 7 zapytań** (łącznie 21.3 sekundy pracy) w całej swojej historii.
- Brak udziału w pętlach i lawinach zapytań (konto dodane już po naprawie parsera).
- Wolumen był zbyt mały, by algorytmy anty-fraudowe zaklasyfikowały je jako bota/proxy.

### Aktualny stan klastra po nocy:
- **Sloty 8 i 9** odblokowały się zgodnie z planem o **23:28** i **23:32** i natychmiast zastąpiły wyciszone sloty 11 i 12.
- Proxy działa stabilnie na **4 czystych slotach: [7, 8, 9, 13]**.
- Kolejne **4 konta [1, 0, 5, 6]** odblokują się dzisiaj po południu między **15:45 a 15:56**.
