"""Export extracted PDF tables, text, invoice data, OCR details and warnings."""
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

    data = {
        "document": base_name,
        "page_count": doc.page_count,
        "document_kind": doc.kind,
        "total_tables": len(doc.tables),
        "ocr_used": bool(doc.ocr_pages),
        "ocr_pages": doc.ocr_pages,
        "warnings": [w["message"] for w in doc.warnings],
        "tables": [table_to_json(table) for table in doc.tables],
        "invoice_data": doc.invoice_data,
        "line_items": doc.invoice_line_items,
        "page_text": doc.page_text,
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