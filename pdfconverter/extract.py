"""PDF extraction: tables, text, scanned-page detection and OCR fallback."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pdfplumber

from .errors import CorruptPDFError, PDFProcessingError
from .pdfcheck import validate_pdf

OCR_DPI = 250
LOW_OCR_CONFIDENCE = 60.0
# OCR is slow, so cap how many pages one request may OCR (override with env).
MAX_OCR_PAGES = int(os.environ.get("MAX_OCR_PAGES", "25"))


@dataclass
class ExtractedTable:
    page: int
    index: int
    header: List[str]
    rows: List[List[str]]
    bbox: Optional[tuple] = None


@dataclass
class ExtractedDocument:
    filename: str
    page_count: int
    tables: List[ExtractedTable] = field(default_factory=list)
    page_text: Dict[int, str] = field(default_factory=dict)
    ocr_pages: List[int] = field(default_factory=list)
    scanned_pages: List[int] = field(default_factory=list)  # image-only, not OCR'd
    page_info: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    ocr_available: bool = False
    kind: str = "text"  # text | scanned | mixed | empty
    # Filled in by the invoice step (or restored from an export request).
    invoice_data: dict = field(default_factory=dict)
    invoice_line_items: List[dict] = field(default_factory=list)
    invoice_warnings: List[dict] = field(default_factory=list)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _warn(doc: ExtractedDocument, level: str, code: str, message: str,
          page: Optional[int] = None) -> None:
    doc.warnings.append(
        {"level": level, "code": code, "message": message, "page": page}
    )


def _clean(cell) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def _looks_like_header(row: List[str]) -> bool:
    filled = [c for c in row if c]
    if not filled:
        return False

    numeric = sum(
        bool(re.fullmatch(r"[-+$€£]?[\d,]+(\.\d+)?%?", c))
        for c in filled
    )
    return numeric / len(filled) < 0.5


def _unique_headers(header: List[str]) -> List[str]:
    seen, output = {}, []

    for i, value in enumerate(header):
        value = value or f"Column {i + 1}"

        if value in seen:
            seen[value] += 1
            value = f"{value} ({seen[value]})"
        else:
            seen[value] = 1

        output.append(value)

    return output


def _normalise(raw: List[List]) -> Optional[tuple]:
    rows = [[_clean(c) for c in row] for row in raw]
    rows = [row for row in rows if any(row)]

    if len(rows) < 2:
        return None

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    keep = [i for i in range(width) if any(row[i] for row in rows)]
    rows = [[row[i] for i in keep] for row in rows]

    if _looks_like_header(rows[0]):
        header, body = rows[0], rows[1:]
    else:
        header = [f"Column {i + 1}" for i in range(len(rows[0]))]
        body = rows

    return _unique_headers(header), body


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
def _configure_tesseract(pytesseract) -> None:
    executable = os.environ.get("TESSERACT_CMD")
    if executable:
        pytesseract.pytesseract.tesseract_cmd = executable


def ocr_available() -> bool:
    """True when pytesseract AND the Tesseract program are both usable."""
    try:
        import pytesseract

        _configure_tesseract(pytesseract)
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_page(page) -> Tuple[str, Optional[float]]:
    """OCR one page. Returns (text, mean word confidence 0-100 or None)."""
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import ImageOps
    except ImportError as exc:
        raise RuntimeError(
            "OCR packages are missing. Install pytesseract and pillow."
        ) from exc

    _configure_tesseract(pytesseract)

    try:
        image = page.to_image(resolution=OCR_DPI).original.convert("L")
        image = ImageOps.autocontrast(image)

        data = pytesseract.image_to_data(
            image,
            lang=os.environ.get("TESSERACT_LANG", "eng"),
            config="--psm 6",
            output_type=Output.DICT,
        )
    except Exception as exc:
        raise RuntimeError(
            "OCR failed. Check that Tesseract OCR is installed and its "
            "executable path is correct (TESSERACT_CMD)."
        ) from exc

    lines: Dict[tuple, List[str]] = {}
    confidences: List[float] = []

    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)

        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0:
            confidences.append(conf)

    text = "\n".join(" ".join(words) for words in lines.values()).strip()
    mean_conf = round(sum(confidences) / len(confidences), 1) if confidences else None

    return text, mean_conf


def _page_is_blank(page) -> bool:
    """No text, images or vector drawing at all -> nothing worth OCR-ing."""
    try:
        return not (page.images or page.rects or page.curves or page.lines)
    except Exception:
        return False


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------
def extract_pdf(
    path: str,
    pages: Optional[List[int]] = None,
    enable_ocr: bool = True,
    max_pages: Optional[int] = None,
) -> ExtractedDocument:
    """
    Extract tables and text from a PDF.

    Text-based extraction is attempted first; pages without a text layer are
    OCR'd when Tesseract is available. Raises a PDFProcessingError subclass
    for corrupt, password-protected or unsupported files. Problems with
    individual pages become warnings instead of failing the whole file.
    """
    page_total = validate_pdf(path, max_pages=max_pages)

    engine_ok = ocr_available()
    ocr_ready = enable_ocr and engine_ok
    doc = ExtractedDocument(
        filename=os.path.basename(path),
        page_count=page_total,
        ocr_available=engine_ok,
    )

    ocr_budget = MAX_OCR_PAGES
    ocr_broken = False
    failed_pages = 0
    processed = 0

    try:
        with pdfplumber.open(path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                if pages and pno not in pages:
                    continue

                processed += 1

                try:
                    text = page.extract_text() or ""
                    method, confidence = "text", None

                    if not text.strip():
                        text, method, confidence, ocr_ok = _handle_textless_page(
                            doc, page, pno, ocr_ready and not ocr_broken, ocr_budget
                        )
                        if method == "ocr":
                            ocr_budget -= 1
                        if ocr_ok is False:
                            ocr_broken = True

                    doc.page_text[pno] = text
                    doc.page_info.append({
                        "page": pno,
                        "method": method,
                        "chars": len(text),
                        "confidence": confidence,
                    })

                    _find_tables(doc, page, pno)

                except PDFProcessingError:
                    raise
                except Exception:
                    failed_pages += 1
                    doc.page_text[pno] = ""
                    doc.page_info.append(
                        {"page": pno, "method": "failed", "chars": 0, "confidence": None}
                    )
                    _warn(doc, "warning", "page_failed",
                          f"Page {pno} could not be read and was skipped.", pno)

    except PDFProcessingError:
        raise
    except Exception as exc:
        raise CorruptPDFError() from exc

    if processed and failed_pages == processed:
        raise CorruptPDFError()

    _merge_continued_tables(doc)
    _finish(doc, ocr_ready)

    return doc


def _handle_textless_page(doc, page, pno, can_ocr, ocr_budget):
    """Decide what to do with a page that has no text layer.

    Returns (text, method, confidence, ocr_engine_ok).
    """
    if _page_is_blank(page):
        _warn(doc, "info", "blank_page", f"Page {pno} appears to be blank.", pno)
        return "", "blank", None, True

    if not can_ocr:
        doc.scanned_pages.append(pno)
        _warn(
            doc, "warning", "ocr_unavailable",
            f"Page {pno} looks scanned (image only) and OCR isn't available, "
            "so no text could be read. Install Tesseract OCR to read it.",
            pno,
        )
        return "", "scanned", None, True

    if ocr_budget <= 0:
        doc.scanned_pages.append(pno)
        _warn(
            doc, "warning", "ocr_limit",
            f"Page {pno} is scanned but was skipped: OCR is limited to "
            f"{MAX_OCR_PAGES} pages per file.",
            pno,
        )
        return "", "scanned", None, True

    try:
        text, confidence = _ocr_page(page)
    except RuntimeError as exc:
        doc.scanned_pages.append(pno)
        _warn(doc, "warning", "ocr_failed", f"Page {pno}: {exc}", pno)
        return "", "scanned", None, False

    if not text:
        doc.scanned_pages.append(pno)
        _warn(doc, "warning", "ocr_empty",
              f"Page {pno} is scanned but OCR could not find any readable text.", pno)
        return "", "scanned", confidence, True

    doc.ocr_pages.append(pno)

    if confidence is not None and confidence < LOW_OCR_CONFIDENCE:
        _warn(
            doc, "warning", "low_ocr_confidence",
            f"Page {pno}: OCR confidence is low ({confidence:.0f}%). "
            "Review the extracted values carefully.",
            pno,
        )

    return text, "ocr", confidence, True


def _find_tables(doc: ExtractedDocument, page, pno: int) -> None:
    found = page.find_tables()

    if not found:
        found = page.find_tables({
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
        })

    for n, table in enumerate(found, start=1):
        normalized = _normalise(table.extract())
        if normalized:
            header, body = normalized
            doc.tables.append(
                ExtractedTable(page=pno, index=n, header=header, rows=body,
                               bbox=tuple(table.bbox))
            )


def _merge_continued_tables(doc: ExtractedDocument) -> None:
    merged: List[ExtractedTable] = []

    for table in doc.tables:
        if (
            merged
            and merged[-1].header == table.header
            and table.page == merged[-1].page + 1
        ):
            merged[-1].rows.extend(table.rows)
        else:
            merged.append(table)

    doc.tables = merged


def _finish(doc: ExtractedDocument, ocr_ready: bool) -> None:
    """Classify the document and add document-level warnings."""
    methods = [p["method"] for p in doc.page_info if p["method"] != "blank"]
    has_text = any(t.strip() for t in doc.page_text.values())
    image_only = [m for m in methods if m in ("ocr", "scanned")]

    if not has_text:
        doc.kind = "empty"
    elif methods and len(image_only) == len(methods):
        doc.kind = "scanned"
    elif image_only:
        doc.kind = "mixed"
    else:
        doc.kind = "text"

    if doc.kind == "empty":
        _warn(
            doc, "error", "no_text",
            "No readable text was found in this PDF."
            + ("" if ocr_ready else " If it is a scan, install Tesseract OCR and try again."),
        )
    elif not doc.tables:
        extra = (
            " Tables on scanned pages can't be rebuilt, but the OCR text and "
            "invoice fields are available."
            if doc.ocr_pages else
            " The text is still available to copy or export."
        )
        _warn(doc, "info", "no_tables", "No tables were detected." + extra)