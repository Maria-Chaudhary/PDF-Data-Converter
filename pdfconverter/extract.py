
"""PDF extraction with table detection and OCR fallback."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import pdfplumber


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
    page_text: dict = field(default_factory=dict)
    ocr_pages: List[int] = field(default_factory=list)


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

    keep = [
        i for i in range(width)
        if any(row[i] for row in rows)
    ]

    rows = [[row[i] for i in keep] for row in rows]

    if _looks_like_header(rows[0]):
        header, body = rows[0], rows[1:]
    else:
        header = [f"Column {i + 1}" for i in range(len(rows[0]))]
        body = rows

    return _unique_headers(header), body


def _ocr_page(page) -> str:
    """Extract text from a scanned PDF page using Tesseract."""
    try:
        import pytesseract

        executable = os.environ.get("TESSERACT_CMD")

        if executable:
            pytesseract.pytesseract.tesseract_cmd = executable

        image = page.to_image(resolution=250).original

        return pytesseract.image_to_string(
            image,
            config="--psm 6"
        ).strip()

    except ImportError:
        raise RuntimeError(
            "OCR packages are missing. Install pytesseract and pillow."
        )

    except Exception as exc:
        raise RuntimeError(
            "OCR failed. Check that Tesseract OCR is installed "
            "and its executable path is correct."
        ) from exc


def extract_pdf(
    path: str,
    pages: Optional[List[int]] = None,
    enable_ocr: bool = True
) -> ExtractedDocument:
    """
    Extract tables and text from a PDF.

    Normal text-based extraction is attempted first.
    OCR is used when a page has no extractable text.
    """

    with pdfplumber.open(path) as pdf:
        doc = ExtractedDocument(
            filename=os.path.basename(path),
            page_count=len(pdf.pages)
        )

        for pno, page in enumerate(pdf.pages, start=1):

            if pages and pno not in pages:
                continue

            text = page.extract_text() or ""

            # OCR fallback for scanned/image-only pages
            if not text.strip() and enable_ocr:
                try:
                    text = _ocr_page(page)

                    if text:
                        doc.ocr_pages.append(pno)

                except RuntimeError:
                    # Keep extraction usable even if OCR is not installed.
                    text = ""

            doc.page_text[pno] = text

            # Detect normal PDF tables
            found = page.find_tables()

            if not found:
                found = page.find_tables({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text"
                })

            for n, table in enumerate(found, start=1):
                normalized = _normalise(table.extract())

                if normalized:
                    header, body = normalized

                    doc.tables.append(
                        ExtractedTable(
                            page=pno,
                            index=n,
                            header=header,
                            rows=body,
                            bbox=tuple(table.bbox)
                        )
                    )

    # Merge consecutive tables with matching headers.
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

    return doc
