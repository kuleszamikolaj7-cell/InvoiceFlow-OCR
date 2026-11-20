from decimal import Decimal

import pandas as pd
import pytest

from invoiceflow.inventory import apply_review, parse_number


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1 234,50 zł", "1234.50"),
        ("1.234,50", "1234.50"),
        ("1,234.50 PLN", "1234.50"),
        ("18", "18"),
        ("17,5", "17.5"),
    ],
)
def test_parse_number(value, expected):
    assert parse_number(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["1,234", "1.234", "abc", "", "12.34.56"])
def test_ambiguous_or_invalid_number_rejected(value):
    with pytest.raises(ValueError):
        parse_number(value)


def write_csv(path, items):
    pd.DataFrame(items).to_csv(path, index=False)


def test_apply_writes_copy_without_changing_source(tmp_path):
    db = tmp_path / "stock.csv"
    review = tmp_path / "review.csv"
    out = tmp_path / "out.csv"
    write_csv(db, [{"Item": "Product A", "Quantity": "10", "Income": "100.00"}])
    write_csv(review, [
        {"Row": "1", "Item": "Product A", "Quantity": "2", "Income": "15,50", "Approved": "yes"}
    ])
    original = db.read_bytes()
    path, count = apply_review(review, db, out)
    assert path == out
    assert count == 1
    assert db.read_bytes() == original
    loaded = pd.read_csv(out)
    assert loaded.loc[0, "Quantity"] == 8
    assert loaded.loc[0, "Income"] == 115.50


def test_missing_approval_fails_without_writing(tmp_path):
    db, review, out = (tmp_path / p for p in ("db.csv", "review.csv", "out.csv"))
    write_csv(db, [{"Item": "A", "Quantity": "10", "Income": "0"}])
    write_csv(review, [{"Item": "A", "Quantity": "2", "Income": "1.00", "Approved": "no"}])
    with pytest.raises(ValueError, match="Approved=yes"):
        apply_review(review, db, out)
    assert not out.exists()


def test_negative_stock_fails_without_writing(tmp_path):
    db, review, out = (tmp_path / p for p in ("db.csv", "review.csv", "out.csv"))
    write_csv(db, [{"Item": "A", "Quantity": "1", "Income": "0"}])
    write_csv(review, [{"Item": "A", "Quantity": "2", "Income": "1.00", "Approved": "yes"}])
    with pytest.raises(ValueError, match="poniżej zera"):
        apply_review(review, db, out)
    assert not out.exists()


def test_unknown_product_fails(tmp_path):
    db, review, out = (tmp_path / p for p in ("db.csv", "review.csv", "out.csv"))
    write_csv(db, [{"Item": "A", "Quantity": "10", "Income": "0"}])
    write_csv(review, [{"Item": "X", "Quantity": "1", "Income": "1.00", "Approved": "yes"}])
    with pytest.raises(ValueError, match="nie znaleziono produktu"):
        apply_review(review, db, out)


def test_duplicate_database_names_fails(tmp_path):
    db, review, out = (tmp_path / p for p in ("db.csv", "review.csv", "out.csv"))
    write_csv(db, [
        {"Item": "A", "Quantity": "10", "Income": "0"},
        {"Item": " a ", "Quantity": "10", "Income": "0"}
    ])
    write_csv(review, [{"Item": "A", "Quantity": "1", "Income": "1.00", "Approved": "yes"}])
    with pytest.raises(ValueError, match="nieunikalne"):
        apply_review(review, db, out)


def test_fully_blank_review_rows_are_ignored(tmp_path):
    db, review, out = (tmp_path / p for p in ("db.csv", "review.csv", "out.csv"))
    write_csv(db, [{"Item": "A", "Quantity": "5", "Income": "1.00"}])
    write_csv(review, [
        {"Item": "", "Quantity": "", "Income": "", "Approved": "no"},
        {"Item": "A", "Quantity": "1", "Income": "2.00", "Approved": "yes"},
    ])
    _, count = apply_review(review, db, out)
    assert count == 1


def test_output_must_not_overwrite_review_even_with_overwrite_flag(tmp_path):
    db = tmp_path / "db.csv"
    review = tmp_path / "review.csv"
    write_csv(db, [{"Item": "A", "Quantity": "10", "Income": "0"}])
    write_csv(review, [{"Item": "A", "Quantity": "2", "Income": "1.00", "Approved": "yes"}])
    original = review.read_bytes()
    with pytest.raises(ValueError, match="review.csv"):
        apply_review(review, db, review, overwrite=True)
    assert review.read_bytes() == original
