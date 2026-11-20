# Windows — testy ręczne InvoiceFlow OCR v0.6

Używaj wyłącznie fikcyjnych danych demonstracyjnych. Nie aktualizuj prawdziwego magazynu podczas testów.

## Instalacja i rozpoznawanie

- [ ] Testy automatyczne: `.\.venv\Scripts\python.exe -m pytest -q`.
- [ ] Uruchom `gui.py`, kliknij **Diagnostyka OCR** i potwierdź obecność pdfinfo, pdftoppm i Tesseract.
- [ ] Wybierz `examples/demo_invoice.pdf`, `examples/FinancialSheet_example.csv` i `examples/demo_invoice_template.json`.
- [ ] Sprawdź przyciskiem bazę CSV — wyświetla 3 produkty.
- [ ] Skanuj wszystkie strony i pomiń puste wiersze. Porównaj dane w tabeli z PDF.
- [ ] Zatwierdź pozycje i wykonaj eksport do nowej nazwy CSV.

## Zabezpieczenia i historia

- [ ] Wybranie CSV z duplikatami pokazuje numery wierszy i nie daje eksportować.
- [ ] Ponowny import tej samej faktury jest blokowany.
- [ ] Historia i raport XLSX pokazują aktywne importy.
- [ ] Cofnięcie ostatniego importu tworzy nowy CSV i usuwa operację z aktywnych statystyk.
- [ ] Nie wraca `WinError 1` na dysku D: ani przy próbie eksportu pod istniejącą nazwą.

## Budowanie i wydawanie EXE

- [ ] Uruchom `scripts/build_windows.ps1` w PowerShell i sprawdź wynik w `dist/InvoiceFlowOCR`.
- [ ] Przenieś cały folder do nowego zapisywalnego katalogu, uruchom `.exe` i powtórz demo.
- [ ] Sprawdź Tesseract/Poppler osobno, również z opcjonalnymi ścieżkami.
- [ ] Nie dołączaj prywatnych PDF, CSV, SQLite, wyników OCR ani danych lokalnych.
- [ ] Wykonaj prawdziwy screenshot GUI na fikcyjnych danych przed aktualizacją README.

**Uwaga:** ten dokument jest checklistą do odhaczenia, nie zapisem wykonanych testów Windows.
