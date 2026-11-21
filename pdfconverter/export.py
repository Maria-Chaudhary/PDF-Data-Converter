"""Build downloads (xlsx / csv / json / invoice) from already-extracted data.

The browser posts back what it previewed (including any invoice edits), so
nothing is re-processed and no PDF has to be kept on the server.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import List

from .errors import InvalidRequestError
from .extract import ExtractedDocument, ExtractedTable
from .invoice import normalise_invoice
from .invoice_export import export_invoice_json, export_invoice_xlsx
from .json_export import export_json
from .to_csv import export_csv
from .to_excel import write_excel

FORMATS = {"xlsx", "csv", "json", "invoice_json", "invoice_xlsx"}
MAX_FILES = 50

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _safe_stem(name: str) -> str:
    stem = re.sub(r"\.pdf$", "", str(name or "document"), flags=re.I)
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", stem).strip(" .")
    return stem[:120] or "document"


def doc_from_payload(payload: dict) -> ExtractedDocument:
    """Rebuild an ExtractedDocument from the JSON the preview returned."""
    if not isinstance(payload, dict):
        raise InvalidRequestError("Invalid export data.")

    try:
        doc = ExtractedDocument(
            filename=_safe_stem(payload.get("filename")) + ".pdf",
            page_count=int(payload.get("pages") or 0),
        )

        for i, t in enumerate(payload.get("tables") or [], start=1):
            doc.tables.append(ExtractedTable(
                page=int(t.get("page") or 1),
                index=int(t.get("index") or i),
                header=[str(h) for h in t.get("header") or []],
                rows=[[("" if c is None else str(c)) for c in row] for row in t.get("rows") or []],
            ))

        for p in payload.get("pages_detail") or []:
            doc.page_text[int(p["page"])] = str(p.get("text") or "")

        doc.ocr_pages = [int(p) for p in payload.get("ocr_pages") or []]
        doc.kind = str(payload.get("kind") or "text")
        doc.warnings = [w for w in payload.get("warnings") or [] if isinstance(w, dict)]
        doc.invoice_data = normalise_invoice(payload.get("invoice"))
        doc.invoice_line_items = [
            i for i in payload.get("line_items") or [] if isinstance(i, dict)
        ]
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidRequestError("Invalid export data.") from exc

    return doc


def _one(doc: ExtractedDocument, fmt: str, raw: bool):
    base = _safe_stem(doc.filename)

    if fmt == "xlsx":
        buf = io.BytesIO()
        write_excel(doc, buf, convert_types=not raw)
        return buf.getvalue(), f"{base}.xlsx", _XLSX
    if fmt == "csv":
        return export_csv(doc, base)
    if fmt == "json":
        return export_json(doc, base)
    if fmt == "invoice_json":
        return export_invoice_json([doc], base)
    return export_invoice_xlsx([doc], base)


def _unique(name: str, used: set) -> str:
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 2
    while candidate in used:
        candidate = f"{stem} ({n}){dot}{ext}"
        n += 1
    used.add(candidate)
    return candidate


def build_export(files: List[dict], fmt: str, raw: bool = False):
    """Returns (bytes, download_name, mimetype)."""
    if fmt not in FORMATS:
        raise InvalidRequestError("Unknown export format.")
    if not files:
        raise InvalidRequestError("There is nothing to export yet.")
    if len(files) > MAX_FILES:
        raise InvalidRequestError(f"You can export up to {MAX_FILES} files at once.")

    docs = [doc_from_payload(f) for f in files]

    if len(docs) == 1:
        return _one(docs[0], fmt, raw)

    # Invoices combine into one file; everything else becomes a ZIP.
    if fmt == "invoice_xlsx":
        return export_invoice_xlsx(docs, "invoices")
    if fmt == "invoice_json":
        return export_invoice_json(docs, "invoices")

    mem, used = io.BytesIO(), set()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc in docs:
            data, name, _mime = _one(doc, fmt, raw)
            archive.writestr(_unique(name, used), data)

    return mem.getvalue(), f"converted_{fmt}.zip", "application/zip"