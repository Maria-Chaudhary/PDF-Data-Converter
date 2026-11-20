"""Write extracted tables to CSV (one table -> .csv, several tables -> .zip of CSVs)."""
from __future__ import annotations

import csv
import io
import zipfile

from .extract import ExtractedDocument, ExtractedTable


def table_to_csv_text(t: ExtractedTable) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(t.header)
    w.writerows(t.rows)
    return buf.getvalue()


def _bytes(t: ExtractedTable) -> bytes:
    # utf-8-sig adds a BOM so Excel opens Urdu/Japanese/accented text correctly
    return table_to_csv_text(t).encode("utf-8-sig")


def export_csv(doc: ExtractedDocument, base_name: str) -> tuple[bytes, str, str]:
    """Returns (file_bytes, download_filename, mimetype)."""
    if not doc.tables:
        rows = [["Page", "Text"]] + [[p, l] for p, txt in doc.page_text.items() for l in txt.splitlines()]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\r\n").writerows(rows)
        return buf.getvalue().encode("utf-8-sig"), f"{base_name}.csv", "text/csv"
    if len(doc.tables) == 1:
        return _bytes(doc.tables[0]), f"{base_name}.csv", "text/csv"
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for t in doc.tables:
            z.writestr(f"{base_name}_P{t.page}_Table{t.index}.csv", _bytes(t))
    return mem.getvalue(), f"{base_name}_csv.zip", "application/zip"