# Changelog

## v0.6.0 — walidacja CSV, diagnostyka, przygotowanie EXE (2026-11-20)

- Dodano szczegółowe komunikaty z numerami wierszy przy pustych i zduplikowanych nazwach.
- Dodano odczytową diagnostykę CSV w GUI oraz CLI `doctor`.
- Dodano kontrolę dostępności Poppler i Tesseract w GUI i CLI.
- Dodano skrypt `scripts/build_windows.ps1` dla PyInstaller (one-folder) oraz rozdzielenie ścieżek zasobów i danych dla aplikacji spakowanej.
- Dodano testy regresyjne, w tym problematycznego CSV wybranego w GUI.
- Testy: 65/65 na Linuxie; build EXE i test GUI na Windows pozostają do wykonania.


## v0.5.0 — Dashboard, raporty i Windows (2026-11-20)

- Dodano dashboard z KPI i wykresami przychodów miesięcznych oraz TOP produktów.
- Dodano wyszukiwarkę magazynu oraz filtrowanie historii po nazwie, statusie i datach UTC.
- Dodano raporty CSV i XLSX (5 arkuszy), eksport z GUI oraz `main.py report`.
- Naprawiono błąd WinError 1: bezpieczne tworzenie plików bez hard linków.
- 58/58 testów, pełny test demo PDF → OCR → SQLite → XLSX → undo.
- Nowe GUI wciąż wymaga uruchomienia na komputerze użytkownika.

## v0.4.0 — SQLite, audyt i cofanie (2026-11-20)

- Dodano `invoiceflow/history.py` z SQLite: importy, pozycje, migawki CSV i tabela aktualnych produktów.
- Dodano blokowanie duplikatów PDF przez SHA-256 i kontrolę łańcucha wersji magazynu.
- Dodano odtwarzanie stanu magazynu sprzed ostatniego importu (`undo`) do nowego CSV.
- Dodano CLI `history`, `undo`, audytowany `apply --pdf/--ledger` bez nadpisywania wyników.
- Dodano okno GUI z historią, podsumowaniem i stanem produktów oraz cofanie najnowszego importu.
- Dodano testy ochrony przed duplikatem, starym magazynem, uszkodzonym eksportem i cofania.
- 50/50 testów; potwierdzono pełny obieg na fikcyjnym dwustronicowym PDF z realnym OCR.
- GUI wymaga sprawdzenia na Windows; nie twierdzimy, że działa tam bez testu.

## v0.3.0 — wielostronicowe OCR i diagnostyka (2026-11-20)

- Dodano `--all-pages` i limit stron oraz przetwarzanie PDF strona po stronie.
- Dodano `quality.json`: sygnały niskiej pewności, braków i podejrzanych liczb.
- Dodano obrazy `layout.jpg` i `layout_p002.jpg` z prostokątami OCR.
- GUI pozwala przełączać strony, pokazywać ramki i wyróżnia ostrzegane pozycje.
- Dodano interaktywny kreator szablonów `main.py calibrate` (wybór ROI w OpenCV).
- Dołączono bezpieczne demo: fikcyjny dwustronicowy PDF, szablon i wizualizację w README.
- Rozszerzono testy; wykonano rzeczywisty OCR demonstracyjnego PDF przez Tesseract i Poppler.

## v0.2.0 — GUI / review (2026-11-20)

- Dodano GUI w CustomTkinter z podglądem, edycją i zatwierdzaniem pozycji.
- Dodano opcjonalne ścieżki do Poppler i Tesseract.
- Dodano atomowy zapis i odczyt `review.csv`.
- Eksport do osobnego pliku, bez nadpisywania bazy wejściowej.

## v0.1.0 — silnik OCR / CLI

- Wydzielono moduły skanowania i aktualizacji magazynu.
- Dodano szablon JSON, walidację i testy.
- Wprowadzono ręczne zatwierdzanie danych przed aktualizacją CSV.
