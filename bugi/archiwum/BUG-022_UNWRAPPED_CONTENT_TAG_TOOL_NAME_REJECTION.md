# BUG-022: Emisja Surowego Tagu `<content>` zamiast `<parameter name="content">` i Odrzucenie przez Trae jako Nieistniejące Narzędzie (`Tool's name content is not available`)

**Data rejestracji:** 2026-09-02 18:22  
**Komponenty:** `server.py` (Tool Call Normalizer & Sanitizer, regexy XML `server.py:L1780-1890`), Trae Tool Execution Engine  
**Wpływ na działanie:** WYSOKI (Model przy wywołaniu narzędzia zapisu pliku `Write` zamiast poprawnej składni `<parameter name="content">` wyemitował surowy tag `<content>...</content>`. Klient Trae lub parser potraktował ten znacznik jako wywołanie narzędzia o nazwie `content`, rzucając błąd `Tool's name content is not available`, co zmusiło model do wycofania się i użycia `SearchReplace`).

---

## 1. DOWODY EMPIRYCZNE (Zrzut z surowego strumienia myślenia modelu)

Bezpośrednio z `data/raw_stream_capture.jsonl` (z sesji `96af12f7` z godziny 18:21:40):
> *„Miałem problemy z zapisem pliku z powodu błędu w tagach XML. Widzę, że popełniłem błąd — użyłem nieprawidłowych nazw tagów `content` zamiast `content` jako parametr. Ale system mówi: 'Tool's name content is not available'.*  
> *Problem polega na tym, że użyłem złej struktury. Prawidłowa struktura to:*  
> ```xml
> <tool_call name="Write">
>   <parameter name="file_path">...</parameter>
>   <parameter name="content">...</parameter>
> </tool_call>
> ```  
> *Ale wcześniej przypadkiem użyłem `<content>` zamiast `<parameter name="content">`. To spowodowało błędy.*  
> *Właściwie najprościej: użyjemy `SearchReplace` zamiast `Write`, albo po prostu poprawię poprawnie tagami...”*

---

## 2. PRZYCZYNA ŹRÓDŁOWE (Root Cause)

1. **Halucynacja formatu XML u DeepSeeka:**  
   Podczas długich sesji i po wielu wywołaniach narzędzi, DeepSeek gubi ścisłą strukturę `<parameter name="nazwa">` i zaczyna domykać parametry jako bezpośrednie znaczniki XML, np.:
   ```xml
   <tool_call name="Write">
     <parameter name="file_path">plik.py</parameter>
     <content>
       kod pliku...
     </content>
   </tool_call>
   ```
2. **Brak normalizacji w proxy:**  
   Proxy `server.py` w sekcji `_parse_tool_calls` wyszukuje parametry przez regex dopasowujący wyłącznie `<parameter name="...">`. Gdy napotyka surowy `<content>`, nie przekształca go w argument `content` narzędzia `Write`. Zamiast tego:
   * Albo wycina treść jako zwykły tekst, wysyłając do Trae `Write` z pustym argumentem,
   * Albo Trae bezpośrednio parsuje tag `<content>` i interpretuje go jako samodzielne wywołanie narzędzia `content`, które nie istnieje w rejestrze narzędzi.

---

## 3. DETERMINISTYCZNY PLAN NAPRAWY (W ramach Filara 5)

W `server.py` w module normalizacji narzędzi (`_parse_tool_calls`):
1. **Reguła auto-naprawy tagów potomnych:**  
   Wewnątrz bloku `<tool_call name="Write">` lub `<invoke name="Write">`:
   Jeżeli występuje tag `<content>...</content>` (bez opakowania w `<parameter name="content">`), proxy musi deterministycznie zmapować jego wnętrze jako parametr `params["content"] = text`.
2. **Eliminacja błędu `Tool's name content is not available`:**  
   Dzięki tej prostej normalizacji Trae otrzyma poprawny JSON `{"file_path": "...", "content": "..."}`, a model nigdy nie dostanie błędu nieistniejącego narzędzia.
