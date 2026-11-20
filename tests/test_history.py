"""SQLite audited export: duplicate prevention, linear history, rollback safety."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from invoiceflow.history import commit_review, undo_last, list_imports, list_products, statistics
from invoiceflow.review import save_review


@pytest.fixture
def sample(tmp_path):
    src = tmp_path / 'inventory.csv'
    src.write_text('Item,Quantity,Income\nProduct A,15,100.00\nProduct B,22,50.00\n', encoding='utf-8')
    pdf = tmp_path / 'invoice.pdf'
    pdf.write_bytes(b'%PDF test invoice A')
    folder = tmp_path / 'scan'
    folder.mkdir()
    review = folder / 'review.csv'
    save_review(review, [
        {'Row':'1','Item':'Product A','Quantity':'2','Income':'15,50','Approved':'yes'},
        {'Row':'2','Item':'Product B','Quantity':'1','Income':'12.00','Approved':'yes'},
    ])
    ledger = tmp_path / 'data' / 'history.sqlite3'
    return src, pdf, review, ledger


def _commit(sample, output, source=None, db=None, review=None):
    orig_db, pdf, orig_review, ledger = sample
    return commit_review(review or orig_review, db or orig_db, output, ledger, source_pdf=source or pdf)


def test_commit_and_history_stats(sample, tmp_path):
    src, pdf, review, ledger = sample
    output, count, import_id = _commit(sample, tmp_path / 'out.csv')
    assert count == 2 and import_id == 1
    db = pd.read_csv(output)
    assert db['Quantity'].tolist() == [13, 21]
    assert db['Income'].tolist() == [115.5, 62.0]
    assert src.read_text(encoding='utf-8').startswith('Item,Quantity,Income')
    assert statistics(ledger) == {'active':1, 'undone':0, 'lines':2,'income':'27.50','products':2,'low_stock':0,'latest_output':str(output.resolve())}
    assert list_imports(ledger)[0]['source_name'] == pdf.name


def test_duplicate_pdf_blocked_even_if_name_changed(sample, tmp_path):
    out, _, _ = _commit(sample, tmp_path / 'out.csv')
    same = tmp_path / 'another_name.pdf'
    same.write_bytes(sample[1].read_bytes())
    with pytest.raises(ValueError, match='już rozliczona'):
        _commit(sample, tmp_path / 'second.csv', source=same, db=out)
    assert not (tmp_path / 'second.csv').exists()
    assert statistics(sample[3])['active'] == 1


def test_stale_inventory_rejected(sample, tmp_path):
    _commit(sample, tmp_path / 'out.csv')
    new_pdf = tmp_path / 'second.pdf'
    new_pdf.write_bytes(b'%PDF other')
    with pytest.raises(ValueError, match='aktualna wersja magazynu'):
        _commit(sample, tmp_path / 'old.csv', source=new_pdf)
    assert not (tmp_path / 'old.csv').exists()


def test_chain_undo_last_and_retry(sample, tmp_path):
    first, _, _ = _commit(sample, tmp_path / 'out1.csv')
    other_pdf = tmp_path / 'other.pdf'
    other_pdf.write_bytes(b'%PDF different')
    second, _, _ = _commit(sample, tmp_path / 'out2.csv', source=other_pdf, db=first)
    assert statistics(sample[3])['active'] == 2
    reverted, undone_id = undo_last(sample[3], tmp_path / 'restored.csv')
    assert undone_id == 2
    assert reverted.read_bytes() == first.read_bytes()
    assert statistics(sample[3])['active'] == 1
    assert statistics(sample[3])['undone'] == 1
    # It is allowed to reimport a previously undone invoice against the restored current state.
    again, _, _ = _commit(sample, tmp_path / 'out3.csv', source=other_pdf, db=reverted)
    assert again.is_file()
    assert statistics(sample[3])['active'] == 2


def test_undo_first_restores_exact_input(sample, tmp_path):
    src = sample[0]
    original = src.read_bytes()
    _commit(sample, tmp_path / 'out.csv')
    restored, _ = undo_last(sample[3], tmp_path / 'restored.csv')
    assert restored.read_bytes() == original
    assert statistics(sample[3])['active'] == 0
    assert list_imports(sample[3])[0]['status'] == 'undone'


def test_undo_modified_export_is_blocked(sample, tmp_path):
    output, _, _ = _commit(sample, tmp_path / 'out.csv')
    output.write_text('corrupted', encoding='utf-8')
    with pytest.raises(ValueError, match='zmieniony/usunięty'):
        undo_last(sample[3], tmp_path / 'restored.csv')
    assert not (tmp_path / 'restored.csv').exists()
    assert statistics(sample[3])['active'] == 1


def test_existing_destination_never_overwritten(sample, tmp_path):
    destination = tmp_path / 'out.csv'
    destination.write_text('keep', encoding='utf-8')
    with pytest.raises(FileExistsError):
        _commit(sample, destination)
    assert destination.read_text() == 'keep'
    _commit(sample, tmp_path / 'out2.csv')
    with pytest.raises(FileExistsError):
        undo_last(sample[3], destination)
    assert destination.read_text() == 'keep'


def test_missing_approvals_no_output_no_active_import(sample, tmp_path):
    review = sample[2]
    save_review(review, [{'Row':'1','Item':'Product A','Quantity':'2','Income':'12.00','Approved':'no'}])
    with pytest.raises(ValueError, match='zatwierdzone'):
        _commit(sample, tmp_path / 'out.csv')
    assert not (tmp_path / 'out.csv').exists()
    assert statistics(sample[3])['active'] == 0


def test_wrong_product_no_output(sample, tmp_path):
    save_review(sample[2], [{'Row':'1','Item':'Nonexistent','Quantity':'2','Income':'12.00','Approved':'yes'}])
    with pytest.raises(ValueError, match='nie znaleziono produktu'):
        _commit(sample, tmp_path / 'out.csv')
    assert not (tmp_path / 'out.csv').exists()


def test_recorded_source_sha_verified(sample, tmp_path):
    src, pdf, review, ledger = sample
    report = {'source_file':pdf.name, 'source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}
    (review.parent / 'quality.json').write_text(json.dumps(report), encoding='utf-8')
    other = tmp_path / 'wrong.pdf'
    other.write_bytes(b'other')
    with pytest.raises(ValueError, match='nie zgadza się'):
        _commit(sample, tmp_path / 'out.csv', source=other)
    output, count, _ = commit_review(review, src, tmp_path / 'out.csv', ledger, source_pdf=None)
    assert count == 2 and output.exists()


def test_empty_ledger_stats_and_undo_error(sample, tmp_path):
    assert statistics(tmp_path / 'none.sqlite3')['active'] == 0
    assert list_imports(tmp_path / 'none.sqlite3') == []
    with pytest.raises(FileNotFoundError):
        undo_last(tmp_path / 'none.sqlite3', tmp_path / 'restore.csv')


def test_untracked_review_requires_pdf(sample, tmp_path):
    with pytest.raises(ValueError, match='--pdf'):
        commit_review(sample[2], sample[0], tmp_path/'out.csv', sample[3])


def test_oversized_snapshot_rejected(sample, tmp_path, monkeypatch):
    import invoiceflow.history as history
    monkeypatch.setattr(history, 'MAX_SNAPSHOT_SIZE', 10)
    with pytest.raises(ValueError, match='50 MB'):
        _commit(sample, tmp_path/'out.csv')


def test_rollback_after_rollback_chain(sample, tmp_path):
    first, _, _ = _commit(sample, tmp_path/'out1.csv')
    next_pdf = tmp_path/'another.pdf'
    next_pdf.write_bytes(b'%PDF another')
    _commit(sample, tmp_path/'out2.csv', source=next_pdf, db=first)
    undo_last(sample[3], tmp_path/'rollback2.csv')
    restored, _ = undo_last(sample[3], tmp_path/'rollback1.csv')
    assert restored.read_bytes() == sample[0].read_bytes()
    assert statistics(sample[3])['undone'] == 2


def test_sqlite_mirrors_products_and_undo(sample, tmp_path):
    _commit(sample, tmp_path / 'export.csv')
    products = list_products(sample[3])
    assert [p['item'] for p in products] == ['Product A', 'Product B']
    assert [p['quantity'] for p in products] == ['13', '21']
    undo_last(sample[3], tmp_path / 'restored.csv')
    assert [p['quantity'] for p in list_products(sample[3])] == ['15', '22']
    assert statistics(sample[3])['products'] == 2
