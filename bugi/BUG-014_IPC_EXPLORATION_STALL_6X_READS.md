# BUG-014: Zastój Pomiędzy Fazą Eksploracji IPC a Implementacją (6 Plików Odczytanych przed Propozycją UI)

**Data rejestracji:** 2026-08-31 22:29  
**Komponenty:** Model Exploration Phase, Read Batching, `server.py` Session Pipeline  
**Wpływ na działanie:** ŚREDNI (Złudzenie zamrożenia agenta na `0%` po zakończeniu podwójnej tury odczytów architektury Electron IPC i widoku supervisora).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu i logów sesji)

### Incydent: Zatrzymanie na 0% po odczytaniu plików widoku
* **Sekwencja w Trae:**
  1. `Search Agent | Znajdź UI pipelinów w cortex-app`
  2. Tekst: *„Znalazłem architekturę: Electron IPC, bez child_process. Muszę dodać odpalanie Pythona z main process. Czytam kluczowe pliki przed edycją.”*
  3. `Read 4 files >`
  4. Tekst: *„Czytam widok supervisor i typy, żeby znaleźć miejsce na przycisk i pola pipeline.”*
  5. `Read 2 files > Read SupervisorView.tsx, Read types.ts` $\rightarrow$ **Chwilowy przestój i status 0%**.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Fragmentacja fazy eksploracji na mikro-zapytania
Zamiast przeczytać potrzebne pliki w jednej paczce, model podzielił badanie na 3 tury (Search Agent $\to$ Read 4 files $\to$ Read 2 files). Każda taka tura to osobne zapytanie HTTP do DeepSeeka, co powoduje wrażenie zacinania się interfejsu.
