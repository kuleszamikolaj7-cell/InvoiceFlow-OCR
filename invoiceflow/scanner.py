"""PDF → obrazy stron → OCR pól według wybranego szablonu → review CSV.

v0.3: tryb wielostronicowy i oddzielny raport diagnostyczny. Nadal jest to OCR
SZABLONOWY, a nie uniwersalny detektor dowolnego układu tabel.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import cv2
import pytesseract
from pdf2image import convert_from_path, pdfinfo_from_path
from pytesseract import Output

from .review import save_review
from .inventory import parse_number

FIELDS = ("product", "amount", "price")
FIELD_LABELS = {"product": "Item", "amount": "Quantity", "price": "Income"}
DEFAULT_MAX_PAGES = 15


def load_template(path: Path) -> dict:
    """Wczytuje i waliduje szablon; zachowuje zgodność z formatem v0.2."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Nie znaleziono szablonu: {path}")
    with path.open("r", encoding="utf-8") as stream:
        template = json.load(stream)
    try:
        rows, step, dpi = (template[key] for key in ("rows", "row_step", "dpi"))
        coords = template["coordinates"]
        for field in FIELDS:
            rectangle = coords[field]
            if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4 or any(type(n) is not int for n in rectangle):
                raise ValueError(f"Niepoprawne współrzędne: {field}")
            x, y, w, h = rectangle
            if min(x, y) < 0 or min(w, h) <= 0:
                raise ValueError(f"Niepoprawny obszar: {field}")
        if not all(type(n) is int and n > 0 for n in (rows, step, dpi)):
            raise ValueError("rows, row_step i dpi muszą być dodatnimi liczbami całkowitymi")
        if not isinstance(template["language"], str) or not re.fullmatch(
            r"[a-z]{3}(\+[a-z]{3})*", template["language"]
        ):
            raise ValueError("Niepoprawny język OCR w szablonie")
        threshold = template.get("confidence_threshold", 65)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
            raise ValueError("confidence_threshold musi być liczbą 0–100")
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Niekompletny szablon: {exc}") from exc
    return template


def _configure_tesseract(executable: Path | None):
    if executable:
        if not executable.is_file():
            raise FileNotFoundError(f"Nie znaleziono Tesseract: {executable}")
        pytesseract.pytesseract.tesseract_cmd = str(executable)
    elif Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").is_file():
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _ocr_crop(crop, field: str, language: str) -> tuple[str, float | None]:
    """Zwraca tekst i średnią ufność ważoną długością słów (nie prawdopodobieństwo poprawności)."""
    psm = 3 if field == "product" else 6
    if field != "product":
        crop = cv2.GaussianBlur(crop, (5, 5), 0)
    data = pytesseract.image_to_data(
        crop,
        output_type=Output.DICT,
        config=f"-l {language} --oem 1 --psm {psm}",
    )
    pieces = []
    weighted_total = 0.0
    weight_total = 0
    for word, raw_confidence in zip(data["text"], data["conf"]):
        word = str(word).strip()
        if not word:
            continue
        pieces.append(word)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            weight = max(1, len(word))
            weighted_total += confidence * weight
            weight_total += weight
    return " ".join(pieces), round(weighted_total / weight_total, 1) if weight_total else None


def _write_json_atomically(path: Path, payload: dict):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".quality-", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _get_page_count(pdf_path: Path, poppler_bin: Path | None) -> int:
    info = pdfinfo_from_path(
        str(pdf_path), poppler_path=str(poppler_bin) if poppler_bin else None
    )
    count = int(info["Pages"])
    if count <= 0:
        raise ValueError("Dokument PDF nie zawiera stron")
    return count


