"""InvoiceFlow OCR v0.6 — OCR, audyt, diagnostyka i raporty w GUI."""

from __future__ import annotations

import os
import sys
import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from invoiceflow.history import commit_review, undo_last, statistics
from invoiceflow.diagnostics import inspect_inventory_csv
from invoiceflow.environment import check_environment, render_environment_report
from invoiceflow.dashboard_gui import AnalyticsWindow
from invoiceflow.review import get_review_stats, load_review, save_review
from invoiceflow.scanner import load_quality_report, scan_invoice

# In a PyInstaller bundle resources are read next to the packaged code,
# but local data must live next to the executable (not in an ephemeral temp dir).
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULT_TEMPLATE = RESOURCE_DIR / "templates" / "invoice1.json"
OUTPUT_DIR = ROOT / "output"
LEDGER_FILE = ROOT / "data" / "invoiceflow.sqlite3"

BG = "#0B1120"
PANEL = "#141E30"
PANEL_ALT = "#1D2A41"
BLUE = "#467FFF"
WHITE = "#EFF4FF"
MUTED = "#9CAEC9"
GREEN = "#2FB98A"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class InvoiceFlowApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("InvoiceFlow OCR | v0.6")
        self.geometry("1360x860")
        self.minsize(1100, 690)
        self.configure(fg_color=BG)

        self.pdf_path = ctk.StringVar(value=str(ROOT / "Invoice1.pdf") if (ROOT / "Invoice1.pdf").exists() else "")
        self.db_path = ctk.StringVar(value=str(ROOT / "FinancialSheet.csv") if (ROOT / "FinancialSheet.csv").exists() else "")
        self.template_path = ctk.StringVar(value=str(DEFAULT_TEMPLATE))
        self.poppler_path = ctk.StringVar()
        self.tesseract_path = ctk.StringVar()
        self.all_pages = ctk.BooleanVar(value=False)
        self.omit_empty = ctk.BooleanVar(value=False)
        self._preview_pages: list[Path] = []
        self.show_layout = ctk.BooleanVar(value=False)
        self._events = queue.Queue()
        self._busy = False
        self.review_path: Path | None = None
        self._original_rows: list[dict[str, str]] = []
        self.row_controls: list[dict] = []
        self._preview_image: ctk.CTkImage | None = None
        self._preview_path: Path | None = None
        self._history_window = None

        self._build_ui()
        self.after(120, self._poll_events)

    @staticmethod
    def _heading(parent, title, subtitle=None):
        ctk.CTkLabel(parent, text=title, font=("Segoe UI", 18, "bold"), text_color=WHITE, anchor="w").pack(fill="x")
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, font=("Segoe UI", 12), text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=(1, 7))

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=BG, height=75, corner_radius=0)
        header.pack(fill="x", padx=24, pady=(15, 4))
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="◈  InvoiceFlow", font=("Segoe UI", 30, "bold"), text_color=WHITE).pack(side="left")
        ctk.CTkLabel(header, text="OCR  /  REVIEW  /  EXPORT", font=("Segoe UI", 11, "bold"), text_color=MUTED).pack(side="left", padx=24, pady=(14, 0))
        ctk.CTkLabel(header, text="v0.6  •  Desktop", font=("Segoe UI", 12), text_color=MUTED).pack(side="right")
        self.history_btn = ctk.CTkButton(
            header, text="Dashboard i historia", width=190, height=34,
            fg_color=PANEL_ALT, hover_color="#34445F", command=self._open_history,
        )
        self.history_btn.pack(side="right", padx=14)
        self.diagnostics_btn = ctk.CTkButton(
            header, text="Diagnostyka OCR", width=144, height=34,
            fg_color=PANEL_ALT, hover_color="#34445F", command=self._check_environment,
        )
        self.diagnostics_btn.pack(side="right", padx=(4, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        body.grid_columnconfigure(0, weight=2, minsize=375)
        body.grid_columnconfigure(1, weight=3, minsize=670)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self._build_left(left)
        self._build_right(right)

        footer = ctk.CTkFrame(self, fg_color=BG, height=40, corner_radius=0)
        footer.pack(fill="x", padx=28, pady=(0, 10))
        self.status = ctk.CTkLabel(footer, text="Gotowe. Wybierz fakturę i bazę CSV.", text_color=MUTED, anchor="w", font=("Segoe UI", 12))
        self.status.pack(side="left")
        self.progress = ctk.CTkProgressBar(footer, width=130, progress_color=BLUE, mode="indeterminate")
        self.progress.pack(side="right", padx=(12, 0))
        self.progress.set(0)

    def _file_field(self, parent, label, variable, command):
        ctk.CTkLabel(parent, text=label, text_color=MUTED, font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x", pady=(8, 3))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(row, textvariable=variable, fg_color=BG, border_color="#34445F", text_color=WHITE, height=34).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="Wybierz", width=78, height=34, fg_color=PANEL_ALT, hover_color="#34445F", command=command).pack(side="right")

    def _build_left(self, parent):
        settings = ctk.CTkFrame(parent, fg_color="transparent")
        settings.pack(fill="x", padx=18, pady=(17, 9))
        self._heading(settings, "01  Dokument", "Wczytaj PDF i wskaż magazyn (CSV).")
        self._file_field(settings, "FAKTURA PDF", self.pdf_path, self._choose_pdf)
        self._file_field(settings, "BAZA PRODUKTÓW CSV", self.db_path, self._choose_db)
        self.db_check_btn = ctk.CTkButton(
            settings, text="Sprawdź poprawność bazy CSV", width=220, height=28,
            fg_color="transparent", text_color="#A4C2FF", hover_color=PANEL_ALT,
            anchor="w", command=lambda: self._check_db(show_dialog=True),
        )
        self.db_check_btn.pack(anchor="w", pady=(5, 0))
        ctk.CTkCheckBox(settings, text="Skanuj wszystkie strony PDF (ten sam szablon)", variable=self.all_pages,
                        text_color=MUTED, checkbox_width=18, checkbox_height=18).pack(anchor="w", pady=(12, 0))
        ctk.CTkCheckBox(settings, text="Pomiń całkowicie puste wiersze", variable=self.omit_empty,
                        text_color=MUTED, checkbox_width=18, checkbox_height=18).pack(anchor="w", pady=(7, 0))

        options = ctk.CTkFrame(settings, fg_color="transparent")
        options.pack(fill="x", pady=(8, 0))
        self.advanced_open = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options, text="Zaawansowane ścieżki", variable=self.advanced_open, command=self._toggle_advanced, text_color=MUTED, checkbox_height=18, checkbox_width=18).pack(anchor="w")
        self.advanced_panel = ctk.CTkFrame(settings, fg_color="transparent")
        self._file_field(self.advanced_panel, "SZABLON OCR JSON", self.template_path, self._choose_template)
        self._file_field(self.advanced_panel, "FOLDER POPPLER (opcjonalnie)", self.poppler_path, self._choose_poppler)
        self._file_field(self.advanced_panel, "TESSERACT.EXE (opcjonalnie)", self.tesseract_path, self._choose_tesseract)

        action_row = ctk.CTkFrame(settings, fg_color="transparent")
        action_row.pack(fill="x", pady=(12, 0))
        self.scan_btn = ctk.CTkButton(action_row, text="Skanuj PDF", height=40, fg_color=BLUE, hover_color="#3466D8", command=self._scan)
        self.scan_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.open_btn = ctk.CTkButton(action_row, text="Otwórz review.csv", height=40, fg_color=PANEL_ALT, hover_color="#34445F", command=self._choose_review)
        self.open_btn.pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(parent, fg_color="#2A3952", height=1).pack(fill="x", padx=18, pady=(10, 14))
        preview = ctk.CTkFrame(parent, fg_color="transparent")
        preview.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self._heading(preview, "02  Podgląd faktury", "Przełączaj strony po skanowaniu dokumentu.")
        pager = ctk.CTkFrame(preview, fg_color="transparent")
        pager.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(pager, text="Strona PDF:", text_color=MUTED).pack(side="left")
        self.page_choice = ctk.CTkOptionMenu(pager, values=["1"], width=90, state="disabled",
                                             fg_color=PANEL_ALT, button_color="#34445F",
                                             command=self._select_preview_page)
        self.page_choice.pack(side="left", padx=(8, 0))
        ctk.CTkCheckBox(pager, text="Pokaż ramki OCR", variable=self.show_layout,
                        command=self._update_preview, text_color=MUTED,
                        checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))
        self.image_label = ctk.CTkLabel(preview, text="Brak podglądu\n\nPo skanowaniu zobaczysz tutaj fakturę.", font=("Segoe UI", 13), text_color=MUTED, fg_color=BG, corner_radius=12)
        self.image_label.pack(fill="both", expand=True, pady=(4, 9))
        self.image_btn = ctk.CTkButton(preview, text="Otwórz obraz w pełnej rozdzielczości", fg_color=PANEL_ALT, hover_color="#34445F", height=34, state="disabled", command=self._open_preview)
        self.image_btn.pack(fill="x")

    def _build_right(self, parent):
        titlebar = ctk.CTkFrame(parent, fg_color="transparent")
        titlebar.pack(fill="x", padx=18, pady=(17, 5))
        self._heading(titlebar, "03  Weryfikacja OCR", "Sprawdź każdą nazwę, ilość i kwotę przed zatwierdzeniem.")
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(0, 8))
        self.counter = ctk.CTkLabel(top, text="0 / 0 zatwierdzonych", font=("Segoe UI", 13, "bold"), text_color=GREEN, anchor="w")
        self.counter.pack(side="left")
        self.quality_label = ctk.CTkLabel(top, text="", font=("Segoe UI", 11), text_color="#F5BC76")
        self.quality_label.pack(side="left", padx=(15, 0))
        self.review_file_label = ctk.CTkLabel(top, text="Nie wybrano pliku review.csv", font=("Segoe UI", 11), text_color=MUTED, anchor="e")
        self.review_file_label.pack(side="right")

        table_header = ctk.CTkFrame(parent, fg_color=PANEL_ALT, corner_radius=7, height=34)
        table_header.pack(fill="x", padx=18)
        for title, width in (("Lp.", 41), ("Produkt", 270), ("Ilość", 75), ("Kwota", 96), ("OK", 50)):
            ctk.CTkLabel(table_header, text=title, width=width, text_color=MUTED, font=("Segoe UI", 11, "bold")).pack(side="left", padx=(4, 0))

        self.table = ctk.CTkScrollableFrame(parent, fg_color=BG, corner_radius=10, scrollbar_button_color="#34445F")
        self.table.pack(fill="both", expand=True, padx=18, pady=(7, 12))
        self._table_widgets = []
        initial_hint = ctk.CTkLabel(self.table, text="Po skanowaniu pojawią się tutaj odczytane wiersze.", text_color=MUTED)
        initial_hint.pack(pady=25)
        self._table_widgets.append(initial_hint)

        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.pack(fill="x", padx=18, pady=(0, 17))
        self.sale_confirm = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(panel,
            text="Potwierdzam: faktura sprzedaży; kwoty to wartości całych pozycji.",
            variable=self.sale_confirm, text_color=MUTED, font=("Segoe UI", 12),
            checkbox_width=18, checkbox_height=18,
        ).pack(fill="x", pady=(0, 10))
        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.pack(fill="x")
        self.save_btn = ctk.CTkButton(controls, text="Zapisz poprawki", height=42, fg_color=PANEL_ALT, hover_color="#34445F", command=self._save, state="disabled")
        self.save_btn.pack(side="left", fill="x", expand=True, padx=(0, 7))
        self.apply_btn = ctk.CTkButton(controls, text="Zatwierdź i eksportuj CSV", height=42, fg_color=GREEN, hover_color="#23936F", text_color="#081421", command=self._apply, state="disabled")
        self.apply_btn.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(panel, text="Oryginalna baza CSV nie jest nadpisywana. Brak automatycznego zatwierdzania OCR.", font=("Segoe UI", 11), text_color=MUTED, anchor="w").pack(fill="x", pady=(8, 0))

    def _toggle_advanced(self):
        if self.advanced_open.get():
            self.advanced_panel.pack(fill="x", pady=(4, 0))
        else:
            self.advanced_panel.pack_forget()

    def _choose_pdf(self):
        path = filedialog.askopenfilename(title="Wybierz fakturę PDF", filetypes=[("Faktury PDF", "*.pdf")])
        if path:
            self.pdf_path.set(path)

    def _choose_db(self):
        path = filedialog.askopenfilename(title="Wybierz bazę produktów CSV", filetypes=[("Pliki CSV", "*.csv")])
        if path:
            self.db_path.set(path)
            self._check_db(show_dialog=False)

    def _check_db(self, *, show_dialog: bool = False) -> bool:
        """Read-only checks, including exact CSV rows when names collide."""
        try:
            raw = self.db_path.get().strip()
            if not raw:
                raise ValueError("Wybierz plik bazy produktów CSV.")
            count = inspect_inventory_csv(Path(raw))
        except (ValueError, OSError) as exc:
            self._set_status(f"Baza CSV wymaga poprawy: {exc}", is_error=True)
            if show_dialog:
                messagebox.showerror("Kontrola bazy CSV", str(exc))
            return False
        self._set_status(f"Baza {Path(raw).name}: {count} produktów — nazwy są poprawne.")
        if show_dialog:
            messagebox.showinfo("Kontrola bazy CSV", f"Nazwy {count} produktów są poprawne.\n\nPrzed eksportem program dodatkowo sprawdzi stany, kwoty i historię importów.")
        return True

    def _check_environment(self):
        poppler = self.poppler_path.get().strip()
        tesseract = self.tesseract_path.get().strip()
        rows = check_environment(
            poppler_bin=Path(poppler) if poppler else None,
            tesseract_bin=Path(tesseract) if tesseract else None,
        )
        text = render_environment_report(rows)
        if all(ok for ok, _ in rows):
            messagebox.showinfo("Diagnostyka OCR", text)
        else:
            messagebox.showwarning("Diagnostyka OCR — brakuje narzędzi", text + "\n\nŚcieżki możesz ustawić w sekcji Zaawansowane ścieżki.")

    def _choose_template(self):
        path = filedialog.askopenfilename(title="Szablon OCR", filetypes=[("Pliki JSON", "*.json")])
        if path:
            self.template_path.set(path)

    def _choose_poppler(self):
        path = filedialog.askdirectory(title="Folder zawierający pdfinfo.exe")
        if path:
            self.poppler_path.set(path)

    def _choose_tesseract(self):
        path = filedialog.askopenfilename(title="Wybierz tesseract.exe", filetypes=[("Program Tesseract", "*.exe")])
        if path:
            self.tesseract_path.set(path)

    def _choose_review(self):
        if not self._confirm_discard_changes():
            return
        path = filedialog.askopenfilename(title="Otwórz review.csv", initialdir=str(OUTPUT_DIR), filetypes=[("Pliki CSV", "*.csv")])
        if path:
            self._load_review(Path(path))

    def _set_status(self, message, is_error=False):
        self.status.configure(text=message, text_color="#FF9D9D" if is_error else MUTED)

    def _set_busy(self, value, text=""):
        self._busy = value
        for button in (self.scan_btn, self.open_btn, self.save_btn, self.apply_btn, self.history_btn, self.db_check_btn, self.diagnostics_btn):
            button.configure(state="disabled" if value else "normal")
        if not value and self.review_path is None:
            self.save_btn.configure(state="disabled")
            self.apply_btn.configure(state="disabled")
        if value:
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.set(0)
        if text:
            self._set_status(text)

    def _run_worker(self, kind, func, **kwargs):
        self._set_busy(True, "Przetwarzanie… możesz nadal korzystać z podglądu.")

        def work():
            try:
                value = func(**kwargs)
                self._events.put((kind, value, None))
            except Exception as error:
                self._events.put((kind, None, error))

        threading.Thread(target=work, daemon=True).start()

    def _poll_events(self):
        try:
            while True:
                kind, result, error = self._events.get_nowait()
                self._set_busy(False)
                if error is not None:
                    self._set_status(f"Błąd: {error}", is_error=True)
                    messagebox.showerror("InvoiceFlow — błąd", str(error))
                elif kind == "scan":
                    self._load_review(Path(result))
                    self._set_status("Skan ukończony. Sprawdź każdą pozycję i zatwierdź ręcznie.")
                elif kind == "apply":
                    path, count, import_id = result
                    self.db_path.set(str(path))
                    self._refresh_history()
                    self._set_status(f"Import #{import_id}: {count} pozycji. Nowa aktualna baza: {path}")
                    messagebox.showinfo(
                        "Import zapisany w historii",
                        f"Import #{import_id}: {count} pozycji.\n\nNowy plik: {path}\n"
                        "Ustawiono go jako aktualną bazę do następnego importu.\n"
                        "Oryginalny CSV nie został nadpisany.",
                    )
                elif kind == "undo":
                    path, import_id = result
                    self.db_path.set(str(path))
                    self._refresh_history()
                    self._set_status(f"Cofnięto import #{import_id}. Przywrócony CSV: {path}")
                    messagebox.showinfo("Cofnięcie zakończone", f"Cofnięto import #{import_id}.\nNowa aktualna baza: {path}")
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _scan(self):
        if self._busy or not self._confirm_discard_changes():
            return
        pdf = Path(self.pdf_path.get().strip())
        template = Path(self.template_path.get().strip())
        if not pdf.is_file():
            messagebox.showerror("Brak PDF", "Wybierz istniejący plik faktury PDF.")
            return
        if not template.is_file():
            messagebox.showerror("Brak szablonu", "Wybierz istniejący szablon JSON.")
            return
        # Dla istniejących skanów wymagana jest świadoma zgoda na ponowny OCR.
        # W scanner.py nazwy innych niż alfanumeryczne znaków są normalizowane.
        import re
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pdf.stem).strip("_") or "invoice"
        review = OUTPUT_DIR / safe_name / "review.csv"
        overwrite = False
        if review.exists():
            if not messagebox.askyesno("Istniejący skan", "Dla tej faktury istnieje już review.csv.\n\nPonowny skan zastąpi dotychczasowe poprawki i zatwierdzenia. Kontynuować?"):
                self._load_review(review)
                return
            overwrite = True
        self._run_worker(
            "scan", scan_invoice, pdf_path=pdf, template_path=template,
            output_dir=OUTPUT_DIR,
            poppler_bin=Path(self.poppler_path.get().strip()) if self.poppler_path.get().strip() else None,
            tesseract_bin=Path(self.tesseract_path.get().strip()) if self.tesseract_path.get().strip() else None,
            overwrite=overwrite,
            all_pages=self.all_pages.get(),
            omit_empty=self.omit_empty.get(),
        )

    def _load_review(self, path):
        try:
            rows = load_review(path)
        except (ValueError, OSError) as error:
            messagebox.showerror("Błąd wczytywania review.csv", str(error))
            return
        self.review_path = path
        self._original_rows = rows
        quality = load_quality_report(path)
        issue_rows = {str(warning["row"]) for warning in quality.get("warnings", []) if "row" in warning} if quality else set()
        count_issues = len(quality.get("warnings", [])) if quality else 0
        self.quality_label.configure(text=f"⚠ {count_issues} uwag OCR" if count_issues else "Bez zgłoszonych uwag OCR")
        self.sale_confirm.set(False)
        self.review_file_label.configure(text=path.name + " · " + path.parent.name)
        for widget in self._table_widgets:
            widget.destroy()
        self._table_widgets.clear()
        self.row_controls = []
        for i, row in enumerate(rows):
            container = ctk.CTkFrame(self.table, fg_color="#4A3039" if str(row["Row"]) in issue_rows else (PANEL if i % 2 == 0 else PANEL_ALT), corner_radius=6, height=45)
            container.pack(fill="x", pady=2)
            self._table_widgets.append(container)
            number = ctk.CTkLabel(container, text=row["Row"], width=41, text_color=MUTED, font=("Segoe UI", 11))
            number.pack(side="left", padx=(4, 0))
            entries = {}
            for field, width in (("Item", 270), ("Quantity", 75), ("Income", 96)):
                entry = ctk.CTkEntry(container, width=width, height=32, border_width=1,
                                     border_color="#30405C", fg_color=BG, text_color=WHITE,
                                     font=("Segoe UI", 12))
                entry.insert(0, row[field])
                entry.pack(side="left", padx=(4, 0), pady=4)
                entry.bind("<KeyRelease>", lambda _event: self._update_counter())
                entries[field] = entry
            approved = ctk.BooleanVar(value=row["Approved"].strip().casefold() == "yes")
            ctk.CTkCheckBox(container, text="", variable=approved, width=50, checkbox_width=20, checkbox_height=20, command=self._update_counter).pack(side="left", padx=(12, 2))
            self.row_controls.append({"Row": row["Row"], "entries": entries, "Approved": approved})

        self.save_btn.configure(state="normal")
        self.apply_btn.configure(state="normal")
        self._update_counter()
        self._load_previews(path.parent)
        self._set_status(f"Wczytano review.csv: {path}")

    def _current_rows(self):
        return [
            {
                "Row": entry["Row"],
                "Item": entry["entries"]["Item"].get(),
                "Quantity": entry["entries"]["Quantity"].get(),
                "Income": entry["entries"]["Income"].get(),
                "Approved": "yes" if entry["Approved"].get() else "no",
            }
            for entry in self.row_controls
        ]

    def _update_counter(self):
        active, approved = get_review_stats(self._current_rows())
        dirty = self.review_path is not None and self._current_rows() != self._original_rows
        self.counter.configure(text=f"{approved} / {active} zatwierdzonych" + ("  •  niezapisane zmiany" if dirty else ""))

    def _confirm_discard_changes(self):
        if self.review_path and self._current_rows() != self._original_rows:
            return messagebox.askyesno("Niezapisane zmiany", "Masz niezapisane zmiany w tabeli. Odrzucić je?")
        return True

    def _save(self):
        if not self.review_path:
            return False
        try:
            rows = self._current_rows()
            save_review(self.review_path, rows)
            self._original_rows = rows
            self._update_counter()
            self._set_status(f"Zapisano poprawki: {self.review_path}")
            return True
        except (ValueError, OSError) as error:
            messagebox.showerror("Nie udało się zapisać", str(error))
            return False

    def _apply(self):
        if self._busy or not self.review_path:
            return
        db = Path(self.db_path.get().strip())
        if not self._check_db(show_dialog=True):
            return
        if not self.sale_confirm.get():
            messagebox.showwarning("Potwierdź rodzaj dokumentu", "Zaznacz potwierdzenie, że faktura dotyczy sprzedaży, a Income jest sumą pozycji.")
            return
        active, approved = get_review_stats(self._current_rows())
        if active == 0 or approved != active:
            messagebox.showwarning("Brak zatwierdzeń", f"Wymagane jest sprawdzenie każdej niepustej pozycji ({approved}/{active} zatwierdzonych).")
            return
        if not self._save():
            return
        target = filedialog.asksaveasfilename(
            title="Zapisz zaktualizowaną bazę (osobna kopia)",
            initialdir=str(OUTPUT_DIR), initialfile="inventory_updated.csv",
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
        )
        if not target:
            return
        output_path = Path(target)
        if output_path.resolve() in (db.resolve(), self.review_path.resolve()):
            messagebox.showerror("Ochrona plików", "Nie wolno nadpisać oryginalnej bazy ani review.csv plikiem wynikowym.")
            return
        if output_path.exists():
            messagebox.showerror("Ochrona historii", "Plik eksportu już istnieje. Wybierz NOWĄ nazwę — importy historyczne są niezmienne.")
            return
        if not messagebox.askyesno(
            "Potwierdź audytowany import",
            "Czy sprawdziłeś pozycje względem oryginalnej faktury?\n\n"
            "Program utworzy NOWY CSV, zapisze historię SQLite i zablokuje ponowny import tego samego PDF.\n"
            "Kolejny import musi bazować na aktualnie wyeksportowanym CSV.",
        ):
            return
        pdf = Path(self.pdf_path.get().strip()) if self.pdf_path.get().strip() else None
        if pdf is not None and not pdf.is_file():
            messagebox.showerror("Błąd PDF", "Wybrana faktura PDF nie istnieje. Wskaż poprawny plik albo wyczyść pole PDF.")
            return
        self._run_worker(
            "apply", commit_review,
            review_path=self.review_path, database_path=db, output_path=output_path,
            ledger_path=LEDGER_FILE, source_pdf=pdf,
        )

    def _open_history(self):
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.lift()
            self._refresh_history()
            return
        self._history_window = AnalyticsWindow(self, LEDGER_FILE, self._undo_latest)

    def _refresh_history(self):
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.refresh()

    def _undo_latest(self):
        if self._busy:
            return
        stats = statistics(LEDGER_FILE)
        if not stats['active']:
            messagebox.showinfo("Brak importów", "Brak aktywnych importów do cofnięcia.")
            return
        if not messagebox.askyesno("Cofnij ostatni import", "Przywrócić stan sprzed OSTATNIEGO importu?\n"
                                  "Zostanie utworzony osobny CSV. Historia pozostanie zachowana."):
            return
        target = filedialog.asksaveasfilename(title="Zapisz przywrócony magazyn", parent=self._history_window,
                                              initialdir=str(OUTPUT_DIR), initialfile="inventory_restored.csv",
                                              defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not target:
            return
        path = Path(target)
        if path.exists():
            messagebox.showerror("Istniejący plik", "Wybierz nową nazwę pliku przywracania.")
            return
        self._run_worker("undo", undo_last, ledger_path=LEDGER_FILE, output_path=path)

    def _load_previews(self, folder: Path):
        first = folder / "invoice.jpg"
        self._preview_pages = ([first] if first.is_file() else []) + sorted(folder.glob("invoice_p[0-9][0-9][0-9].jpg"))
        if self._preview_pages:
            self.page_choice.configure(values=[str(i) for i in range(1, len(self._preview_pages) + 1)],
                                       state="normal" if len(self._preview_pages) > 1 else "disabled")
            self.page_choice.set("1")
            self._update_preview()
        else:
            self.page_choice.configure(values=["1"], state="disabled")
            self._load_preview(first)

    def _select_preview_page(self, selected: str):
        try:
            idx = int(selected) - 1
            if 0 <= idx < len(self._preview_pages):
                self._update_preview()
        except (ValueError, TypeError):
            return

    def _update_preview(self):
        if not self._preview_pages:
            return
        try:
            idx = int(self.page_choice.get()) - 1
        except (ValueError, TypeError):
            idx = 0
        if not 0 <= idx < len(self._preview_pages):
            return
        original = self._preview_pages[idx]
        if self.show_layout.get():
            layout_name = "layout.jpg" if idx == 0 else f"layout_p{idx + 1:03d}.jpg"
            layout_file = original.parent / layout_name
            if layout_file.is_file():
                self._load_preview(layout_file)
                return
        self._load_preview(original)

    def _load_preview(self, path):
        self._preview_path = path if path.is_file() else None
        if not self._preview_path:
            self.image_label.configure(image=None, text="Podgląd niedostępny — nie znaleziono invoice.jpg")
            self.image_btn.configure(state="disabled")
            return
        try:
            with Image.open(path) as file:
                image = file.convert("RGB")
            max_width = 390
            max_height = 480
            scale = min(max_width / image.width, max_height / image.height)
            size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            self._preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
            self.image_label.configure(image=self._preview_image, text="")
            self.image_btn.configure(state="normal")
        except (OSError, ValueError) as error:
            self.image_label.configure(image=None, text=f"Błąd podglądu: {error}")
            self.image_btn.configure(state="disabled")

    def _open_preview(self):
        if not self._preview_path:
            return
        if os.name == "nt":
            os.startfile(str(self._preview_path))  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("Obraz", f"Otwórz plik w przeglądarce zdjęć:\n{self._preview_path}")


def main():
    InvoiceFlowApp().mainloop()


if __name__ == "__main__":
    main()
