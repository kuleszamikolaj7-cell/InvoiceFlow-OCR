# Test manualny — InvoiceFlow OCR v0.5 (Windows)

Testuj wyłącznie na fikcyjnych danych `examples/`, a nie na produkcyjnej bazie. GUI v0.5 wymaga sprawdzenia na Twoim Windowsie.

1. Uruchom `python gui.py`. Otwórz `Dashboard i historia`: powinien pojawić się widok z trzema zakładkami, nawet gdy historia jest pusta.
2. Zamknij to okno, wybierz `examples/demo_invoice.pdf`, `examples/FinancialSheet_example.csv` i w ustawieniach zaawansowanych `examples/demo_invoice_template.json`.
3. Zaznacz `Skanuj wszystkie strony` i `Pomiń puste wiersze`; uruchom skanowanie.
4. Sprawdź 3 odczytane pozycje: Product A/2/15.50, Product B/1/12.00, Product C/1/9.90. W razie błędu popraw ręcznie i zatwierdź.
5. Potwierdź, że to faktura sprzedaży, a kwoty oznaczają wartości całych pozycji. Eksportuj do **nowej** nazwy pliku CSV.
6. Otwórz dashboard: aktywne importy = 1; pozycje = 3; wartość = 37.40; powinny pokazać się słupki sprzedaży i TOP produktów.
7. W Historii sprawdź wyszukiwanie `demo_invoice`, filtry Aktywne/Cofnięte i daty `2020-01-01` do `2100-01-01`. Niepoprawna data powinna pokazać czytelny błąd.
8. W Magazynie wpisz `Product`, zaznacz `Tylko niski stan (≤ 5)` i sprawdź filtrowanie.
9. Wyeksportuj XLSX oraz CSV do nowych nazw. XLSX powinien mieć 5 zakładek: Podsumowanie, Importy, Produkty, Top produkty i Sprzedaż miesięczna.
10. Ponownie spróbuj rozliczyć ten sam PDF — aplikacja powinna zablokować duplikat.
11. Przetestuj cofnięcie ostatniego importu do **nowej nazwy** CSV. Plik powinien mieć dokładnie taki sam stan jak `examples/FinancialSheet_example.csv`. Dashboard ma pokazywać 0 aktywnych i 1 cofnięty import.
12. Upewnij się, że `WinError 1` nie wrócił, oraz że wybór istniejącego pliku eksportu nie usuwa jego zawartości.

## Wskazówki

- Każdy import zostawia historię: do powtarzanych testów używaj osobnej kopii projektu, nowego `--ledger` albo cofaj ostatni import, zamiast kasować prywatne dane.
- Jeśli przenosisz historię z v0.4, zachowaj stare pliki CSV pod ich dotychczasowymi ścieżkami, inaczej cofnięcie może zostać zablokowane.
- Zapisz zrzut ekranu dashboardu dopiero po upewnieniu się, że widoczne są wyłącznie dane demonstracyjne.
