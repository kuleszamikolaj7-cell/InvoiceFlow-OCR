import csv

import pytest

from invoiceflow.review import FIELDS, get_review_stats, load_review, save_review


def sample_rows():
    return [
        {"Row": "1", "Item": "Żarówka LED", "Quantity": "2", "Income": "49,90", "Approved": "yes"},
        {"Row": "2", "Item": "", "Quantity": "", "Income": "", "Approved": "no"},
    ]


def test_round_trip_preserves_polish_characters_and_empty_rows(tmp_path):
    path = tmp_path / "review.csv"
    save_review(path, sample_rows())
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_review(path) == sample_rows()
    assert get_review_stats(load_review(path)) == (1, 1)


def test_rewrite_replaces_content(tmp_path):
    path = tmp_path / "review.csv"
    save_review(path, sample_rows())
    updated = sample_rows()
    updated[0]["Quantity"] = "3"
    updated[0]["Approved"] = "no"
    save_review(path, updated)
    assert load_review(path) == updated
    assert len(list(tmp_path.glob("*.tmp"))) == 0


def test_invalid_approval_does_not_overwrite_original(tmp_path):
    path = tmp_path / "review.csv"
    save_review(path, sample_rows())
    before = path.read_bytes()
    bad = sample_rows()
    bad[0]["Approved"] = "maybe"
    with pytest.raises(ValueError, match="Approved"):
        save_review(path, bad)
    assert path.read_bytes() == before


def test_missing_columns_rejected(tmp_path):
    path = tmp_path / "review.csv"
    path.write_text("Item,Quantity\nX,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="kolumny"):
        load_review(path)


def test_extra_columns_in_row_rejected(tmp_path):
    path = tmp_path / "review.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(FIELDS) + "\n1,A,2,10,yes,extra\n")
    with pytest.raises(ValueError, match="za dużo"):
        load_review(path)


def test_empty_row_file_rejected(tmp_path):
    path = tmp_path / "review.csv"
    path.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="żadnych"):
        load_review(path)
