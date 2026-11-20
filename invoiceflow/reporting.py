"""Portable CSV and basic Excel XLSX reports (standard library only).

The XLSX writer intentionally supports only value tables (not user formulas or macros).
Spreadsheet text cells are inline strings, preventing formula interpretation.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from decimal import Decimal
from tempfile import NamedTemporaryFile
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile, ZIP_DEFLATED

from .analytics import dashboard_data, filter_imports, filter_products, top_products
from .history import _publish_staged

MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CONTENT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'


def _safe_csv_text(text: object) -> str:
    """Protect spreadsheet programs opening CSV from formula injection."""
    value = str(text if text is not None else '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value


def _tables(ledger: Path) -> list[tuple[str, list[str], list[list[object]]]]:
    snapshot = dashboard_data(ledger)
    stats = snapshot['stats']
    summary = [
        ['Aktywne importy', stats['active']],
        ['Cofnięte importy', stats['undone']],
        ['Pozycje z aktywnych importów', stats['lines']],
        ['Łączna wartość pozycji', stats['income']],
        ['Liczba produktów', stats['products']],
        ['Produkty z niskim stanem (<=5)', stats['low_stock']],
    ]
    imports = filter_imports(ledger, limit=5000)
    products = filter_products(ledger)
    ranked = top_products(ledger, limit=2000)
    months = snapshot['monthly']
    return [
        ('Podsumowanie', ['Wskaźnik', 'Wartość'], summary),
        ('Importy', ['ID', 'Data UTC', 'Status', 'Faktura', 'Pozycje', 'Wartość', 'Plik eksportu'],
         [[r['id'], r['created_at'], r['status'], r['source_name'], r['lines'], r['total_income'], r['output_path']] for r in imports]),
        ('Produkty', ['Produkt', 'Stan', 'Suma Income', 'Ostatnia aktualizacja UTC'],
         [[r['item'], r['quantity'], r['income'], r['updated_at']] for r in products]),
        ('Top produkty', ['Produkt', 'Sprzedana ilość', 'Łączna wartość'],
         [[r['item'], r['quantity'], r['income']] for r in ranked]),
        ('Sprzedaż miesięczna', ['Miesiąc UTC', 'Wartość'], [[r['period'], str(r['income'])] for r in months]),
    ]


def _xml(root: Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(root, encoding='utf-8')


def _column_name(index: int) -> str:
    letters = ''
    while index:
        index, remain = divmod(index - 1, 26)
        letters = chr(65 + remain) + letters
    return letters


def _worksheet(headers: list[str], data: list[list[object]], numeric_columns: set[int] | None = None) -> bytes:
    numeric_columns = numeric_columns or set()
    worksheet = Element('worksheet', {'xmlns': MAIN_NS})
    views = SubElement(worksheet, 'sheetViews')
    view = SubElement(views, 'sheetView', workbookViewId='0')
    SubElement(view, 'pane', ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
    cols = SubElement(worksheet, 'cols')
    for i, heading in enumerate(headers, 1):
        width = min(44, max(14, len(heading) + 4))
        SubElement(cols, 'col', min=str(i), max=str(i), width=str(width), customWidth='1')
    sheet_data = SubElement(worksheet, 'sheetData')
    for rid, values in enumerate([headers, *data], 1):
        row = SubElement(sheet_data, 'row', r=str(rid))
        for cid, value in enumerate(values, 1):
            attr = {'r': f'{_column_name(cid)}{rid}'}
            if rid == 1:
                attr['s'] = '1'
            cell = SubElement(row, 'c', attr)
            if rid > 1 and cid in numeric_columns and value not in (None, ''):
                try:
                    value = Decimal(str(value))
                except Exception as exc:
                    raise ValueError(f'Niepoprawna liczba w raporcie: {value!r}') from exc
                if not value.is_finite():
                    raise ValueError('W raporcie są wartości niefinansowe (NaN/Inf).')
                SubElement(cell, 'v').text = str(value)
            else:
                cell.set('t', 'inlineStr')
                SubElement(SubElement(cell, 'is'), 't').text = str(value if value is not None else '')
    if headers:
        SubElement(worksheet, 'autoFilter', ref=f'A1:{_column_name(len(headers))}{len(data) + 1}')
    return _xml(worksheet)


def _styles() -> bytes:
    style = Element('styleSheet', xmlns=MAIN_NS)
    fonts = SubElement(style, 'fonts', count='2')
    font = SubElement(fonts, 'font')
    SubElement(font, 'sz', val='11')
    SubElement(font, 'name', val='Calibri')
    bold = SubElement(fonts, 'font')
    SubElement(bold, 'b')
    SubElement(bold, 'sz', val='11')
    SubElement(bold, 'color', rgb='FFFFFFFF')
    SubElement(bold, 'name', val='Calibri')
    fills = SubElement(style, 'fills', count='3')
    SubElement(SubElement(fills, 'fill'), 'patternFill', patternType='none')
    SubElement(SubElement(fills, 'fill'), 'patternFill', patternType='gray125')
    blue = SubElement(SubElement(fills, 'fill'), 'patternFill', patternType='solid')
    SubElement(blue, 'fgColor', rgb='FF24466C')
    SubElement(blue, 'bgColor', indexed='64')
    borders = SubElement(style, 'borders', count='1')
    SubElement(borders, 'border')
    xfs = SubElement(style, 'cellStyleXfs', count='1')
    SubElement(xfs, 'xf', numFmtId='0', fontId='0', fillId='0', borderId='0')
    cxf = SubElement(style, 'cellXfs', count='2')
    SubElement(cxf, 'xf', numFmtId='0', fontId='0', fillId='0', borderId='0', xfId='0')
    SubElement(cxf, 'xf', numFmtId='0', fontId='1', fillId='2', borderId='0', xfId='0')
    return _xml(style)


def _xlsx_bytes(tables: list[tuple[str, list[str], list[list[object]]]]) -> bytes:
    memory = io.BytesIO()
    with ZipFile(memory, 'w', ZIP_DEFLATED) as archive:
        types = Element('Types', xmlns=CONTENT_NS)
        SubElement(types, 'Default', Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml')
        SubElement(types, 'Default', Extension='xml', ContentType='application/xml')
        SubElement(types, 'Override', PartName='/xl/workbook.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
        SubElement(types, 'Override', PartName='/xl/styles.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml')
        for i in range(1, len(tables) + 1):
            SubElement(types, 'Override', PartName=f'/xl/worksheets/sheet{i}.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
        archive.writestr('[Content_Types].xml', _xml(types))
        rels = Element('Relationships', xmlns=PKG_REL_NS)
        SubElement(rels, 'Relationship', Id='rId1', Type=OFFICE_REL_NS + '/officeDocument', Target='xl/workbook.xml')
        archive.writestr('_rels/.rels', _xml(rels))
        wb = Element('workbook', {'xmlns': MAIN_NS, 'xmlns:r': OFFICE_REL_NS})
        sheets = SubElement(wb, 'sheets')
        wb_rels = Element('Relationships', xmlns=PKG_REL_NS)
        for i, (name, headers, rows) in enumerate(tables, 1):
            SubElement(sheets, 'sheet', {'name': name, 'sheetId': str(i), 'r:id': f'rId{i}'})
            SubElement(wb_rels, 'Relationship', Id=f'rId{i}', Type=OFFICE_REL_NS + '/worksheet', Target=f'worksheets/sheet{i}.xml')
            numeric_columns = ({2}, {1, 5, 6}, {2, 3}, {2, 3}, {2})[i - 1]
            archive.writestr(f'xl/worksheets/sheet{i}.xml', _worksheet(headers, rows, numeric_columns))
        SubElement(wb_rels, 'Relationship', Id=f'rId{len(tables)+1}', Type=OFFICE_REL_NS + '/styles', Target='styles.xml')
        archive.writestr('xl/workbook.xml', _xml(wb))
        archive.writestr('xl/_rels/workbook.xml.rels', _xml(wb_rels))
        archive.writestr('xl/styles.xml', _styles())
    return memory.getvalue()


def export_report(ledger: Path, destination: Path) -> Path:
    """Export report to new .csv (import history) or .xlsx (five worksheets)."""
    ledger, destination = Path(ledger), Path(destination)
    if not ledger.is_file():
        raise FileNotFoundError('Brak bazy historii SQLite; wykonaj najpierw import.')
    if destination.suffix.lower() not in {'.csv', '.xlsx'}:
        raise ValueError('Wybierz format .csv albo .xlsx.')
    if destination.exists():
        raise FileExistsError('Raport o tej nazwie już istnieje. Wybierz inną nazwę.')
    tables = _tables(ledger)
    if destination.suffix.lower() == '.csv':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        _, headers, rows = tables[1]
        writer.writerow(headers)
        writer.writerows([_safe_csv_text(value) for value in row] for row in rows)
        payload = stream.getvalue().encode('utf-8-sig')
    else:
        payload = _xlsx_bytes(tables)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='wb', prefix='.invoiceflow-report-', suffix='.tmp', dir=destination.parent, delete=False) as temp:
        staged = Path(temp.name)
        temp.write(payload)
    try:
        _publish_staged(staged, destination)
    finally:
        staged.unlink(missing_ok=True)
    return destination
