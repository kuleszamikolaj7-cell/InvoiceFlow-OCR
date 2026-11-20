"""Odczyt i bezpieczny zapis plików z ręczną weryfikacją OCR.

Ten moduł nie zależy od GUI, co ułatwia testowanie i użycie CLI.
"""

import csv
import os
import tempfile
from pathlib import Path

FIELDS = ("Row", "Item", "Quantity", "Income", "Approved")


def load_review(path: Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Nie znaleziono review.csv: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(column not in reader.fieldnames for column in FIELDS):
            raise ValueError("Review CSV musi mieć kolumny: " + ", ".join(FIELDS))
        rows = []
        for line, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"Wiersz {line}: za dużo kolumn w pliku CSV")
            if any(row[column] is None for column in FIELDS):
                raise ValueError(f"Wiersz {line}: brak wartości kolumn")
            rows.append({column: row[column] for column in FIELDS})
    if not rows:
        raise ValueError("Review CSV nie zawiera żadnych wierszy")
    return rows


def save_review(path: Path, rows: list[dict[str, str]]) -> Path:
    """Zapis atomowy: niedokończony zapis nie niszczy poprzedniego review."""
    path = Path(path)
    if not rows:
        raise ValueError("Brak wierszy do zapisania")
    normalized = []
    for index, row in enumerate(rows, start=1):
        if any(field not in row or not isinstance(row[field], str) for field in FIELDS):
            raise ValueError(f"Wiersz {index} ma niekompletne dane")
        approved = row["Approved"].strip().casefold()
        if approved not in ("yes", "no"):
            raise ValueError(f"Wiersz {index}: Approved musi być yes lub no")
        normalized.append({**{field: row[field] for field in FIELDS}, "Approved": approved})

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=f".{path.stem}-", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(normalized)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return path


def get_review_stats(rows: list[dict[str, str]]) -> tuple[int, int]:
    """Zwraca liczbę niepustych pozycji i zatwierdzonych pozycji."""
    active = [row for row in rows if any(row[field].strip() for field in ("Item", "Quantity", "Income"))]
    approved = [row for row in active if row["Approved"].strip().casefold() == "yes"]
    return len(active), len(approved)
