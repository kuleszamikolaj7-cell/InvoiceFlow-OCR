"""InvoiceFlow v0.6 read-only dashboard, searches and report exports."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .analytics import dashboard_data, filter_imports, filter_products
from .history import statistics
from .inventory import parse_number
from .reporting import export_report

BG = '#0B1120'
PANEL = '#141E30'
PANEL_ALT = '#1D2A41'
BLUE = '#467FFF'
WHITE = '#EFF4FF'
MUTED = '#9CAEC9'
GREEN = '#2FB98A'
AMBER = '#F5BC76'


class AnalyticsWindow(ctk.CTkToplevel):
    """Displays data from one SQLite ledger. Never modifies the inventory."""

    def __init__(self, parent, ledger_path: Path, on_undo):
        super().__init__(parent)
        self.ledger_path = Path(ledger_path)
        self.on_undo = on_undo
        self.title('InvoiceFlow | Dashboard & Analytics v0.6')
        self.geometry('1110x790')
        self.minsize(930, 630)
        self.configure(fg_color=BG)
        self.transient(parent)

        heading = ctk.CTkFrame(self, fg_color='transparent')
        heading.pack(fill='x', padx=22, pady=(19, 13))
        ctk.CTkLabel(heading, text='Dashboard & Analytics', font=('Segoe UI', 25, 'bold'), text_color=WHITE).pack(side='left')
        ctk.CTkLabel(heading, text='SQLite  /  CSV  /  EXCEL', text_color=MUTED).pack(side='left', padx=20)
        ctk.CTkButton(heading, text='Raport Excel', width=120, fg_color=GREEN, text_color=BG,
                      command=lambda: self._export('.xlsx')).pack(side='right', padx=(6, 0))
        ctk.CTkButton(heading, text='Raport CSV', width=115, fg_color=PANEL_ALT,
                      command=lambda: self._export('.csv')).pack(side='right', padx=(6, 0))
        ctk.CTkButton(heading, text='Odśwież', width=105, fg_color=PANEL_ALT,
                      command=self.refresh).pack(side='right', padx=(6, 0))

        self.tabs = ctk.CTkTabview(self, fg_color=PANEL, segmented_button_fg_color=PANEL_ALT,
                                   segmented_button_selected_color=BLUE)
        self.tabs.pack(fill='both', expand=True, padx=20, pady=(0, 14))
        self._build_dashboard(self.tabs.add('Dashboard'))
        self._build_history(self.tabs.add('Historia importów'))
        self._build_products(self.tabs.add('Magazyn'))
        self.refresh()

    def _label(self, parent, text, size=12, color=MUTED, bold=False, **kwargs):
        return ctk.CTkLabel(parent, text=str(text), text_color=color,
                            font=('Segoe UI', size, 'bold' if bold else 'normal'), **kwargs)

    def _build_dashboard(self, parent):
        self.cards = ctk.CTkFrame(parent, fg_color='transparent')
        self.cards.pack(fill='x', padx=10, pady=(13, 10))
        self.cards.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        self.kpis = {}
        specs = [
            ('active', 'Importy aktywne'), ('income', 'Wartość sprzedaży'),
            ('lines', 'Pozycje'), ('products', 'Produkty'), ('low_stock', 'Niski stan ≤ 5'),
        ]
        for col, (key, label) in enumerate(specs):
            tile = ctk.CTkFrame(self.cards, fg_color=PANEL_ALT, corner_radius=10)
            tile.grid(row=0, column=col, sticky='nsew', padx=4)
            self._label(tile, label, size=11).pack(anchor='w', padx=12, pady=(10, 0))
            value = self._label(tile, '—', size=23, color=WHITE, bold=True)
            value.pack(anchor='w', padx=12, pady=(3, 12))
            self.kpis[key] = value

        charts = ctk.CTkFrame(parent, fg_color='transparent')
        charts.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        charts.grid_columnconfigure((0, 1), weight=1)
        charts.grid_rowconfigure(0, weight=1)
        monthly_panel = ctk.CTkFrame(charts, fg_color=PANEL_ALT, corner_radius=10)
        monthly_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 7))
        self._label(monthly_panel, 'Wartość sprzedaży / miesiąc (UTC)', size=15, color=WHITE, bold=True).pack(anchor='w', padx=14, pady=(13, 0))
        self.monthly_frame = ctk.CTkScrollableFrame(monthly_panel, fg_color=PANEL_ALT)
        self.monthly_frame.pack(fill='both', expand=True, padx=8, pady=(8, 12))
        top_panel = ctk.CTkFrame(charts, fg_color=PANEL_ALT, corner_radius=10)
        top_panel.grid(row=0, column=1, sticky='nsew', padx=(7, 0))
        self._label(top_panel, 'Najlepiej sprzedające się produkty', size=15, color=WHITE, bold=True).pack(anchor='w', padx=14, pady=(13, 0))
        self.top_frame = ctk.CTkScrollableFrame(top_panel, fg_color=PANEL_ALT)
        self.top_frame.pack(fill='both', expand=True, padx=8, pady=(8, 12))
        self._label(parent, 'Statystyki dotyczą zatwierdzonych i niecofniętych importów. Kwoty są wartościami pozycji, nie zyskiem.',
                    size=11).pack(anchor='w', padx=16, pady=(0, 6))

    def _build_history(self, parent):
        tools = ctk.CTkFrame(parent, fg_color='transparent')
        tools.pack(fill='x', padx=12, pady=(10, 7))
        self.query_imports = ctk.StringVar()
        self.filter_status = ctk.StringVar(value='Wszystkie')
        self.date_from = ctk.StringVar()
        self.date_to = ctk.StringVar()
        entry = ctk.CTkEntry(tools, width=210, placeholder_text='Szukaj po nazwie PDF', textvariable=self.query_imports)
        entry.pack(side='left', padx=(0, 8))
        entry.bind('<KeyRelease>', lambda _event: self._refresh_imports())
        ctk.CTkOptionMenu(tools, width=110, variable=self.filter_status,
                          values=['Wszystkie', 'Aktywne', 'Cofnięte'],
                          command=lambda _choice: self._refresh_imports()).pack(side='left', padx=(0, 8))
        ctk.CTkEntry(tools, width=110, placeholder_text='Od RRRR-MM-DD', textvariable=self.date_from).pack(side='left', padx=(0, 7))
        ctk.CTkEntry(tools, width=110, placeholder_text='Do RRRR-MM-DD', textvariable=self.date_to).pack(side='left', padx=(0, 7))
        ctk.CTkButton(tools, width=88, text='Filtruj', fg_color=BLUE, command=self._refresh_imports).pack(side='left')
        self.history_count = self._label(parent, '', size=11)
        self.history_count.pack(anchor='w', padx=17, pady=(0, 6))
        self.history_scroll = ctk.CTkScrollableFrame(parent, fg_color=BG, corner_radius=10)
        self.history_scroll.pack(fill='both', expand=True, padx=14, pady=(0, 8))
        footer = ctk.CTkFrame(parent, fg_color='transparent')
        footer.pack(fill='x', padx=12, pady=(2, 10))
        self.undo_button = ctk.CTkButton(footer, text='Cofnij ostatni import', width=195,
                                         fg_color='#B85A50', hover_color='#A14840', command=self.on_undo)
        self.undo_button.pack(side='right')
        self._label(footer, 'Cofnięcie utworzy osobny CSV; lista historii pozostanie zachowana.', size=11).pack(side='left')

    def _build_products(self, parent):
        tools = ctk.CTkFrame(parent, fg_color='transparent')
        tools.pack(fill='x', padx=12, pady=(10, 10))
        self.query_products = ctk.StringVar()
        self.low_only = ctk.BooleanVar(value=False)
        entry = ctk.CTkEntry(tools, width=320, placeholder_text='Szukaj produktu...', textvariable=self.query_products)
        entry.pack(side='left', padx=(0, 12))
        entry.bind('<KeyRelease>', lambda _event: self._refresh_products())
        ctk.CTkCheckBox(tools, variable=self.low_only, text='Tylko niski stan (≤ 5)', command=self._refresh_products,
                        text_color=MUTED).pack(side='left')
        self.product_count = self._label(parent, '', size=11)
        self.product_count.pack(anchor='w', padx=17, pady=(0, 6))
        self.product_scroll = ctk.CTkScrollableFrame(parent, fg_color=BG, corner_radius=10)
        self.product_scroll.pack(fill='both', expand=True, padx=14, pady=(0, 12))

    @staticmethod
    def _clear(frame):
        for child in frame.winfo_children():
            child.destroy()

    def _bar_rows(self, frame, rows, key, label, accent):
        self._clear(frame)
        if not rows:
            self._label(frame, 'Brak danych do wykresu.').pack(pady=24)
            return
        maximum = max((float(row[key]) for row in rows), default=0.0)
        for record in rows:
            value = float(record[key])
            line = ctk.CTkFrame(frame, fg_color='transparent')
            line.pack(fill='x', pady=5, padx=3)
            self._label(line, str(record[label])[:34], size=12, color=WHITE, bold=True, anchor='w').pack(fill='x')
            bar_line = ctk.CTkFrame(line, fg_color='transparent')
            bar_line.pack(fill='x', pady=(3, 0))
            ratio = value / maximum if maximum else 0
            # Grid gives a stable proportional bar without matplotlib.
            bar_line.grid_columnconfigure(0, weight=max(1, int(ratio * 100)))
            bar_line.grid_columnconfigure(1, weight=max(1, 100 - int(ratio * 100)))
            ctk.CTkFrame(bar_line, fg_color=accent, corner_radius=3, width=1, height=10).grid(row=0, column=0, sticky='ew')
            ctk.CTkFrame(bar_line, fg_color='#30405C', corner_radius=3, width=1, height=10).grid(row=0, column=1, sticky='ew')
            self._label(line, f'{value:,.2f}', size=11).pack(anchor='e')

    def _refresh_imports(self):
        status_map = {'Wszystkie': 'wszystkie', 'Aktywne': 'applied', 'Cofnięte': 'undone'}
        try:
            rows = filter_imports(self.ledger_path, self.query_imports.get(),
                                  status_map[self.filter_status.get()], self.date_from.get(), self.date_to.get())
        except ValueError as error:
            messagebox.showerror('Błąd filtrowania', str(error), parent=self)
            return
        self.history_count.configure(text=f'Znaleziono {len(rows)} dokumentów (maks. 500). Daty w UTC.')
        self._clear(self.history_scroll)
        for record in rows:
            line = ctk.CTkFrame(self.history_scroll, fg_color=PANEL_ALT, corner_radius=8)
            line.pack(fill='x', padx=4, pady=4)
            active = record['status'] == 'applied'
            top = (f"#{record['id']}  {record['source_name']}   •   {record['lines']} pozycji   •   "
                   f"{record['total_income']}   •   {'AKTYWNY' if active else 'COFNIĘTY'}")
            self._label(line, top, size=13, color=GREEN if active else AMBER, bold=True, anchor='w').pack(fill='x', padx=12, pady=(9, 2))
            self._label(line, f"{record['created_at']}   |   {record['output_path']}", size=11, anchor='w').pack(fill='x', padx=12, pady=(0, 9))
        if not rows:
            self._label(self.history_scroll, 'Brak dokumentów spełniających kryteria.').pack(pady=24)

    def _refresh_products(self):
        rows = filter_products(self.ledger_path, self.query_products.get(), self.low_only.get())
        self.product_count.configure(text=f'Znaleziono: {len(rows)} produktów')
        self._clear(self.product_scroll)
        for record in rows:
            line = ctk.CTkFrame(self.product_scroll, fg_color=PANEL_ALT, corner_radius=7)
            line.pack(fill='x', padx=4, pady=3)
            is_low = parse_number(record['quantity']) <= 5
            self._label(line, record['item'], size=13, color=AMBER if is_low else WHITE, bold=True,
                        anchor='w').pack(side='left', padx=12, pady=8)
            self._label(line, f"Stan: {record['quantity']}    •    Suma Income: {record['income']}",
                        color=MUTED).pack(side='right', padx=12)
        if not rows:
            self._label(self.product_scroll, 'Brak produktów spełniających kryteria.').pack(pady=24)

    def refresh(self):
        payload = dashboard_data(self.ledger_path)
        stats = payload['stats']
        for key in self.kpis:
            self.kpis[key].configure(text=str(stats[key]))
        self._bar_rows(self.monthly_frame, payload['monthly'][-12:], 'income', 'period', BLUE)
        self._bar_rows(self.top_frame, payload['top_products'], 'income', 'item', GREEN)
        self._refresh_imports()
        self._refresh_products()
        self.undo_button.configure(state='normal' if statistics(self.ledger_path)['active'] else 'disabled')

    def _export(self, extension: str):
        filetype = [('Excel', '*.xlsx')] if extension == '.xlsx' else [('CSV', '*.csv')]
        destination = filedialog.asksaveasfilename(
            parent=self, title='Zapisz raport (nowy plik)',
            initialfile='InvoiceFlow_report' + extension,
            defaultextension=extension, filetypes=filetype,
        )
        if not destination:
            return
        try:
            path = export_report(self.ledger_path, Path(destination))
        except (ValueError, OSError, FileExistsError) as error:
            messagebox.showerror('Nie udało się wyeksportować', str(error), parent=self)
            return
        messagebox.showinfo('Raport zapisany', f'Zapisano raport:\n{path}', parent=self)
