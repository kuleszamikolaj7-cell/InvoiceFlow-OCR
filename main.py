"""InvoiceFlow OCR — command-line entry point."""

import argparse
import sys
from pathlib import Path

from invoiceflow.history import commit_review, undo_last, list_imports, statistics
from invoiceflow.calibrate import create_template
from invoiceflow.scanner import scan_invoice
from invoiceflow.reporting import export_report
from invoiceflow.environment import check_environment, render_environment_report
from invoiceflow.diagnostics import inspect_inventory_csv

ROOT = Path(__file__).resolve().parent
LEDGER_FILE = ROOT / "data" / "invoiceflow.sqlite3"


def build_parser():
    parser = argparse.ArgumentParser(
        description="InvoiceFlow OCR: odczyt faktur i kontrolowana aktualizacja magazynu."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Sprawdź środowisko OCR i opcjonalnie plik CSV")
    doctor.add_argument("--db", type=Path, help="Sprawdź nagłówki i nazwy produktów w CSV")
    doctor.add_argument("--poppler-bin", type=Path)
    doctor.add_argument("--tesseract-bin", type=Path)

    scan = commands.add_parser("scan", help="Odczytaj PDF i utwórz plik review.csv")
    scan.add_argument("--pdf", type=Path, required=True, help="Ścieżka do faktury PDF")
    scan.add_argument(
        "--template", type=Path, default=ROOT / "templates" / "invoice1.json",
        help="Szablon współrzędnych (JSON)",
    )
    scan.add_argument(
        "--output", type=Path, default=ROOT / "output", help="Folder obrazów i review.csv"
    )
    scan.add_argument("--poppler-bin", type=Path, help="Folder z pdfinfo.exe i pdftoppm.exe")
    scan.add_argument("--tesseract-bin", type=Path, help="Pełna ścieżka do tesseract.exe")
    scan.add_argument("--all-pages", action="store_true", help="Skanuj wszystkie strony PDF (ten sam szablon dla każdej)")
    scan.add_argument("--max-pages", type=int, default=15, help="Limit stron w trybie --all-pages (domyślnie 15)")
    scan.add_argument("--omit-empty", action="store_true", help="Pomiń całkowicie puste wiersze OCR w review.csv")
    scan.add_argument(
        "--overwrite", action="store_true", help="Nadpisz istniejący review.csv"
    )

    apply = commands.add_parser("apply", help="Zastosuj zatwierdzony review.csv do kopii CSV")
    apply.add_argument("--review", type=Path, required=True, help="Zweryfikowany review.csv")
    apply.add_argument("--db", type=Path, required=True, help="Baza produktów CSV")
    apply.add_argument("--out", type=Path, default=ROOT / "output" / "inventory_updated.csv")
    apply.add_argument("--pdf", type=Path, help="Źródłowy PDF (zalecany; weryfikuje hash)")
    apply.add_argument("--ledger", type=Path, default=LEDGER_FILE, help="Rejestr importów SQLite")
    apply.add_argument("--overwrite", action="store_true", help="Nieobsługiwane w trybie audytu")
    history = commands.add_parser("history", help="Historia importów i statystyki SQLite")
    history.add_argument("--ledger", type=Path, default=LEDGER_FILE)
    undo = commands.add_parser("undo", help="Cofnij ostatni aktywny import do nowego CSV")
    undo.add_argument("--ledger", type=Path, default=LEDGER_FILE)
    undo.add_argument("--out", type=Path, required=True)
    report = commands.add_parser("report", help="Eksport historii i statystyk do CSV/XLSX")
    report.add_argument("--ledger", type=Path, default=LEDGER_FILE)
    report.add_argument("--out", type=Path, required=True, help="Nowy plik raportu .csv lub .xlsx")
    calibrate = commands.add_parser("calibrate", help="Kreator szablonu OCR: ręczne zaznaczanie pól na obrazie")
    calibrate.add_argument("--pdf", type=Path, required=True)
    calibrate.add_argument("--out", type=Path, required=True, help="Plik szablonu JSON")
    calibrate.add_argument("--rows", type=int, required=True, help="Liczba wierszy tabeli na stronie")
    calibrate.add_argument("--row-step", type=int, required=True, help="Odstęp pionowy między wierszami w pikselach PDF przy danym DPI")
    calibrate.add_argument("--dpi", type=int, default=200)
    calibrate.add_argument("--language", default="eng", help="Język Tesseract, np. eng lub pol+eng")
    calibrate.add_argument("--poppler-bin", type=Path)
    calibrate.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            rows = check_environment(poppler_bin=args.poppler_bin, tesseract_bin=args.tesseract_bin)
            print(render_environment_report(rows))
            if args.db:
                count = inspect_inventory_csv(args.db)
                print(f"OK: magazyn {args.db.name}: {count} poprawnych nazw produktów.")
            return 0 if all(ok for ok, _ in rows) else 1
        elif args.command == "scan":
            review = scan_invoice(
                pdf_path=args.pdf,
                template_path=args.template,
                output_dir=args.output,
                poppler_bin=args.poppler_bin,
                tesseract_bin=args.tesseract_bin,
                overwrite=args.overwrite,
                all_pages=args.all_pages,
                max_pages=args.max_pages,
                omit_empty=args.omit_empty,
            )
            print(f"\nGotowe. Sprawdź i popraw dane: {review}")
            print('Dla każdego poprawnego wiersza ustaw Approved na "yes".')
        elif args.command == "calibrate":
            path = create_template(args.pdf, args.out, rows=args.rows, row_step=args.row_step,
                                   dpi=args.dpi, language=args.language, poppler_bin=args.poppler_bin,
                                   overwrite=args.overwrite)
            print(f"\nZapisano szablon: {path}. Wybierz go w GUI lub podaj --template podczas skanowania.")
        elif args.command == "apply":
            if args.overwrite:
                raise ValueError("Audytowany import nie pozwala nadpisywać eksportów. Wybierz nową nazwę --out.")
            result, count, import_id = commit_review(
                review_path=args.review, database_path=args.db,
                output_path=args.out, ledger_path=args.ledger, source_pdf=args.pdf,
            )
            print(f"\nImport #{import_id}: zaktualizowano {count} pozycji. Nowy CSV: {result}")
            print("Przy następnym imporcie użyj tego pliku jako --db (ciągłość historii).")
        elif args.command == "history":
            info = statistics(args.ledger)
            print(f"Aktywne: {info['active']} | Cofnięte: {info['undone']} | Pozycje: {info['lines']} | Wartość: {info['income']} PLN")
            for row in list_imports(args.ledger):
                print(f"#{row['id']} | {row['status']} | {row['created_at']} | {row['source_name']} | {row['lines']} pozycji | {row['total_income']} PLN")
        elif args.command == "undo":
            path, import_id = undo_last(args.ledger, args.out)
            print(f"\nCofnięto import #{import_id}. Stan sprzed importu zapisano: {path}")
        elif args.command == "report":
            path = export_report(args.ledger, args.out)
            print(f"Zapisano raport: {path}")
    except (ValueError, FileNotFoundError, FileExistsError, OSError, RuntimeError) as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
