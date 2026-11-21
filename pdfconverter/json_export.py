
"""Export extracted PDF tables, text, invoice data and OCR details."""
from __future__ import annotations

import json

from .extract import ExtractedDocument


def table_to_json(table) -> dict:
    return {
        "page": table.page,
        "table_index": table.index,
        "headers": table.header,
        "rows": [
            {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(table.header)
            }
            for row in table.rows
        ]
    }


def export_json(
    doc: ExtractedDocument,
    base_name: str
) -> tuple[bytes, str, str]:

    ocr_pages = getattr(doc, "ocr_pages", [])

    data = {
        "document": base_name,
        "page_count": doc.page_count,
        "total_tables": len(doc.tables),
        "ocr_used": bool(ocr_pages),
        "ocr_pages": ocr_pages,
        "tables": [
            table_to_json(table)
            for table in doc.tables
        ],
        "invoice_data": getattr(doc, "invoice_data", {}),
        "page_text": doc.page_text
    }

    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=4,
        default=str
    )

    return (
        content.encode("utf-8"),
        f"{base_name}.json",
        "application/json"
    )

