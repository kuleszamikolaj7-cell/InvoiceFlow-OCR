"""Nowe testy v0.3: wiele stron, raport jakości, limity i nadpisywanie."""
import json

import pytest
from PIL import Image

from invoiceflow import scanner
from invoiceflow.review import load_review


def _make_pdf_and_template(tmp_path):
    pdf = tmp_path / "multi.pdf"
    pdf.write_bytes(b"test source")
    template = tmp_path / "template.json"
    template.write_text(json.dumps({
        "rows": 2, "row_step": 50, "dpi": 200, "language": "eng",
        "confidence_threshold": 70,
        "coordinates": {
            "product": [10, 10, 100, 30],
            "amount": [200, 10, 60, 30],
            "price": [300, 10, 60, 30],
        },
    }))
    return pdf, template


def _fake_pdf(monkeypatch, page_count=2):
    monkeypatch.setattr(scanner, "pdfinfo_from_path", lambda *args, **kwargs: {"Pages": page_count})
    calls = []

    def converter(*args, **kwargs):
        calls.append((kwargs["first_page"], kwargs["last_page"]))
        return [Image.new("RGB", (500, 500), "white")]

    monkeypatch.setattr(scanner, "convert_from_path", converter)
    return calls


def _fake_ocr(monkeypatch, low_conf=False):
    state = {field: 0 for field in scanner.FIELDS}

    def ocr(image, field, language):
        state[field] += 1
        pos = state[field]
        if pos == 1:
            val = {"product": "Produkt A", "amount": "2", "price": "12,50"}[field]
            return val, 45.0 if low_conf and field == "product" else 98.0
        if pos == 3:
            return {"product": "Produkt B", "amount": "1", "price": "abc"}[field], 99.0
        return "", None

    monkeypatch.setattr(scanner, "_ocr_crop", ocr)


def test_multipage_keeps_page_identity_and_quality(tmp_path, monkeypatch):
    pdf, template = _make_pdf_and_template(tmp_path)
    calls = _fake_pdf(monkeypatch)
    _fake_ocr(monkeypatch, low_conf=True)
    review_path = scanner.scan_invoice(pdf, template, tmp_path / "output", all_pages=True)
    rows = load_review(review_path)
    assert len(rows) == 4
    assert [row["Row"] for row in rows] == ["1:1", "1:2", "2:1", "2:2"]
    assert [row["Item"] for row in rows] == ["Produkt A", "", "Produkt B", ""]
    assert all(row["Approved"] == "no" for row in rows)
    assert calls == [(1, 1), (2, 2)]
    assert (review_path.parent / "invoice.jpg").is_file()
    assert (review_path.parent / "invoice_p002.jpg").is_file()
    assert (review_path.parent / "layout.jpg").is_file()
    assert (review_path.parent / "layout_p002.jpg").is_file()
    assert (review_path.parent / "product_p002_0.jpg").is_file()
    report = scanner.load_quality_report(review_path)
    assert report["total_pages_scanned"] == 2
    assert [p["nonempty_rows"] for p in report["pages"]] == [1, 1]
    assert any(w["kind"] == "low_confidence" and w["row"] == "1:1" for w in report["warnings"])
    assert any(w["kind"] == "invalid_number" and w["row"] == "2:1" for w in report["warnings"])


def test_omit_empty_preserves_original_row_numbers(tmp_path, monkeypatch):
    pdf, template = _make_pdf_and_template(tmp_path)
    _fake_pdf(monkeypatch)
    _fake_ocr(monkeypatch)
    path = scanner.scan_invoice(pdf, template, tmp_path / "output", all_pages=True, omit_empty=True)
    rows = load_review(path)
    assert [r["Row"] for r in rows] == ["1:1", "2:1"]


def test_default_scans_only_first_page(tmp_path, monkeypatch):
    pdf, template = _make_pdf_and_template(tmp_path)
    calls = _fake_pdf(monkeypatch)
    _fake_ocr(monkeypatch)
    monkeypatch.setattr(scanner, "pdfinfo_from_path", lambda **kwargs: pytest.fail("Should not check count in first-page mode"))
    path = scanner.scan_invoice(pdf, template, tmp_path / "output")
    assert calls == [(1, 1)]
    assert [r["Row"] for r in load_review(path)] == ["1", "2"]


def test_page_limit_does_not_write_review(tmp_path, monkeypatch):
    pdf, template = _make_pdf_and_template(tmp_path)
    _fake_pdf(monkeypatch, page_count=16)
    with pytest.raises(ValueError, match="limit"):
        scanner.scan_invoice(pdf, template, tmp_path / "output", all_pages=True)
    assert not (tmp_path / "output" / "multi" / "review.csv").exists()


def test_overwrite_removes_old_preview_pages(tmp_path, monkeypatch):
    pdf, template = _make_pdf_and_template(tmp_path)
    _fake_pdf(monkeypatch)
    _fake_ocr(monkeypatch)
    output = tmp_path / "output"
    path = scanner.scan_invoice(pdf, template, output, all_pages=True)
    assert (path.parent / "invoice_p002.jpg").exists()
    _fake_ocr(monkeypatch)
    scanner.scan_invoice(pdf, template, output, overwrite=True)
    assert not (path.parent / "invoice_p002.jpg").exists()
    assert not (path.parent / "layout_p002.jpg").exists()


def test_template_rejects_invalid_threshold(tmp_path):
    _, template = _make_pdf_and_template(tmp_path)
    data = json.loads(template.read_text())
    data["confidence_threshold"] = 111
    template.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="confidence_threshold"):
        scanner.load_template(template)


def test_ocr_calculates_weighted_confidence(monkeypatch):
    monkeypatch.setattr(scanner.pytesseract, "image_to_data", lambda *a, **kw: {
        "text": ["A", "BBBB", ""], "conf": [50, 100, -1]
    })
    result, confidence = scanner._ocr_crop(None, "product", "eng")
    assert result == "A BBBB"
    assert confidence == 90.0