def scan_invoice(
    pdf_path: Path,
    template_path: Path,
    output_dir: Path,
    poppler_bin: Path | None = None,
    tesseract_bin: Path | None = None,
    overwrite: bool = False,
    all_pages: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    omit_empty: bool = False,
) -> Path:
    """Skanuje jedną lub wszystkie strony szablonowej faktury.

    Stałe współrzędne są stosowane na KAŻDEJ stronie. Dla PDF o innym układzie
    trzeba przygotować osobny szablon, a wynik zawsze ręcznie zweryfikować.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Nie znaleziono faktury: {pdf_path}")
    if type(max_pages) is not int or max_pages <= 0 or max_pages > 100:
        raise ValueError("max_pages musi być liczbą całkowitą z zakresu 1–100")
    template_path = Path(template_path)
    template = load_template(template_path)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pdf_path.stem).strip("_") or "invoice"
    work_dir = Path(output_dir) / safe_name
    review_path = work_dir / "review.csv"
    if review_path.exists() and not overwrite:
        raise FileExistsError(f"{review_path} już istnieje. Aby zastąpić wynik, dodaj --overwrite.")
    _configure_tesseract(tesseract_bin)

    try:
        page_count = _get_page_count(pdf_path, poppler_bin) if all_pages else 1
    except Exception as exc:
        raise RuntimeError("Nie można odczytać liczby stron PDF. Sprawdź Poppler oraz PDF.") from exc
    if page_count > max_pages:
        raise ValueError(
            f"Faktura ma {page_count} stron; limit to {max_pages}. "
            "Podaj większe --max-pages (maksymalnie 100) lub skanuj tylko pierwszą stronę."
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    warnings = []
    page_reports = []
    threshold = template.get("confidence_threshold", 65)
    for page_number in range(1, page_count + 1):
        try:
            converted = convert_from_path(
                str(pdf_path), dpi=template["dpi"],
                poppler_path=str(poppler_bin) if poppler_bin else None,
                first_page=page_number, last_page=page_number,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Nie można przekonwertować strony {page_number}. "
                "Sprawdź Poppler, PDF i dostępne zasoby pamięci."
            ) from exc
        if len(converted) != 1:
            raise RuntimeError(f"Konwersja strony {page_number} nie zwróciła jednego obrazu")
        image_name = "invoice.jpg" if page_number == 1 else f"invoice_p{page_number:03d}.jpg"
        image_path = work_dir / image_name
        converted[0].save(image_path, "JPEG")
        converted[0].close()
        image = cv2.imread(str(image_path))
        if image is None:
            raise RuntimeError(f"Nie można otworzyć obrazu: {image_path}")
        height, width = image.shape[:2]
        marked = image.copy()
        page_data = {field: [] for field in FIELDS}
        confidence_data = {field: [] for field in FIELDS}
        for field in FIELDS:
            x, y, w, h = template["coordinates"][field]
            for row_number in range(template["rows"]):
                top = y + row_number * template["row_step"]
                if x + w > width or top + h > height:
                    raise ValueError(
                        f"Obszar {field}[{row_number}] strony {page_number} "
                        f"wychodzi poza obraz ({width} × {height} px). "
                        "Sprawdź DPI i szablon."
                    )
                crop = image[top:top + h, x:x + w]
                color = {"product": (120, 200, 45), "amount": (230, 155, 40), "price": (75, 85, 235)}[field]
                cv2.rectangle(marked, (x, top), (x + w, top + h), color, 2)
                crop_name = (f"{field}{row_number}.jpg" if page_number == 1
                             else f"{field}_p{page_number:03d}_{row_number}.jpg")
                crop_path = work_dir / crop_name
                if not cv2.imwrite(str(crop_path), crop):
                    raise OSError(f"Nie udało się zapisać wycinka: {crop_path}")
                try:
                    text, confidence = _ocr_crop(crop, field, template["language"])
                except pytesseract.TesseractNotFoundError as exc:
                    raise RuntimeError(
                        "Nie znaleziono Tesseract. Dodaj go do PATH lub podaj --tesseract-bin."
                    ) from exc
                except pytesseract.TesseractError as exc:
                    raise RuntimeError(f"Błąd OCR: strona {page_number}, {field}[{row_number}]: {exc}") from exc
                page_data[field].append(text)
                confidence_data[field].append(confidence)

        layout_name = "layout.jpg" if page_number == 1 else f"layout_p{page_number:03d}.jpg"
        if not cv2.imwrite(str(work_dir / layout_name), marked):
            raise OSError(f"Nie udało się zapisać podglądu: {layout_name}")

        nonempty_count = 0
        for i in range(template["rows"]):
            cells = {FIELD_LABELS[field]: page_data[field][i] for field in FIELDS}
            is_active = any(text.strip() for text in cells.values())
            if not is_active and omit_empty:
                continue
            row_id = str(i + 1) if page_count == 1 else f"{page_number}:{i + 1}"
            rows.append({"Row": row_id, **cells, "Approved": "no"})
            if not is_active:
                continue
            nonempty_count += 1
            for field in FIELDS:
                text = page_data[field][i]
                confidence = confidence_data[field][i]
                label = FIELD_LABELS[field]
                if not text.strip():
                    warnings.append({
                        "row": row_id, "page": page_number, "field": label,
                        "kind": "missing", "message": "Nie rozpoznano pola",
                    })
                elif confidence is None or confidence < threshold:
                    warnings.append({
                        "row": row_id, "page": page_number, "field": label,
                        "kind": "low_confidence", "confidence": confidence,
                        "message": f"Pewność OCR: {confidence if confidence is not None else chr(63)} (próg {threshold})",
                    })
                if text.strip() and field in ("amount", "price"):
                    try:
                        number = parse_number(text)
                        if number < 0 or (field == "amount" and number == 0):
                            raise ValueError("wartość nieprawidłowa")
                        if field == "price" and number.as_tuple().exponent < -2:
                            raise ValueError("kwota zawiera więcej niż 2 miejsca po przecinku")
                    except ValueError:
                        warnings.append({
                            "row": row_id, "page": page_number, "field": label,
                            "kind": "invalid_number", "message": f"Sprawdź format liczby: {text!r}",
                        })
        page_reports.append({"page": page_number, "image": image_name, "layout": layout_name, "nonempty_rows": nonempty_count})

    if not rows:
        raise ValueError("Nie znaleziono żadnych wierszy; sprawdź szablon i tryb pomijania pustych")
    digest = hashlib.sha256()
    with pdf_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    report = {
        "version": 1,
        "source_file": pdf_path.name,
        "source_sha256": digest.hexdigest(),
        "template_file": template_path.name,
        "mode": "all_pages" if all_pages else "first_page",
        "total_pages_scanned": page_count,
        "confidence_threshold": threshold,
        "note": "Pewność OCR to wskaźnik silnika, nie gwarancja poprawnego odczytu. Zawsze porównaj wynik z fakturą.",
        "pages": page_reports,
        "warnings": warnings,
    }
    # Zapis review jest atomowy; błędne lub przerwane skanowanie nie aktualizuje magazynu.
    # Raport zapisywany przed review, aby GUI miało do niego dostęp przy zakończeniu skanowania.
    _write_json_atomically(work_dir / "quality.json", report)
    save_review(review_path, rows)
    if overwrite:
        # Usuń tylko nasze wygenerowane pliki stron, które nie występują w nowym skanie.
        used_images = {page["image"] for page in page_reports} | {page["layout"] for page in page_reports}
        for pattern in ("invoice_p[0-9][0-9][0-9].jpg", "layout_p[0-9][0-9][0-9].jpg"):
            for stale in work_dir.glob(pattern):
                if stale.name not in used_images:
                    stale.unlink()
    return review_path


def load_quality_report(review_path: Path) -> dict | None:
    """Zwraca diagnostykę jeśli istnieje; starsze review z v0.2 pozostają kompatybilne."""
    report_path = Path(review_path).parent / "quality.json"
    if not report_path.is_file():
        return None
    try:
        with report_path.open("r", encoding="utf-8") as stream:
            report = json.load(stream)
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and isinstance(report.get("warnings"), list) else None
