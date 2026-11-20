"""Audited inventory exports: SQLite ledger, duplicate prevention, and reversible snapshots.

One ledger represents one linear CSV inventory history. Never mutate input CSVs.
Filesystem/SQLite cannot commit atomically together; existing outputs are never overwritten.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .inventory import apply_review, parse_number
from .review import load_review

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('applied', 'undone')),
    source_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    review_sha256 TEXT NOT NULL,
    base_sha256 TEXT NOT NULL,
    output_sha256 TEXT NOT NULL,
    output_path TEXT NOT NULL,
    base_snapshot BLOB NOT NULL,
    lines INTEGER NOT NULL,
    total_income TEXT NOT NULL,
    undone_at TEXT,
    undo_path TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_applied_invoice ON imports(source_sha256) WHERE status='applied';
CREATE TABLE IF NOT EXISTS products (
    item TEXT PRIMARY KEY COLLATE NOCASE,
    quantity TEXT NOT NULL,
    income TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_items (
    import_id INTEGER NOT NULL REFERENCES imports(id),
    row_ref TEXT NOT NULL,
    item TEXT NOT NULL,
    quantity TEXT NOT NULL,
    income TEXT NOT NULL
);
"""
MAX_SNAPSHOT_SIZE = 50 * 1024 * 1024


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _open_ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    conn.executescript(SCHEMA)
    return conn


