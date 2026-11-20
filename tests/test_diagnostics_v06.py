"""Regression tests for issues discovered while running on Windows."""
from pathlib import Path

import pandas as pd
import pytest

from invoiceflow.diagnostics import describe_item_name_errors, inspect_inventory_csv
from invoiceflow.environment import check_environment, render_environment_report
from invoiceflow.inventory import apply_review


def test_duplicate_spelling_and_blank_show_csv_line_numbers():
    errors = describe_item_name_errors([" Product A ", "product a", "", "Product B"])
    assert "Wiersz CSV 3" in errors[0] and "wiersza CSV 2" in errors[0]
    assert "Wiersz CSV 4: pusta" in errors[1]


def test_clean_csv_passes(tmp_path):
    path = tmp_path / "inventory.csv"
    pd.DataFrame({"Item": ["A", "B"], "Quantity": [3, 5], "Income": ["10.00", "0.00"]}).to_csv(path, index=False)
    assert inspect_inventory_csv(path) == 2


def test_csv_missing_required_header_explains_separator(tmp_path):
    path = tmp_path / "inventory.csv"
    path.write_text("Item;Quantity;Income\nA;3;10.00\n", encoding="utf-8")
    with pytest.raises(ValueError, match="separator: przecinek"):
        inspect_inventory_csv(path)


def test_problematic_csv_reports_rows(tmp_path):
    path = tmp_path / "inventory.csv"
    path.write_text("Item,Quantity,Income\nX,1,1.00\n x ,1,1.00\n,1,1.00\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        inspect_inventory_csv(path)
    assert "Wiersz CSV 3" in str(e.value)
    assert "Wiersz CSV 4" in str(e.value)


def test_engine_never_exports_invalid_product_names(tmp_path):
    db = tmp_path / "bad.csv"
    review = tmp_path / "review.csv"
    out = tmp_path / "out.csv"
    db.write_text("Item,Quantity,Income\nItem,10,0.00\n item ,4,0.00\n", encoding="utf-8")
    review.write_text("Row,Item,Quantity,Income,Approved\n1:1,Item,1,2.00,yes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Wiersz CSV 3"):
        apply_review(review, db, out)
    assert not out.exists()


def test_environment_reports_selected_missing_binaries(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    results = check_environment(poppler_bin=fake, tesseract_bin=fake / "tesseract.exe")
    assert not results[1][0]
    assert not results[2][0]
    assert not results[3][0]
    report = render_environment_report(results)
    assert "BRAK: Poppler / pdfinfo" in report
    assert "BRAK: Tesseract" in report


def test_environment_custom_paths(tmp_path):
    for filename in ("pdfinfo.exe", "pdftoppm.exe", "tesseract.exe", "pdfinfo", "pdftoppm"):
        (tmp_path / filename).touch()
    results = check_environment(poppler_bin=tmp_path, tesseract_bin=tmp_path / "tesseract.exe")
    assert all(ok for ok, _ in results[1:])
