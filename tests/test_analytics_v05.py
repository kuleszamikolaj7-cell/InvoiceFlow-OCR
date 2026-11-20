"""v0.5: dashboard, filters, CSV/XLSX reports, portable export regression."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from invoiceflow.analytics import dashboard_data, filter_imports, filter_products, sales_series, top_products
from invoiceflow.history import _publish_staged, commit_review, undo_last
from invoiceflow.reporting import export_report, _safe_csv_text
from invoiceflow.review import save_review


@pytest.fixture
def ledger_data(tmp_path):
    source = tmp_path / 'inventory.csv'
    source.write_text('Item,Quantity,Income\nProduct A,15,100.00\nProduct B,4,50.00\n', encoding='utf-8')
    pdf = tmp_path / 'one.pdf'
    pdf.write_bytes(b'%PDF-1.4 test-one')
    scan = tmp_path / 'scan'
    scan.mkdir()
    review = scan / 'review.csv'
    save_review(review, [
        {'Row':'1','Item':'Product A','Quantity':'2','Income':'15.50','Approved':'yes'},
        {'Row':'2','Item':'Product B','Quantity':'1','Income':'12.00','Approved':'yes'},
    ])
    ledger = tmp_path / 'data' / 'history.sqlite3'
    output = tmp_path / 'newinventory.csv'
    commit_review(review, source, output, ledger, source_pdf=pdf)
    return ledger, output, tmp_path


def test_dashboard_aggregates_active_imports_only(ledger_data):
    ledger, _, _ = ledger_data
    data = dashboard_data(ledger)
    assert data['stats']['active'] == 1
    assert data['stats']['income'] == '27.50'
    assert data['stats']['low_stock'] == 1
    assert len(data['monthly']) == 1
    assert data['monthly'][0]['income'] == Decimal('27.50')
    assert [r['item'] for r in data['top_products']] == ['Product A', 'Product B']


def test_history_search_status_dates_and_bad_input(ledger_data):
    ledger, output, _ = ledger_data
    assert len(filter_imports(ledger, 'ONE')) == 1
    assert filter_imports(ledger, 'not-found') == []
    assert len(filter_imports(ledger, status='applied')) == 1
    assert len(filter_imports(ledger, start_date='2000-01-01', end_date='2100-01-01')) == 1
    with pytest.raises(ValueError, match='RRRR'):
        filter_imports(ledger, start_date='2020-02-30')
    with pytest.raises(ValueError, match='początkowa'):
        filter_imports(ledger, start_date='2026-12-01', end_date='2026-01-01')
    with pytest.raises(ValueError, match='statusu'):
        filter_imports(ledger, status='unknown')
    assert filter_products(ledger, query='proDUCT b', low_stock_only=True)[0]['item'] == 'Product B'
    assert filter_products(ledger, low_stock_only=True)[0]['quantity'] == '3'
    assert filter_products(ledger, query='nonexistent') == []


def test_undo_removes_sales_but_keeps_history(ledger_data):
    ledger, _, folder = ledger_data
    undo_last(ledger, folder / 'restored.csv')
    payload = dashboard_data(ledger)
    assert payload['stats']['active'] == 0
    assert payload['stats']['undone'] == 1
    assert payload['stats']['income'] == '0.00'
    assert payload['monthly'] == []
    assert top_products(ledger) == []
    assert filter_imports(ledger, status='undone')[0]['status'] == 'undone'


def test_export_csv_and_xlsx_workbook(ledger_data):
    ledger, _, folder = ledger_data
    csv_file = export_report(ledger, folder / 'raport.csv')
    content = csv_file.read_text(encoding='utf-8-sig')
    assert 'Product' not in content  # import history, not inventory
    assert 'one.pdf' in content
    assert '27.50' in content
    xlsx_file = export_report(ledger, folder / 'raport.xlsx')
    with ZipFile(xlsx_file) as archive:
        assert archive.testzip() is None
        sheet_names = [f'xl/worksheets/sheet{i}.xml' for i in range(1, 6)]
        assert all(name in archive.namelist() for name in sheet_names)
        for name in sheet_names:
            ET.fromstring(archive.read(name))
        workbook_xml = archive.read('xl/workbook.xml').decode('utf-8')
        assert 'Podsumowanie' in workbook_xml
        assert 'Sprzedaż miesięczna' in workbook_xml
        assert 'Product A' in archive.read('xl/worksheets/sheet3.xml').decode('utf-8')


def test_export_never_overwrites(ledger_data):
    ledger, _, folder = ledger_data
    file = folder / 'raport.xlsx'
    file.write_bytes(b'Keep original')
    with pytest.raises(FileExistsError):
        export_report(ledger, file)
    assert file.read_bytes() == b'Keep original'
    with pytest.raises(ValueError, match='format'):
        export_report(ledger, folder / 'report.txt')


def test_csv_formula_injection_guard():
    assert _safe_csv_text('=HYPERLINK("evil")').startswith("'=")
    assert _safe_csv_text(' +SUM(A1)') == "' +SUM(A1)"
    assert _safe_csv_text('ordinary') == 'ordinary'


def test_portable_publish_works_with_hardlinks_unavailable(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(os, 'link', lambda *args, **kwargs: (_ for _ in ()).throw(OSError(1, 'Not supported')))
    staged = tmp_path / 'staged.tmp'
    staged.write_bytes(b'Staged data')
    target = tmp_path / 'final.csv'
    _publish_staged(staged, target)
    assert target.read_bytes() == b'Staged data'
    staged.write_bytes(b'Changed')
    with pytest.raises(FileExistsError):
        _publish_staged(staged, target)
    assert target.read_bytes() == b'Staged data'


def test_portable_publish_cleans_partial_file_on_failure(tmp_path, monkeypatch):
    import invoiceflow.history as history
    import shutil
    staged = tmp_path / 's.tmp'
    staged.write_bytes(b'hello')
    target = tmp_path / 'new.csv'
    def explode(*args, **kwargs):
        raise OSError('Simulated disk failure')
    monkeypatch.setattr(shutil, 'copyfileobj', explode)
    with pytest.raises(OSError, match='Simulated'):
        history._publish_staged(staged, target)
    assert not target.exists()
