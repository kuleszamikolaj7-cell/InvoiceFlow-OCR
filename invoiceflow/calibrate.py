"""Interaktywny kreator szablonów z OpenCV: wskazanie pól pierwszego wiersza."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
from pdf2image import convert_from_path

from .scanner import load_template


def create_template(
    pdf_path: Path,
    out_path: Path,
    *,
    rows: int,
    row_step: int,
    dpi: int = 200,
    language: str = "eng",
    poppler_bin: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Otwiera obraz i prosi o zaznaczenie trzech prostokątów przez cv2.selectROI.

    Współrzędne dotyczą PIERWSZEGO wiersza i tego samego DPI co w szablonie.
    """
    pdf_path = Path(pdf_path)
    out_path = Path(out_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Brak PDF: {pdf_path}")
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"Szablon już istnieje: {out_path} (użyj --overwrite)")
    if any(type(n) is not int or n <= 0 for n in (rows, row_step, dpi)):
        raise ValueError("rows, row_step oraz dpi muszą być dodatnimi liczbami całkowitymi")
    try:
        pages = convert_from_path(str(pdf_path), first_page=1, last_page=1, dpi=dpi,
                                  poppler_path=str(poppler_bin) if poppler_bin else None)
    except Exception as exc:
        raise RuntimeError("Nie można otworzyć PDF. Sprawdź Poppler i plik wejściowy.") from exc
    if len(pages) != 1:
        raise ValueError("Nie udało się odczytać pierwszej strony PDF")
    import numpy as np
    image = cv2.cvtColor(np.array(pages[0].convert("RGB")), cv2.COLOR_RGB2BGR)
    pages[0].close()
    height, width = image.shape[:2]
    # Zmniejszenie podglądu, aby zmieścić go w oknie (współrzędne przeliczamy na oryginał).
    scale = min(1.0, 1200 / width, 780 / height)
    display = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
    coords = {}
    try:
        for field, label in (("product", "NAZWA PRODUKTU"), ("amount", "ILOSC"), ("price", "WARTOSC POZYCJI")):
            window_name = f"{label}: zaznacz pierwsze pole, ENTER zatwierdza, ESC przerywa"
            try:
                x, y, w, h = cv2.selectROI(window_name, display, fromCenter=False, showCrosshair=True)
            except cv2.error as exc:
                raise RuntimeError("Brak graficznej obsługi okien OpenCV. Uruchom kreator na komputerze z pulpitem.") from exc
            finally:
                cv2.destroyAllWindows()
            if w <= 0 or h <= 0:
                raise ValueError(f"Nie wybrano obszaru: {field}")
            xx, yy = round(x / scale), round(y / scale)
            ww, hh = round(w / scale), round(h / scale)
            if xx + ww > width or yy + hh > height:
                raise ValueError(f"Wybrany obszar wychodzi poza obraz: {field}")
            coords[field] = [xx, yy, ww, hh]
    finally:
        cv2.destroyAllWindows()

    template = {
        "description": f"Szablon utworzony ręcznie z {pdf_path.name}; ten sam układ na wszystkich stronach",
        "dpi": dpi, "language": language, "rows": rows,
        "row_step": row_step, "confidence_threshold": 65,
        "coordinates": coords,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Zweryfikuj wygenerowany dokument zanim zapiszesz wynik końcowy.
    import tempfile
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=out_path.parent, suffix=".json", encoding="utf-8", delete=False) as stream:
            temp_name = Path(stream.name)
            json.dump(template, stream, ensure_ascii=False, indent=2)
        load_template(temp_name)
        temp_name.replace(out_path)
    finally:
        if temp_name and temp_name.exists():
            temp_name.unlink()
    return out_path
