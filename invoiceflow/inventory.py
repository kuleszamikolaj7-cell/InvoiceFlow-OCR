"""Bezpieczny, deterministyczny import ręcznie zatwierdzonych danych do CSV."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

import pandas as pd

from .diagnostics import describe_item_name_errors

REQUIRED_COLUMNS = ("Item", "Quantity", "Income")
REVIEW_COLUMNS = (*REQUIRED_COLUMNS, "Approved")


def parse_number(value: str) -> Decimal:
    """Rozpoznaj np. 15,50; 1 234,50; 1.234,50; 1,234.50.

    Celowo odrzucamy niejednoznaczne '1,234' i '1.234'.
    """
    cleaned = str(value).strip().replace("\u00a0", " ").replace("\u202f", " ")
    cleaned = re.sub(r"\s*(?:PLN|zł)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(" ", "")
    if not cleaned or not re.fullmatch(r"\d[\d.,]*", cleaned):
        raise ValueError(f"Nieczytelna liczba: {value!r}")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            normalized = cleaned.replace(".", "").replace(",", ".")
        else:
            normalized = cleaned.replace(",", "")
    elif "," in cleaned or "." in cleaned:
        sep = "," if "," in cleaned else "."
        if cleaned.count(sep) > 1:
            raise ValueError(f"Niejednoznaczny format liczby: {value!r}")
        left, right = cleaned.split(sep)
        if not right or len(right) == 3:
            raise ValueError(f"Niejednoznaczny format liczby: {value!r}")
        normalized = f"{left}.{right}"
    else:
        normalized = cleaned

    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Niepoprawna liczba: {value!r}") from exc


def _format_decimal(n: Decimal, money: bool = False) -> str:
    if money:
        if n.as_tuple().exponent < -2:
            raise ValueError(f"Kwota ma więcej niż 2 miejsca po przecinku: {n}")
        return format(n.quantize(Decimal("0.01")), ".2f")
    return format(n, "f")


def apply_review(
    review_path: Path, database_path: Path, output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int]:
    review_path = Path(review_path)
    database_path = Path(database_path)
    output_path = Path(output_path)
    for path in (review_path, database_path):
        if not path.is_file():
            raise FileNotFoundError(f"Nie znaleziono pliku: {path}")
    if output_path.resolve() in (database_path.resolve(), review_path.resolve()):
        raise ValueError("Nie wolno nadpisać oryginalnej bazy ani review.csv. Podaj inny --out.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} już istnieje. Użyj innej nazwy lub --overwrite.")

    review = pd.read_csv(review_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    db = pd.read_csv(database_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if not set(REVIEW_COLUMNS).issubset(review.columns):
        raise ValueError(f"Plik review.csv musi mieć kolumny: {', '.join(REVIEW_COLUMNS)}")
    if not set(REQUIRED_COLUMNS).issubset(db.columns):
        raise ValueError(f"Baza CSV musi mieć kolumny: {', '.join(REQUIRED_COLUMNS)}")

    name_errors = describe_item_name_errors(db["Item"].tolist())
    if name_errors:
        raise ValueError("Wstrzymano import — puste lub nieunikalne nazwy produktów w bazie:\n- " + "\n- ".join(name_errors[:10]))
    names = db["Item"].str.strip().str.casefold()
    lookup = dict(zip(names, db.index))
    pending = []
    errors = []
    for pos, (_, row) in enumerate(review.iterrows(), start=2):
        item = row["Item"].strip()
        qty_raw = row["Quantity"].strip()
        income_raw = row["Income"].strip()
        approved = row["Approved"].strip().casefold()
        if not any((item, qty_raw, income_raw)):
            continue
        if approved != "yes":
            errors.append(f"Wiersz CSV {pos}: brak Approved=yes")
            continue
        if item.casefold() not in lookup:
            errors.append(f"Wiersz CSV {pos}: nie znaleziono produktu {item!r}")
            continue
        try:
            qty = parse_number(qty_raw)
            income = parse_number(income_raw)
            if qty <= 0 or income < 0:
                raise ValueError("Ilość musi być dodatnia, a przychód nieujemny")
            if income.as_tuple().exponent < -2:
                raise ValueError("Kwota musi mieć maksymalnie 2 miejsca po przecinku")
            pending.append((lookup[item.casefold()], qty, income, pos))
        except ValueError as exc:
            errors.append(f"Wiersz CSV {pos}: {exc}")

    if errors:
        raise ValueError("Wstrzymano import — popraw błędy:\n- " + "\n- ".join(errors))
    if not pending:
        raise ValueError("Brak zatwierdzonych pozycji do aktualizacji.")

    # Obliczenia na kopii w pamięci; na dysk zapisujemy dopiero po pełnej walidacji.
    result = db.copy()
    for idx, qty, income, pos in pending:
        try:
            stock_before = parse_number(result.at[idx, "Quantity"])
            income_before = parse_number(result.at[idx, "Income"])
            new_stock = stock_before - qty
            if new_stock < 0:
                raise ValueError(f"stan magazynowy spadłby poniżej zera ({new_stock})")
            result.at[idx, "Quantity"] = _format_decimal(new_stock)
            result.at[idx, "Income"] = _format_decimal(income_before + income, money=True)
        except ValueError as exc:
            errors.append(f"Wiersz CSV {pos}: {exc}")
    if errors:
        raise ValueError("Wstrzymano import — popraw błędy:\n- " + "\n- ".join(errors))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Przy normalnym zakończeniu oryginalny CSV pozostaje nietknięty.
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path, len(pending)