def _source_identity(review_path: Path, source_pdf: Path | None) -> tuple[str, str]:
    report_file = review_path.parent / 'quality.json'
    recorded_digest = None
    recorded_name = None
    if report_file.is_file():
        try:
            report = json.loads(report_file.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('Uszkodzony raport quality.json; nie można zweryfikować tożsamości faktury.') from exc
        recorded_digest = report.get('source_sha256')
        recorded_name = report.get('source_file')
        if not isinstance(recorded_digest, str) or not re.fullmatch('[a-f0-9]{64}', recorded_digest):
            raise ValueError('quality.json nie zawiera poprawnego source_sha256.')
    if source_pdf is not None:
        source_pdf = Path(source_pdf)
        if not source_pdf.is_file():
            raise FileNotFoundError(f'Nie znaleziono PDF: {source_pdf}')
        computed = _hash_file(source_pdf)
        if recorded_digest and recorded_digest != computed:
            raise ValueError('Wybrany PDF nie zgadza się z hashem z quality.json. Zeskanuj PDF ponownie.')
        return computed, source_pdf.name
    if recorded_digest and recorded_name:
        # Skaner zapisuje digest treści PDF do quality.json.
        return recorded_digest, str(recorded_name)
    raise ValueError('Brak identyfikatora faktury. Podaj --pdf (w GUI wybierz fakturę).')


def _extract_items(review_path: Path) -> tuple[list[dict[str, str]], str]:
    items = []
    total = Decimal('0')
    for row in load_review(review_path):
        if not any(row[key].strip() for key in ('Item', 'Quantity', 'Income')):
            continue
        if row['Approved'].strip().casefold() != 'yes':
            raise ValueError('Nie wszystkie pozycje review.csv są zatwierdzone.')
        qty = parse_number(row['Quantity'])
        amount = parse_number(row['Income'])
        if qty <= 0 or amount < 0 or amount.as_tuple().exponent < -2:
            raise ValueError(f"Nieprawidłowa ilość/kwota w pozycji {row['Row']}")
        total += amount
        items.append({'row_ref': row['Row'], 'item': row['Item'].strip(), 'quantity': str(qty), 'income': str(amount)})
    if not items:
        raise ValueError('Brak zatwierdzonych pozycji do importu.')
    return items, str(total.quantize(Decimal('0.01')))


def _sync_products(conn: sqlite3.Connection, csv_bytes: bytes, when: str) -> None:
    """Keep a queryable SQLite mirror of the latest CSV inventory snapshot."""
    try:
        content = csv_bytes.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Plik CSV magazynu musi być w UTF-8.') from exc
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or not {'Item', 'Quantity', 'Income'}.issubset(reader.fieldnames):
        raise ValueError('Magazyn musi mieć kolumny Item, Quantity, Income.')
    values = []
    seen = set()
    for row in reader:
        item = (row.get('Item') or '').strip()
        normalized = item.casefold()
        if not item or normalized in seen:
            raise ValueError('Niepoprawne lub zduplikowane produkty w magazynie CSV.')
        seen.add(normalized)
        qty = parse_number(row['Quantity'])
        income = parse_number(row['Income'])
        if qty < 0 or income < 0:
            raise ValueError('Nieprawidłowe ujemne wartości w magazynie.')
        values.append((item, str(qty), str(income), when))
    conn.execute('DELETE FROM products')
    conn.executemany('INSERT INTO products (item, quantity, income, updated_at) VALUES (?,?,?,?)', values)


def _stage_csv(path: Path, contents: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.invoiceflow-', suffix='.tmp', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        return temp
    except BaseException:
        if temp is not None:
            temp.unlink(missing_ok=True)
        raise



def _publish_staged(staged: Path, destination: Path) -> None:
    """Portable, no-clobber publication (including Windows drives without hard links).

    O_EXCL atomically reserves the destination name; never replace an existing
    user's export. Write and fsync while the SQLite transaction is still open.
    Clean up only our own incomplete file if copying fails.
    """
    import shutil

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as target, staged.open('rb') as source:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        # O_EXCL guarantees ownership of this path once opened successfully.
        destination.unlink(missing_ok=True)
        raise

def commit_review(
    review_path: Path, database_path: Path, output_path: Path,
    ledger_path: Path, source_pdf: Path | None = None,
) -> tuple[Path, int, int]:
    """Make reviewed CSV export and audit event; prevent duplicate PDF or stale inventory.

    A single ledger follows one inventory chain. To continue, pass the most recent
    exported/restored CSV as --db, NOT the original version again.
    """
    review_path, database_path, output_path, ledger_path = map(Path, (review_path, database_path, output_path, ledger_path))
    for path in (review_path, database_path):
        if not path.is_file():
            raise FileNotFoundError(f'Nie znaleziono pliku: {path}')
    if output_path.exists():
        raise FileExistsError(f'Plik wynikowy już istnieje: {output_path}. Wybierz nową nazwę.')
    if output_path.resolve() in (review_path.resolve(), database_path.resolve(), ledger_path.resolve()):
        raise ValueError('Plik wynikowy musi być osobną kopią CSV (nie review, bazą ani bazą SQLite).')
    if ledger_path.resolve() in (review_path.resolve(), database_path.resolve()):
        raise ValueError('Baza historii SQLite musi mieć osobną ścieżkę.')
    pdf_digest, pdf_name = _source_identity(review_path, source_pdf)
    review_digest = _hash_file(review_path)
    base_data = database_path.read_bytes()
    if len(base_data) > MAX_SNAPSHOT_SIZE:
        raise ValueError('Baza CSV przekracza 50 MB; import z historią nie jest obsługiwany.')
    base_digest = _hash_bytes(base_data)
    items, total = _extract_items(review_path)
    # Use the already validated v0.3 inventory implementation, but only on a fresh temp file.
    temp_output = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.inventory-preview-', suffix='.csv', dir=output_path.parent if output_path.parent.is_dir() else None, delete=False) as tmp:
            temp_output = Path(tmp.name)
        # file exists, use overwrite=True only for this unique temporary result
        _, count = apply_review(review_path, database_path, temp_output, overwrite=True)
        result_bytes = temp_output.read_bytes()
        result_digest = _hash_bytes(result_bytes)
    finally:
        if temp_output:
            temp_output.unlink(missing_ok=True)
    staged = None
    conn = _open_ledger(ledger_path)
    output_created = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        duplicate = conn.execute("SELECT id FROM imports WHERE source_sha256=? AND status='applied'", (pdf_digest,)).fetchone()
        if duplicate:
            raise ValueError(f'Faktura została już rozliczona w imporcie #{duplicate["id"]}. Powtórny import zablokowany.')
        head = conn.execute("SELECT output_sha256 FROM imports WHERE status='applied' ORDER BY id DESC LIMIT 1").fetchone()
        base_setting = conn.execute("SELECT value FROM settings WHERE key='initial_sha256'").fetchone()
        expected = head['output_sha256'] if head else (base_setting['value'] if base_setting else None)
        if expected is not None and base_digest != expected:
            raise ValueError('To nie jest aktualna wersja magazynu. Wybierz ostatni eksport (lub plik przywrócony przez cofnięcie).')
        if _hash_file(review_path) != review_digest or _hash_file(database_path) != base_digest:
            raise ValueError('Pliki wejściowe zmieniły się podczas przygotowania importu. Ponów operację.')
        if source_pdf is not None and _hash_file(Path(source_pdf)) != pdf_digest:
            raise ValueError('PDF zmienił się podczas importu. Ponów operację.')
        if output_path.exists():
            raise FileExistsError(f'Plik wynikowy został już utworzony: {output_path}')
        if base_setting is None:
            conn.execute('INSERT INTO settings (key,value) VALUES (?,?)', ('initial_sha256', base_digest))
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        cursor = conn.execute('''INSERT INTO imports
                (created_at,status,source_name,source_sha256,review_sha256,base_sha256,output_sha256,output_path,base_snapshot,lines,total_income)
                VALUES (?,'applied',?,?,?,?,?,?,?,?,?)''',
                (now, pdf_name, pdf_digest, review_digest, base_digest, result_digest, str(output_path.resolve()), base_data, count, total))
        import_id = int(cursor.lastrowid)
        conn.executemany('INSERT INTO import_items (import_id,row_ref,item,quantity,income) VALUES (?,?,?,?,?)',
                         [(import_id, item['row_ref'], item['item'], item['quantity'], item['income']) for item in items])
        _sync_products(conn, result_bytes, now)
        staged = _stage_csv(output_path, result_bytes)
        # O_EXCL avoids hard-link limitations on Windows and never overwrites.
        _publish_staged(staged, output_path)
        output_created = True
        conn.commit()
        return output_path, count, import_id
    except Exception as exc:
        conn.rollback()
        if output_created:
            # Import row was not committed. Leave exported file as evidence rather than deleting
            # a potentially user-visible output after an ambiguous database failure.
            raise RuntimeError(f'Nie potwierdzono zapisu historii; plik {output_path} może istnieć. Sprawdź przed ponowieniem. {exc}') from exc
        raise
    finally:
        conn.close()
        if staged is not None:
            staged.unlink(missing_ok=True)


def undo_last(ledger_path: Path, output_path: Path) -> tuple[Path, int]:
    """Undo only latest applied import, producing a fresh CSV from stored snapshot."""
    ledger_path, output_path = Path(ledger_path), Path(output_path)
    if not ledger_path.is_file():
        raise FileNotFoundError('Brak historii importów SQLite.')
    if output_path.exists():
        raise FileExistsError('Plik przywracania już istnieje. Wybierz nową nazwę.')
    if output_path.resolve() == ledger_path.resolve():
        raise ValueError('Plik CSV nie może zastąpić bazy SQLite.')
    conn = _open_ledger(ledger_path)
    staged = None
    created = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM imports WHERE status='applied' ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError('Nie ma aktywnych importów do cofnięcia.')
        current_file = Path(row['output_path'])
        if not current_file.is_file() or _hash_file(current_file) != row['output_sha256']:
            raise ValueError('Eksport ostatniego importu został zmieniony/usunięty. Cofanie wstrzymane.')
        if output_path.resolve() == current_file.resolve():
            raise ValueError('Przywracany CSV musi mieć nową nazwę.')
        original = bytes(row['base_snapshot'])
        if _hash_bytes(original) != row['base_sha256']:
            raise ValueError('Uszkodzony snapshot w historii; cofanie wstrzymane.')
        _sync_products(conn, original, datetime.now(timezone.utc).isoformat(timespec='seconds'))
        staged = _stage_csv(output_path, original)
        _publish_staged(staged, output_path)
        created = True
        conn.execute("UPDATE imports SET status='undone', undone_at=?, undo_path=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(timespec='seconds'), str(output_path.resolve()), row['id']))
        conn.commit()
        return output_path, int(row['id'])
    except Exception as exc:
        conn.rollback()
        if created:
            raise RuntimeError(f'Nie potwierdzono cofnięcia w SQLite; plik {output_path} może istnieć. {exc}') from exc
        raise
    finally:
        conn.close()
        if staged:
            staged.unlink(missing_ok=True)


def list_imports(ledger_path: Path, limit: int = 100) -> list[dict]:
    if not Path(ledger_path).is_file():
        return []
    with _open_ledger(Path(ledger_path)) as conn:
        rows = conn.execute('''SELECT id,created_at,status,source_name,lines,total_income,
                              output_path,undone_at,undo_path FROM imports ORDER BY id DESC LIMIT ?''', (min(500, max(1, limit)),)).fetchall()
        return [dict(row) for row in rows]


def statistics(ledger_path: Path) -> dict:
    if not Path(ledger_path).is_file():
        return {'active': 0, 'undone': 0, 'lines': 0, 'income': '0.00', 'products': 0, 'low_stock': 0, 'latest_output': None}
    with _open_ledger(Path(ledger_path)) as conn:
        rows = conn.execute('SELECT status,lines,total_income,output_path FROM imports ORDER BY id').fetchall()
        stock = conn.execute('SELECT quantity FROM products').fetchall()
    active = [r for r in rows if r['status'] == 'applied']
    undone = [r for r in rows if r['status'] == 'undone']
    return {
        'active': len(active), 'undone': len(undone),
        'lines': sum(int(r['lines']) for r in active),
        'products': len(stock),
        'low_stock': sum(parse_number(row['quantity']) <= 5 for row in stock),
        'income': str(sum((Decimal(r['total_income']) for r in active), Decimal('0')).quantize(Decimal('0.01'))),
        'latest_output': active[-1]['output_path'] if active else None,
    }


def list_products(ledger_path: Path, limit: int = 500) -> list[dict]:
    """Query products from SQLite's mirror of the most recent inventory CSV."""
    if not Path(ledger_path).is_file():
        return []
    with _open_ledger(Path(ledger_path)) as conn:
        rows = conn.execute('SELECT item,quantity,income,updated_at FROM products ORDER BY item LIMIT ?',
                            (min(2000, max(1, limit)),)).fetchall()
        return [dict(row) for row in rows]
