
"""Export extracted PDF tables and text to structured JSON."""
from __future__ import annotations

import json

from .extract import ExtractedDocument, ExtractedTable


def table_to_json(t: ExtractedTable) -> dict:
    """Convert one extracted table into structured JSON."""
    return {
        "page": t.page,
        "table_index": t.index,
        "headers": t.header,
        "rows": [
            dict(zip(t.header, row))
            for row in t.rows
        ],
    }


def export_json(
    doc: ExtractedDocument,
    base_name: str
) -> tuple[bytes, str, str]:
    """Returns (file_bytes, download_filename, mimetype)."""

    if doc.tables:
        data = {
            "document": base_name,
            "total_tables": len(doc.tables),
            "tables": [
                table_to_json(table)
                for table in doc.tables
            ],
            "page_text": doc.page_text,
        }
    else:
        data = {
            "document": base_name,
            "total_tables": 0,
            "tables": [],
            "page_text": doc.page_text,
        }

    json_content = json.dumps(
        data,
        ensure_ascii=False,
        indent=4,
        default=str
    )

    return (
        json_content.encode("utf-8"),
        f"{base_name}.json",
        "application/json"
    )
