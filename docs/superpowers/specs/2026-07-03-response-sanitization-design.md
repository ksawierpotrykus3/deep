# Specyfikacja: Sanityzacja odpowiedzi DeepSeek dla Trae IDE

## Cel
Usuwanie metadanych (tagów XML, prefiksów, nagłówków sekcji) z odpowiedzi DeepSeek przed wysłaniem ich do Trae, aby uniknąć nieprawidłowej interpretacji przez interfejs użytkownika. Sanityzacja nie może ingerować w mechanizm identyfikacji sesji (watermarking).

## Zakres
- Oczyszczanie treści odpowiedzi z tagów XML/metadanych.
- Usuwanie prefiksów: `MCP:`, `Skill:`, `Task:`.
- Usuwanie nagłówków sekcji (np. `###`, `---`).
- **Zachowanie watermarków** – tag `PROXY_SID` musi pozostać nietknięty.

## Implementacja

### 1. Lista tagów do usunięcia (`_STRIP_TAGS`)
Rozszerzona lista konkretnych tagów XML, które mają być usunięte. **Nie używać generycznego regexa `]*>`**, ponieważ usunąłby legalne tagi HTML/XML w przykładach kodu.

```python
_STRIP_TAGS = {
    "tool_call", "invoke", "tool_capability", "mcp_info",
    "server_name", "available_skills", "skill",
    # Dodajemy inne znane tagi metadanych, ale NIGDY nie usuwamy:
    # "PROXY_SID" – musi być zachowane
}
```

### 2. Usuwanie prefiksów
Regex usuwający prefiksy `MCP:`, `Skill:`, `Task:` z treści.

### 3. Usuwanie nagłówków sekcji
Regex usuwający linie zaczynające się od `###`, `---` itp.

### 4. Ochrona watermarków
`PROXY_SID` nie podlega żadnemu usuwaniu – musi być traktowane jako część treści odpowiedzi. Wszystkie operacje regex muszą być testowane pod kątem pozostawienia tego tagu bez zmian.

### 5. Testowanie kompatybilności
Należy dodać test jednostkowy (np. w `tests/`), który:
- Przyjmuje przykładową odpowiedź z watermarkiem `<!-- PROXY_SID:abc123... -->`.
- Przepuszcza przez funkcję sanitizacji.
- Sprawdza, czy watermark pozostał dokładnie taki sam.

## Zależności od istniejącego kodu
Sanityzacja jest wywoływana w `server.py` po wyciągnięciu tool calli, przed wysłaniem do Trae. Mechanizm watermarkingu (`_get_conv_key()`, wstrzykiwanie `<!-- PROXY_SID:... -->`) jest już zaimplementowany – sanityzacja musi go respektować.

## Plan wdrożenia
1. Zaktualizować `_STRIP_TAGS` – dodać wszystkie znane tagi metadanych, ale **nie dodawać `PROXY_SID`**.
2. Zmodyfikować funkcję sanitizacji, aby **nie usuwała** żadnych tagów zawierających `PROXY_SID` (np. poprzez sprawdzenie, czy dany fragment nie zaczyna się od `<!-- PROXY_SID:`).
3. Napisać test jednostkowy weryfikujący zachowanie watermarków.
4. Zintegrować z `server.py` – wywołać sanitizację na odpowiedzi przed wysłaniem.

## Uwagi
- Generyczne stripowanie XML jest zabronione – używać tylko konkretnych tagów z `_STRIP_TAGS`.
- Wszystkie zmiany muszą być testowane na rzeczywistych odpowiedziach DeepSeek, aby upewnić się, że nie usuwają one treści użytkownika ani kodu.
- Watermarki są kluczowe dla ciągłości rozmów – ich usunięcie spowoduje utratę kontekstu.