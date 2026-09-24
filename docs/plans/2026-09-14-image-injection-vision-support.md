# Obsługa Multimodalności (Image Injection / Vision) w DeepSeek Proxy

Zaimplementowanie pełnego, natywnego przesyłania obrazów dostarczanych przez IDE (w formacie OpenAI Vision `image_url` / base64 / URL) bezpośrednio do DeepSeek Web Chat API z użyciem endpointu `POST /api/v0/file/upload_file`, dedykowanego wyzwania PoW oraz `ref_file_ids` w `chat/completion`, przy jednoczesnym usunięciu starych, martwych i atrapowych rozwiązań (np. spłaszczania obrazów do stringów `"[Image]"` czy martwego mapowania modelu `"deepseek-vision"`).

---

## User Review Required

> [!IMPORTANT]
> **Kluczowe decyzje architektoniczne:**
> 1. **Domyślny model flash (`model_type: "default"`):** Analiza przechwyconego pliku `image_injection.har` potwierdziła, że silnik DeepSeek Vision jest w pełni zintegrowany z modelem domyślnym (`default` / flash). Model w swoich myślach oraz odpowiedzi bez problemu przetwarza obrazy.
> 2. **Usunięcie sztucznego tagu `[Image]`:** Do tej pory `_extract_text_content` zamieniał zawartość obrazka na tekst `"[Image]"` i porzucał dane binarne. Po wdrożeniu obrazy będą wgrywane jako pliki, a tekst promptu pozostanie czysty (zawierający wyłącznie instrukcje tekstowe użytkownika).
> 3. **Multipart i `curl_cffi`:** W `curl_cffi` upload pliku wymaga użycia klasy `CurlMime` (standardowe `files={}` rzuca `NotImplementedError`).
> 4. **Izolacja PoW per endpoint:** Wyzwanie Proof-of-Work dla uploadu pliku (`target_path: "/api/v0/file/upload_file"`) jest niezależne od wyzwania dla completions (`target_path: "/api/v0/chat/completion"`). Cache PoW musi uwzględniać krotkę `(slot, target_path)`.

---

## Open Questions

Brak pytań blokujących. Format OpenAI Vision (`image_url` data URIs base64 oraz `http(s)`) jest precyzyjnie określony, a format uploadu DeepSeek został w 100% zdekodowany z `image_injection.har`.

---

## Proposed Changes

### 1. Komponent Przetwarzania Obrazów (`server/utils/helpers.py` & `server/core/image_service.py`)

Zastąpienie nieużywanego i niespójnego kodu z `helpers.py` czystym, ustrukturyzowanym serwisem przetwarzania obrazów.

#### [MODIFY] [helpers.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server/utils/helpers.py)
* Usunięcie martwych/starych funkcji `_compress_image` i `_extract_images` z `helpers.py`.
* Pozostawienie funkcji pomocniczych JSON i chunkowania SSE.

#### [NEW] [image_processor.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server/core/image_processor.py)
* Klasa `ExtractedImage` przechowująca: `data: bytes`, `filename: str`, `mime_type: str`, `file_size: int`.
* Funkcja `extract_images_from_messages(messages: list[dict]) -> tuple[list[ExtractedImage], list[dict]]`:
  * Wydobywa obrazy z bloków `image_url` (zarówno `data:image/...;base64,...`, jak i ewentualnych linków `http/https`).
  * Zwraca oczyszczone wiadomości (gdzie tekst użytkownika nie jest zanieczyszczony atrapami `[Image]`) oraz listę wyodrębnionych obiektów `ExtractedImage`.
* Bezpieczna kompresja/konwersja dużych obrazów do formatu JPEG/PNG (z zachowaniem limitów DeepSeek).

---

### 2. Proof-of-Work z obsługą wielu endpointów (`server/core/deepseek_client.py`)

#### [MODIFY] [deepseek_client.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server/core/deepseek_client.py)
* **Wielościeżkowy PoW:**
  * Rozszerzenie `_get_challenge(slot: int, target_path: str = "/api/v0/chat/completion") -> dict`.
  * Rozszerzenie `_get_pow(slot: int, target_path: str = "/api/v0/chat/completion") -> str`.
  * Zmiana klucza cache: `_pow_cache: dict[tuple[int, str], str]` oraz `_pow_expires: dict[tuple[int, str], float]`.
