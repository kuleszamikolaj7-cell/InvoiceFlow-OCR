"""Read-only analytics for InvoiceFlow's auditable SQLite ledger.

Amounts use Decimal; undone imports never contribute to revenue metrics.
Dates represent UTC event timestamps stored in the existing ledger.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from .history import list_imports, list_products, statistics
from .inventory import parse_number


def _check_date(value: str) -> str:
    value = value.strip()
    if value:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('Data musi mieć format RRRR-MM-DD.') from exc
    return value


def filter_imports(
    ledger: Path, query: str = '', status: str = 'wszystkie',
    start_date: str = '', end_date: str = '', limit: int = 500,
) -> list[dict]:
    """Search source filenames, statuses and inclusive UTC creation dates."""
    if status not in ('wszystkie', 'applied', 'undone'):
        raise ValueError('Nieznany filtr statusu.')
    start_date, end_date = _check_date(start_date), _check_date(end_date)
    if start_date and end_date and start_date > end_date:
        raise ValueError('Data początkowa nie może być późniejsza od końcowej.')
    if not Path(ledger).is_file():
        return []
    conditions, params = [], []
    if query.strip():
        conditions.append('instr(lower(source_name), ?) > 0')
        params.append(query.strip().lower())
    if status != 'wszystkie':
        conditions.append('status=?')
        params.append(status)
    if start_date:
        conditions.append('substr(created_at,1,10)>=?')
        params.append(start_date)
    if end_date:
        conditions.append('substr(created_at,1,10)<=?')
        params.append(end_date)
    where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT id,created_at,status,source_name,lines,total_income,output_path '
            'FROM imports' + where + ' ORDER BY id DESC LIMIT ?',
            (*params, max(1, min(int(limit), 5000))),
        ).fetchall()
    return [dict(row) for row in rows]


def filter_products(ledger: Path, query: str = '', low_stock_only: bool = False) -> list[dict]:
    products = list_products(ledger, limit=2000)
    needle = query.strip().casefold()
    return [row for row in products if
            (not needle or needle in row['item'].casefold()) and
            (not low_stock_only or parse_number(row['quantity']) <= 5)]


def sales_series(ledger: Path, group: str = 'month') -> list[dict]:
    """Sales are totals of active invoices grouped by UTC day or month."""
    if group not in ('month', 'day'):
        raise ValueError('Nieobsługiwany przedział czasu.')
    if not Path(ledger).is_file():
        return []
    with sqlite3.connect(ledger) as conn:
        rows = conn.execute(
            "SELECT created_at,total_income FROM imports WHERE status='applied' ORDER BY created_at"
        ).fetchall()
    grouped = defaultdict(lambda: Decimal('0'))
    for created_at, amount in rows:
        grouped[created_at[:7] if group == 'month' else created_at[:10]] += Decimal(amount)
    return [{'period': k, 'income': v.quantize(Decimal('0.01'))} for k, v in sorted(grouped.items())]


def top_products(ledger: Path, limit: int = 8) -> list[dict]:
    """Rank imported line items by total confirmed value, excluding undone imports."""
    if not Path(ledger).is_file():
        return []
    with sqlite3.connect(ledger) as conn:
        rows = conn.execute(
            "SELECT i.item,i.quantity,i.income FROM import_items i "
            "JOIN imports t ON t.id=i.import_id WHERE t.status='applied'"
        ).fetchall()
    aggregated = {}
    for name, qty, amount in rows:
        key = name.strip().casefold()
        if key not in aggregated:
            aggregated[key] = {'item': name.strip(), 'quantity': Decimal('0'), 'income': Decimal('0')}
        aggregated[key]['quantity'] += parse_number(qty)
        aggregated[key]['income'] += parse_number(amount)
    ranked = sorted(aggregated.values(), key=lambda r: (-r['income'], r['item'].casefold()))
    return [dict(item=r['item'], quantity=str(r['quantity']), income=str(r['income'].quantize(Decimal('0.01'))))
            for r in ranked[:max(1, limit)]]


def dashboard_data(ledger: Path) -> dict:
    """Stable dashboard payload, free of GUI dependencies."""
    return {
        'stats': statistics(ledger),
        'monthly': sales_series(ledger),
        'daily': sales_series(ledger, group='day'),
        'top_products': top_products(ledger),
        'recent': list_imports(ledger, limit=5),
    }
