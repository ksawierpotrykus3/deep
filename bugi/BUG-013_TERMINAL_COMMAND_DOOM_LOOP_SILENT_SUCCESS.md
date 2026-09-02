# BUG-013: Pętla Zagłady Komend Terminala (8x `py_compile` PowerShell Doom Loop) z Powodu Paranoi Cichego Sukcesu (Silent Success Paranoia)

**Data rejestracji:** 2026-08-31 22:23  
**Komponenty:** Model Planning, Terminal Tool Result Formatter, `server.py` (Command Debounce / Rate Limiter)  
**Wpływ na działanie:** WYSOKI (Model zaciął się w 8-krotnym powtarzaniu komendy `py_compile` na pliku `chain_executor.py`, testując różne dialekty PowerShell w poszukiwaniu stringa 'OK', co wyczerpało slot i zerwało sesję; kod na dysku jest w 100% poprawny).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutów ekranu i weryfikacja kodu)

### Incydent 1: Sekwencja 8 komend kompilacji z wariacjami PowerShell
* **Zarejestrowana lista wywołań narzędzia terminala w jednym dymku:**
  1. `python -m py_compile "...\chain_executor.py"`
  2. `python -m py_compile "...\chain_executor.py"`
  3. `python -m py_compile "...\chain_executor.py" ; echo "OK"`
  4. `python -m py_compile chain_executor.py; if ($?) { echo "OK - skladnia poprawna" }`
  5. `python -m py_compile chain_executor.py; if ($?) { echo "OK - skladnia poprawna" }`
  6. `Read chain_executor.py`
  7. `python -m py_compile chain_executor.py; if ($?) { Write-Output "OK" } else { Write-Output "BLAD" }`
  8. `python -m py_compile chain_executor.py`
  9. `Read chain_executor.py`
  10. `python -m py_compile chain_executor.py; if ($?) { "OK" } else { "BLAD" }`
* **Wynik:** Model wpadł w amok weryfikacyjny i zablokował strumień.

### Incydent 2: Weryfikacja deterministyczna poprawności pliku
Uruchomiono bezpośrednio w systemie:
```powershell
python -m py_compile "c:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\useme_core\chain_executor.py"
# Exit code: 0, Błędy: BRAK
```
Plik [`useme_core/chain_executor.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/useme_core/chain_executor.py) został zapisany na dysku i ma w 100% poprawną składnię Pythona.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Paranoja Cichego Sukcesu (*Silent Success Misinterpretation*)
Narzędzie `python -m py_compile` przy braku błędów kończy działanie sukcesem (Exit code 0) i **nie zwraca żadnego tekstu do konsoli**. Model DeepSeek zinterpretował pusty output jako brak potwierdzenia i zaczął desperacko kombinować z operatorami PowerShell (`; echo "OK"`, `if ($?) { ... }`, `Write-Output`), aby wymusić tekstową informację zwrotną.

### B. Brak bezpiecznika komend powłoki w proxy
Podobnie jak przy pętlach odczytu plików (`Read`), proxy nie posiadało licznika powtórzeń dla komend terminala (`RunCommand`). Gdyby po 2. identycznej komendzie proxy zwróciło symulowany komunikat: `[OK - Komenda powiodła się, kod zakończony kodem 0]`, model natychmiast przeszedłby do kolejnego kroku.

---

## 3. DETERMINISTYCZNA NAPRAWA

1. **Plik `chain_executor.py` jest gotowy i poprawny.**
2. **Instrukcja odblokowująca dla Trae:**
   W nowym czacie wpisz do agenta:
   > *„Plik `useme_core/chain_executor.py` został sprawdzony kompilatorem – składnia jest w 100% poprawna. Nie uruchamiaj py_compile. Przejdź bezpośrednio do uruchomienia testu integracyjnego lub kolejnego modułu.”*