* **Nowa metoda `upload_file`:**
  ```python
  def upload_file(
      self,
      slot: int,
      file_data: bytes,
      filename: str = "image.png",
      mime_type: str = "image/png",
      model_type: str = "default",
  ) -> str:
      """Upload image/file to DeepSeek Web API and return file-xxxxxxxx id."""
  ```
  * Pobiera PoW dla `target_path: "/api/v0/file/upload_file"`.
  * Buduje `CurlMime` z polem `file`.
  * Ustawia nagłówki: `x-ds-pow-response`, `x-file-size: str(len(file_data))`, `x-model-type: model_type`, `x-thinking-enabled: 1`.
  * Wykonuje `POST /api/v0/file/upload_file`.
  * Parsuje odpowiedź JSON i zwraca `data.biz_data.id` (np. `"file-b78c5a26-..."`).

---

### 3. Usunięcie nieużywanych i mylących mapowań modeli (`server/core/input_parser.py`)

#### [MODIFY] [input_parser.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server/core/input_parser.py)
* W `_MODEL_TYPE_MAP`:
  * Usunięcie `"deepseek-vision": "vision"` (w API DeepSeek Web nie istnieje `model_type: "vision"`, model `vision` to po prostu załącznik pliku `model_kind: "VISION"` na modelu `"default"`).
  * Zamiana aliasu: `"deepseek-vision": "default"`.

---

### 4. Integracja uploadu obrazów i `ref_file_ids` w Proxy (`server/services/proxy_service.py`)

#### [MODIFY] [proxy_service.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server/services/proxy_service.py)
* W `_extract_text_content()`:
  * Usunięcie doklejania atrapy `[Image]` / `[Image: url]`. Tekst promptu użytkownika pozostaje czysty.
* W `chat_completions()`:
  * Przed wysłaniem promptu: sprawdzenie czy w najnowszych wiadomościach tury znajdują się obrazy.
  * Jeśli wykryto obrazy:
    * Dla każdego obrazu wywołanie `file_id = ds.upload_file(account_idx, img.data, img.filename, img.mime_type, model_type=parsed.model_type)`.
    * Skompletowanie `ref_file_ids = [file_id, ...]`.
  * Przekazanie `ref_file_ids` do wywołania `ds.stream_completion(...)`:
    ```python
    stream_gen_obj, stream_meta_obj = ds.stream_completion(
        account_idx,
        chat_id,
        prompt,
        parent_id,
        model_type=parsed.model_type,
        ref_file_ids=ref_file_ids,
        ...
    )
    ```
  * Zapis `ref_file_ids` w stanie sesji (`conv_state`) na wypadek retry/recovery.

---

### 5. Aktualizacja i rozbudowa testów (`tests/`)

#### [MODIFY] [test_stream_service_utils.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/tests/test_stream_service_utils.py)
* Usunięcie testów starego `_extract_images` z `helpers.py`.
* Dodanie testów nowego modułu `image_processor.py`:
  * Ekstrakcja z Data URI (base64 png/jpeg).
  * Oczyszczanie wiadomości i zachowanie czystego promptu tekstowego.
  * Walidacja MIME type i rozmiaru.

#### [NEW] [test_image_upload.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/tests/test_image_upload.py)
* Testy jednostkowe `DeepSeekClient.upload_file` (mockowanie PoW, sesji i `CurlMime`).
* Testy obsługi błędów uploadu (np. brak ID w odpowiedzi, błąd HTTP, brak PoW).
* Testy integracji `proxy_service.chat_completions` z przekazywaniem `ref_file_ids`.

---

## Verification Plan

### Automated Tests
1. Uruchomienie nowych i zaktualizowanych testów jednostkowych:
   ```bash
   pytest tests/test_image_processor.py tests/test_image_upload.py tests/test_stream_service_utils.py -v
   ```
2. Uruchomienie pełnego zestawu testów serwera proxy w celu weryfikacji braku regresji:
   ```bash
   pytest tests/ -v
   ```

### Manual Verification
1. Wysłanie próbnego requestu przez `curl` / Python do lokalnego serwera proxy z obrazem testowym zakodowanym w base64 (standard OpenAI Vision):
   ```json
   {
     "model": "deepseek-v4-flash",
     "messages": [
       {
         "role": "user",
         "content": [
           {"type": "text", "text": "Jaki kolor ma ten obrazek?"},
           {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}}
         ]
       }
     ],
     "stream": true
   }
   ```
2. Sprawdzenie w logach proxy:
   * Wygenerowanie PoW dla `/api/v0/file/upload_file`.
   * Sukces `upload_file` i uzyskanie identyfikatora `file-...`.
   * Wysłanie `chat/completion` z `ref_file_ids: ["file-..."]`.
   * Potwierdzenie, że model na typie `default` poprawnie zinterpretował załączony obraz.
