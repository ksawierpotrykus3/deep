============================================================
   DeepSeek Proxy - instrukcja uruchomienia (krok po kroku)
============================================================

CO TO JEST:
  To program, ktory zamienia darmowy czat DeepSeek w strona
  (chat.deepseek.com) na "udawane API". Dzieki niemu mozesz
  uzywac DeepSeek w Trae (lub innym programie) za darmo.

  W skrocie:
  - Uruchamiasz serwer lokalnie
  - Logujesz swoj darmowy konto DeepSeek
  - Podpinasz w Trae: http://localhost:4570
  - I uzywasz jak normalnego API

------------------------------------------------------------
KROK 1 - SPRAWDZ CZY MASZ PYTHONA
------------------------------------------------------------
  Otworz CMD (Wyszukaj: "cmd" i Enter) i wpisz:
      python --version
  - Jesli widzisz cos jak "Python 3.11.x" lub nowsze - OK, idz do KROKU 2.
  - Jesli widzisz blad "python is not recognized":
      1. Wejdz na https://www.python.org/downloads/ i pobierz Pythona
      2. Instalujac ZAZNACZ opcje: "Add Python to PATH" (to wazne!)
      3. Po instalacji zamknij i otworz CMD od nowa, sprawdz jeszcze raz
  - UWAGA: W CMD wpisujacy "python" a nie "python3".

------------------------------------------------------------
KROK 2 - ZAINSTALUJ ZALEZNOSCI (tylko raz)
------------------------------------------------------------
  W CMD wejdz do folderu z tymi plikami:
      cd C:\sciezka\do\folderu\deepseek-proxy
  (albo: w Eksploratorze otworz folder, wpisz "cmd" w pasku adresu i Enter)

  Potem wpisz:
      pip install -r requirements.txt
  - Zaczekaj az sie zainstaluje (moze trwac pare minut).
  - Jak cos sie sypie - napisz do sprzedawcy, to nie Twoj blad.

------------------------------------------------------------
KROK 3 - URUCHOM PROXY
------------------------------------------------------------
  Kliknij DWUKROTNIE:   start.bat
  - Otworzy sie czarne okno z napisem "Uruchamianie proxy..."
  - NA KONCU powinno byc cos jak:
        Active accounts: X/3. Ready for requests.
  - NIE ZAMYKAJ tego okna! Serwer musi dzialac w tle.

------------------------------------------------------------
KROK 4 - ZALOGUJ KONTO DEEPSEEK (NAJWAZNIEJSZE)
------------------------------------------------------------
  Kliknij DWUKROTNIE:   login_slot.bat
  (to uruchamia sie w DRUGIM oknie - pierwsze okno z serwerem ma zostac)

  - Otworzy sie przegladarka z DeepSeek.
  - ZALOGUJ SIE na swoj darmowy konto (mozesz je zalozyc w 1 min).
  - NIE ZAMYKAJ przegladarki sam! Zamknie sie sama po zalogowaniu.
  - W oknie serwera zobaczysz: "Active accounts: 1/3".

  MASZ JEDNO KONTO - wystarczy. Koniec konfiguracji.

  OPCJONALNIE: wiecej kont = wiecej zapytan zanim DeepSeek ograniczy
  predkosc. Zaloguj do 3 kont powtarzajac login_slot.bat (kolejne
  konta trzeba uruchamiac z CMD:  login_slot.bat 1  i  login_slot.bat 2).

------------------------------------------------------------
KROK 5 - PODEPNIJ DO TRAE
------------------------------------------------------------
  W Trae: Ustawienia - Model - dodaj dostawce "OpenAI compatible":
  - Base URL (API):  http://localhost:4570
  - Klucz API:       dowolny tekst, np. "x" (proxy nie sprawdza)
  - Model:           deepseek-v4-pro

------------------------------------------------------------
JESLI COS NIE DZIALA
------------------------------------------------------------
  1. Blad 503 "Brak zalogowanych kont"
     -> Zapomniales zalogowac konto. Zrob KROK 4 i sprobuj znowu.
  2. Przegladarka nie otworzyla sie po login_slot.bat
     -> Sprawdz czy start.bat dziala (otworz w przegladarce:
        http://localhost:4570/health  - powinno byc {"status":"ok"})
  3. "Browser was closed before sign-in completed"
     -> Zamknieto przegladarke za szybko. Uruchom login_slot.bat
        jeszcze raz i NIE ZAMYKAJ jej - poczekaj.
  4. DeepSeek zwalnia lub przestaje odpowiadac po dluzszym uzyciu
     -> To normalne - darmowy czat ma limity. Odczekaj chwile,
        zaloguj dodatkowe konta (KROK 4), albo zmien slot w CMD:
        login_slot.bat 1
  5. Komputer sie restartowal / okno zniknelo
     -> Po prostu uruchom start.bat od nowa (KROK 3).
        Sesje zostaja zapisane, nie trzeba logowac sie ponownie.

------------------------------------------------------------
PLATNY KLUCZ API (OPCJONALNE - nie potrzebne do dzialania)
------------------------------------------------------------
  - Otworz plik: data\deepseek_api_key.txt
  - Zastap "sk-TWOJ_KLUCZ_API_DEEPSEEK_TUTAJ" swoim kluczem
    (klucze kupuje sie na platformie DeepSeek - to dodatkowy koszt)
  - Bez klucza proxy dziala normalnie na darmowym czacie.

------------------------------------------------------------
UWAGI:
  - Nie usuwaj folderow .chrome_slot i data - to dane zalogowanych kont.
  - Nie uruchamiaj login_slot.bat 2 razy naraz - zaczekaj az
    poprzednia przegladarka sie zamknie.
  - Konta webowe sa DARMOWE, klucz API jest PLATNY.
============================================================
