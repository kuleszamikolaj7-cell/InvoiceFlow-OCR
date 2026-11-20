"""Human-readable, side-effect-free checks for OCR dependencies.

Does not download or install software. GUI uses the same information as `doctor`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def check_environment(*, poppler_bin: Path | None = None,
                      tesseract_bin: Path | None = None) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    version_ok = sys.version_info >= (3, 12)
    results.append((version_ok, f"Python {sys.version_info.major}.{sys.version_info.minor}"
                    + ("" if version_ok else " (zalecany 3.12+)")))

    folder = Path(poppler_bin) if poppler_bin else None
    for executable in ("pdfinfo", "pdftoppm"):
        binary = executable + (".exe" if sys.platform == "win32" else "")
        found = str(folder / binary) if folder and (folder / binary).is_file() else (
            shutil.which(binary) if not folder else None
        )
        results.append((bool(found), f"Poppler / {executable}: " + (found or "nie znaleziono; podaj folder Poppler w ustawieniach")))

    if tesseract_bin:
        candidate = Path(tesseract_bin)
        tess = str(candidate) if candidate.is_file() else None
    else:
        tess = shutil.which("tesseract")
        if not tess and sys.platform == "win32":
            common = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            if common.is_file():
                tess = str(common)
    results.append((bool(tess), "Tesseract: " + (tess or "nie znaleziono; wskaż tesseract.exe")))
    return results


def render_environment_report(rows: list[tuple[bool, str]]) -> str:
    return "\n".join(("OK: " if good else "BRAK: ") + message for good, message in rows)
