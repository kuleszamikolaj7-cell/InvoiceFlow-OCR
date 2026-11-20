"""Read-only diagnostics for the CSV inventory used by InvoiceFlow.

No data is changed by these functions. The column and name rules match the
inventory engine, so an error can be shown *before* opening an export dialog.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("Item", "Quantity", "Income")


def describe_item_name_errors(names: list[str], *, first_csv_row: int = 2) -> list[str]:
    """Return actionable problems with 1-based CSV row numbers (including header)."""
    errors: list[str] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(names, start=first_csv_row):
        name = str(raw).strip()
        if not name:
            errors.append(f"Wiersz CSV {number}: pusta nazwa w kolumnie Item.")
            continue
        key = name.casefold()
        if key in seen:
            errors.append(
                f"Wiersz CSV {number}: produkt {name!r} powtarza nazwę "
                f"z wiersza CSV {seen[key]} (ignorowana wielkość liter i spacje na brzegach)."
            )
        else:
            seen[key] = number
    return errors


def inspect_inventory_csv(path: str | Path) -> int:
    """Validate CSV header and product names; return product count or raise ValueError.

    CSV is deliberately read exactly like the inventory engine (comma-separated,
    UTF-8 with optional BOM). It is a preflight, not a replacement for the
    engine's quantity/income checks and SQLite concurrency protections.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku magazynu CSV: {path}")
    try:
        data = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Nie można odczytać CSV: {path.name}. Sprawdź UTF-8 i separator przecinka. {exc}") from exc
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(
            f"Niepoprawny magazyn: {path.name}. Brakuje kolumn: {', '.join(missing)}. "
            "Wymagany nagłówek: Item,Quantity,Income (separator: przecinek)."
        )
    if data.empty:
        raise ValueError(f"Magazyn {path.name} nie zawiera produktów.")
    errors = describe_item_name_errors(data["Item"].tolist())
    if errors:
        shown = errors[:10]
        remainder = f"\n... i kolejnych {len(errors) - 10} błędów." if len(errors) > 10 else ""
        raise ValueError(
            f"Niepoprawne nazwy produktów w {path.name}:\n- "
            + "\n- ".join(shown) + remainder
        )
    return len(data)
