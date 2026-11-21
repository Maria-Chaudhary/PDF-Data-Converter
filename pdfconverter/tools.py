"""Stand-alone PDF tools: merge and split (no extraction involved)."""
from __future__ import annotations

import io
import re
import zipfile
from typing import List, Tuple

from pypdf import PdfWriter

from .errors import CorruptPDFError, InvalidRequestError, PDFProcessingError
from .pdfcheck import open_pdf


def parse_ranges(spec: str, total: int) -> List[Tuple[int, int]]:
    """'1-3, 5, 8-' -> [(1, 3), (5, 5), (8, total)] with friendly errors."""
    spec = (spec or "").strip()
    if not spec:
        raise InvalidRequestError("Enter the pages to use, for example 1-3, 5, 8-10.")

    ranges: List[Tuple[int, int]] = []

    for part in re.split(r"[,\s;]+", spec):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d*))?", part)
        if not match:
            raise InvalidRequestError(f"'{part}' is not a valid page or range. Use e.g. 1-3, 5, 8-10.")

        start = int(match.group(1))
        if match.group(2) is None:
            end = start
        elif match.group(2) == "":
            end = total                       # "8-" means 8 to the last page
        else:
            end = int(match.group(2))

        if start < 1 or end < 1 or start > total or end > total:
            bad = start if (start < 1 or start > total) else end
            raise InvalidRequestError(f"Page {bad} is out of range. This PDF has {total} page(s).")
        if start > end:
            raise InvalidRequestError(f"'{part}' is backwards. Use {end}-{start} instead.")

        ranges.append((start, end))

    if not ranges:
        raise InvalidRequestError("Enter the pages to use, for example 1-3, 5, 8-10.")
    return ranges


def _label(start: int, end: int) -> str:
    return f"{start}" if start == end else f"{start}-{end}"


def _build(reader, page_numbers: List[int]) -> bytes:
    writer = PdfWriter()
    for number in page_numbers:
        writer.add_page(reader.pages[number - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def merge_pdfs(items: List[Tuple[str, str]]) -> Tuple[bytes, int]:
    """items = [(display_name, path), ...] in the desired order."""
    if len(items) < 2:
        raise InvalidRequestError("Add at least two PDFs to merge.")

    writer = PdfWriter()
    pages = 0

    for name, path in items:
        try:
            reader = open_pdf(path)
            for page in reader.pages:
                writer.add_page(page)
            pages += len(reader.pages)
        except PDFProcessingError as exc:
            exc.filename = name
            exc.message = f"{name}: {exc.message}"
            raise
        except Exception as exc:
            err = CorruptPDFError(f"{name}: {CorruptPDFError.message}", filename=name)
            raise err from exc

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), pages


def split_pdf(path: str, name: str, mode: str, spec: str = ""):
    """Returns (bytes, download_name, mimetype, parts).

    mode: 'each'    one PDF per page            -> zip
          'ranges'  one PDF per range in spec   -> zip (or one PDF if one range)
          'extract' all pages in spec in a single PDF
    """
    stem = re.sub(r"\.pdf$", "", name, flags=re.I) or "document"

    try:
        reader = open_pdf(path)
        total = len(reader.pages)

        if mode == "extract":
            numbers = [p for s, e in parse_ranges(spec, total) for p in range(s, e + 1)]
            return _build(reader, numbers), f"{stem}_extract.pdf", "application/pdf", 1

        if mode == "each":
            groups = [(p, p) for p in range(1, total + 1)]
        elif mode == "ranges":
            groups = parse_ranges(spec, total)
        else:
            raise InvalidRequestError("Choose how you want to split the PDF.")

        if len(groups) == 1:
            s, e = groups[0]
            data = _build(reader, list(range(s, e + 1)))
            return data, f"{stem}_pages_{_label(s, e)}.pdf", "application/pdf", 1

        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as archive:
            for s, e in groups:
                archive.writestr(
                    f"{stem}_pages_{_label(s, e)}.pdf",
                    _build(reader, list(range(s, e + 1))),
                )
        return mem.getvalue(), f"{stem}_split.zip", "application/zip", len(groups)

    except PDFProcessingError as exc:
        exc.filename = exc.filename or name
        raise
    except Exception as exc:
        raise CorruptPDFError(filename=name) from exc