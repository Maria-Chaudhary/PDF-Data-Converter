"""PDF extraction: finds tables page by page (shared by Excel / CSV / JSON exporters)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import pdfplumber


@dataclass
class ExtractedTable:
    page: int
    index: int                      # table number on that page (1-based)
    header: List[str]
    rows: List[List[str]]
    bbox: Optional[tuple] = None


@dataclass
class ExtractedDocument:
    filename: str
    page_count: int
    tables: List[ExtractedTable] = field(default_factory=list)
    page_text: dict = field(default_factory=dict)   # page -> raw text (fallback / JSON later)


def _clean(cell) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def _looks_like_header(row: List[str]) -> bool:
    """A header row is mostly non-empty, non-numeric text."""
    filled = [c for c in row if c]
    if not filled:
        return False
    numeric = sum(bool(re.fullmatch(r"[-+$€£]?[\d,]+(\.\d+)?%?", c)) for c in filled)
    return numeric / len(filled) < 0.5


def _unique_headers(header: List[str]) -> List[str]:
    seen, out = {}, []
    for i, h in enumerate(header):
        h = h or f"Column {i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    return out


def _normalise(raw: List[List]) -> Optional[tuple]:
    rows = [[_clean(c) for c in r] for r in raw]
    rows = [r for r in rows if any(r)]                 # drop blank rows
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # drop fully empty columns
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    rows = [[r[i] for i in keep] for r in rows]
    if _looks_like_header(rows[0]):
        header, body = rows[0], rows[1:]
    else:
        header, body = [f"Column {i + 1}" for i in range(len(rows[0]))], rows
    return _unique_headers(header), body


def extract_pdf(path: str, pages: Optional[List[int]] = None) -> ExtractedDocument:
    """Extract all tables from a PDF.

    Strategy per page: try ruled-line tables first ("lines"), then fall back to
    whitespace alignment ("text") for borderless tables.
    """
    with pdfplumber.open(path) as pdf:
        doc = ExtractedDocument(filename=str(path).split("/")[-1], page_count=len(pdf.pages))
        for pno, page in enumerate(pdf.pages, start=1):
            if pages and pno not in pages:
                continue
            doc.page_text[pno] = page.extract_text() or ""

            found = page.find_tables()                       # default: ruling lines
            if not found:
                found = page.find_tables(
                    {"vertical_strategy": "text", "horizontal_strategy": "text"}
                )
            for n, t in enumerate(found, start=1):
                norm = _normalise(t.extract())
                if norm:
                    header, body = norm
                    doc.tables.append(ExtractedTable(pno, n, header, body, tuple(t.bbox)))

    # Merge tables that continue across pages (same header)
    merged: List[ExtractedTable] = []
    for t in doc.tables:
        if merged and merged[-1].header == t.header and t.page == merged[-1].page + 1:
            merged[-1].rows.extend(t.rows)
        else:
            merged.append(t)
    doc.tables = merged
    return doc
