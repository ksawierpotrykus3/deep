# Historia ustaleń i operacji projektu OLX

> **Workspace:** `c:\Users\Ksawier\Pictures\Screenshots\Projekty_zlecenia\OLX`  
> **Status:** Zakończony etap RECON, zdefiniowana architektura detektora i komparatora.

---

## 1. Wstępne założenia i plan projektu

### Prompt Użytkownika:
> *Skupmy sie tylko na OLX. zrob plan w ktorym opiszesz dokladne zalozenia, czyli zeby bylo przed wyszukiwarka, jak to zrobisz. jak to bedziesz weryfikowac. trzeba odrazu stworzyc cos co weryfikuje przegladarke z tym co my wyszukamy przed nia i to bedzie wyliczac odrazu ile jest minut szybciej. i 0 powiadomien wszystko w logach i cmd*

### Odpowiedź AI (Ustalenia architektoniczne):
* **Cel:** Bot OLX od zera, który wyprzedza wyszukiwarkę metodą przewidywania rosnących ID, sam się weryfikuje (porównuje detekcję ID z wynikami wyszukiwarki) i **od razu liczy przewagę w minutach** (`T_browser − T_detect`). Zero powiadomień — wszystko w logach + konsola (cmd).
* **4 moduły bota:**
  1. **M1 — Weryfikator endpointów / seed:** ustalenie aktualnego granicznego ID na OLX.
  2. **M2 — Detektor:** przewidywanie przyszłych ID (`max_id + 1 … +K`) i bezpośrednie odpytywanie `/api/v1/offers/{id}/`.
  3. **M3 — Komparator:** cykliczne sprawdzanie publicznej wyszukiwarki i liczenie: `przewaga[min] = T_browser − T_detect`.
  4. **M4 — Logger:** pliki z logami w `logs/` (`detect.log`, `compare.log`, `live_site.log`, `app.log`).

---

## 2. Doprecyzowanie roli klucza API i mechaniki bazy OLX

### Prompt Użytkownika:
> *klucz jest po to zeb ywyslac milion requestow znaczy ze duzo bez banow. a kluczem jest to że zawsze istnieja ogloszenia w glownej bazie i na podstaqwie tego mozna jakos wyliczac te ID., wiem ze to dzialalo, wysylalo klientowi na telegrama normalnie kilo minutowa przewaga nad przegladarka. i on mogl juz dzwonic do tych ludzi juz zanim to sie pojawi w przegladarce.*

### Odpowiedź AI:
* **Metoda:** Ogłoszenia **najpierw istnieją w głównej bazie OLX** pod sekwencyjnym, rosnącym ID numerycznym, zanim trafią do indeksu wyszukiwarki frontendu.
* **Efekt biznesowy:** Klient mógł dzwonić do wystawców ofert z przewagą kilku/kilkunastu minut, zanim ogłoszenie pojawiło się w przeglądarce.

---

## 3. Wytyczne do testów LIVE i filtry kategorii

### Prompt Użytkownika:
> *Dobra sprobuj odpalic live testy. tego zobacz co uda ci sie znalezc. mozesz dluuuugo to robic. przynies wyniki. zapisuj porazki i sukcesy jako dowody, OLX to cos o czym nie masz pojecia az tak. wiec musimy goi poznac i tworzyc dokumentacje. sprobuj sprawic zeby to dzialalo. jak cos to bierzemy auta do 12k z mazowsza. i iphony macbooki cala polska. i one mialy swoje kategorie. pamietam ze kiedys jak to robilem to np ttrzeba bylo usuwac konkretne slowa klucze bo kategorie nie byly idealne.*

---

## 4. Kluczowe odkrycia z fazy RECON (Dowody techniczne)

Wszystkie dowody zostały zbadane i potwierdzone deterministycznie:

1. **Ochrona CloudFront & TLS Fingerprint:**
   * Zwykły `curl` oraz biblioteka `requests` dostają natychmiastowy kod **403 Forbidden** od CloudFront.
   * **Rozwiązanie:** Biblioteka `curl_cffi` z parametrem `impersonate="chrome124"` omija blokadę CloudFront i zwraca **200 OK**.

2. **Wewnętrzne API OLX:**
   * Lista ofert: `GET https://www.olx.pl/api/v1/offers/?offset=0&limit=N`
   * Pojedyncza oferta po ID: `GET https://www.olx.pl/api/v1/offers/{numeric_id}/`
   * Nieistniejące / przyszłe wolne ID zwraca kod **404 Not Found**.
   * Istniejące ogłoszenie zwraca kod **200 OK** z pełnym obiektem JSON oferty.

