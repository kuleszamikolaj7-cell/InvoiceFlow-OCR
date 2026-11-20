import json

import cv2
from PIL import Image

from invoiceflow import calibrate
from invoiceflow.scanner import load_template


def test_template_calibrator_saves_selected_coordinates(tmp_path, monkeypatch):
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"pdf")
    monkeypatch.setattr(calibrate, "convert_from_path", lambda *a, **kw: [Image.new("RGB", (600, 500), "white")])
    rects = iter([(10, 100, 200, 30), (250, 100, 40, 30), (320, 100, 60, 30)])
    monkeypatch.setattr(cv2, "selectROI", lambda *a, **kw: next(rects))
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    target = tmp_path / "new.json"
    calibrate.create_template(pdf, target, rows=7, row_step=35)
    result = load_template(target)
    assert result["rows"] == 7
    assert result["coordinates"]["price"] == [320, 100, 60, 30]
    assert result["row_step"] == 35


def test_calibrator_does_not_overwrite_existing_template(tmp_path):
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"pdf")
    target = tmp_path / "template.json"
    target.write_text("unchanged")
    import pytest
    with pytest.raises(FileExistsError):
        calibrate.create_template(pdf, target, rows=7, row_step=35)
    assert target.read_text() == "unchanged"
