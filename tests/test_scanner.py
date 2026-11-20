import json

import pytest

from invoiceflow.scanner import load_template


def test_original_template_loads():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    template = load_template(base / "templates" / "invoice1.json")
    assert template["rows"] == 17
    assert template["coordinates"]["product"] == [90, 790, 660, 48]


def test_template_rejects_missing_field(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"rows": 17, "row_step": 50, "dpi": 200, "language": "eng", "coordinates": {}}))
    with pytest.raises(ValueError, match="Niekompletny szablon"):
        load_template(path)


def test_scan_preserves_alignment_and_saves_images(tmp_path, monkeypatch):
    """Test przepływu bez realnego PDF/Tesseract: puste OCR nie przesuwa wierszy."""
    from PIL import Image
    from invoiceflow import scanner

    pdf_path = tmp_path / "Invoice1.pdf"
    pdf_path.write_bytes(b"test PDF fixture: konwersja jest zamockowana")
    monkeypatch.setattr(scanner, "convert_from_path", lambda *a, **kw: [Image.new("RGB", (1700, 2000), "white")])

    calls = {"product": 0, "amount": 0, "price": 0}

    def fake_ocr(crop, field, lang):
        calls[field] += 1
        pos = calls[field]
        if pos == 1:
            return {"product": "Product A", "amount": "2", "price": "10.00"}[field], 99.0
        if pos == 2:
            return "", None   # kompletnie pusty wiersz
        if pos == 3:
            return {"product": "Product B", "amount": "1", "price": "5.50"}[field], 99.0
        return "", None

    monkeypatch.setattr(scanner, "_ocr_crop", fake_ocr)
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({
        "rows": 3,
        "row_step": 50,
        "dpi": 200,
        "language": "eng",
        "coordinates": {
            "product": [90, 790, 660, 48],
            "amount": [1250, 790, 200, 48],
            "price": [1480, 790, 140, 48],
        },
    }))
    review = scanner.scan_invoice(pdf_path, template_path, tmp_path / "output")
    import csv
    with review.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert [row["Item"] for row in rows] == ["Product A", "", "Product B"]
    assert [row["Quantity"] for row in rows] == ["2", "", "1"]
    assert [row["Income"] for row in rows] == ["10.00", "", "5.50"]
    assert all(row["Approved"] == "no" for row in rows)
    assert (review.parent / "invoice.jpg").is_file()
    assert (review.parent / "product0.jpg").is_file()
    assert (review.parent / "amount1.jpg").is_file()
    assert (review.parent / "price2.jpg").is_file()
    with pytest.raises(FileExistsError):
        scanner.scan_invoice(pdf_path, template_path, tmp_path / "output")