3. **Podwójny system ID:**
   * W adresach URL stron ogłoszeń znajduje się alfanumeryczny hash (np. `ID9xYZ`), który nie jest sekwencyjny.
   * W odpowiedziach JSON API znajduje się prawdziwe **numeryczne ID globalne** (np. `1093493751`), które rośnie sekwencyjnie w skali całego portalu.

4. **Zmapowane kategorie i filtry (`category.id`):**
   * **iPhone:** `category.id == 2298` (Wymagana czarna lista akcesoriów: *etui, szkło, obudowa, case, ładowarka, słuchawki, uchwyt, folia*).
   * **MacBook:** `category.id == 3102` (Wymagany filtr w tytule: *macbook, mac book, mac*).
   * **Samochody osobowe:** `category.type == "automotive"`, cena `<= 12000 PLN`, region `mazowieckie`. Wykluczamy części (`category.id == 1465`) oraz oferty z Otomoto (`partner.code == "otomoto_pl_form"`).

---

## 5. Weryfikacja oficjalnego klucza API (Client ID `202745`)

### Prompt Użytkownika:
> *tu masz api baranie OFICJASLNE z rozmowy on tam wkleil na samym dole. jak to kurwa jeszcze kilka miesiecy temu pozwalalo mi to przeszukiwac wszystko. oni cos zmienili? ssprawdz google*

### Odpowiedź AI (Dowody z oficjalnego API i dokumentacji):
1. **OAuth działa:** `POST https://www.olx.pl/api/open/oauth/token` z danymi `client_id=202745` poprawnie generuje ważny token JWT (`partner_code: 4420`, `scope: v2 read write`).
2. **Endpoint partnerski `/api/partner/adverts`:**
   * Zwraca `400 Invalid user ID in token` przy autoryzacji `client_credentials`.
   * Zgodnie z oficjalną dokumentacją OLX Developers FAQ:
     > *"Czy mogę użyć API do pobierania informacji o ogłoszeniach innych użytkowników? — Nie jest to możliwe, możesz zarządzać wyłącznie ogłoszeniami na swoim koncie OLX."*
   * Rate-limit oficjalnego API wynosi 4500 req / 5 min na IP.
3. **Podsumowanie źródła przewagi:**
   * Źródłem przewagi czasowej **nie jest** endpoint partnerski, lecz **publiczne API `/api/v1/offers/{id}/`** odpytywane po rosnących numerach ID z użyciem `curl_cffi` (TLS Chrome).

---

## 6. Zadanie końcowe (Tryb 20-minutowego monitora)

### Prompt Użytkownika:
> *program musi dzialac przez 20 minut i wszystkie zlecenia ktore sie da dostac przed wyszukiwarka mamy dostac wiec musisz miec:*
> 1. *cos co pokazuje ci strone na zywo i wiesz zeto dziala i pokazue wszystko i to uwodonic*
> 2. *to co daje te ogloszenia przed tym pierwszym i dzieki wynikom z 1 mozesz przyrownac zmierzyc ile minut.*
> 3. *jelski cos nie dziala to tworzyc dokumentacje tego co np nie dziala i dlaczego z DOWODEM.*

### Wymagania techniczne do skryptu `monitor_20min.py`:
1. **Lokalizacja skryptu:** `C:\Users\Ksawier\Pictures\Screenshots\Projekty_zlecenia\OLX\recon\monitor_20min.py`
2. **Struktura katalogu logów:** `C:\Users\Ksawier\Pictures\Screenshots\Projekty_zlecenia\OLX\logs\`
   * `detect.log` — trafienia detektora ID (ID, kategoria, tytuł, cena, timestamp detekcji `T_detect`).
   * `compare.log` — wyniki komparatora: powiązanie oferty z momentem pojawienia się w wyszukiwarce publicznej (`T_browser`) oraz wyliczona przewaga czasowa (`przewaga = T_browser - T_detect`).
   * `live_site.log` — dowód działania odpytywania publicznej wyszukiwarki (liczba zwróconych ofert w każdej turze).
   * `app.log` — ogólne komunikaty diagnostyczne i błędy.
3. **Parametry:** Czas działania = 20 minut, zero powiadomień, pełny zapis do logów i konsoli stdout.
