"""Export invoice data (possibly edited by the user) to JSON or Excel."""
from __future__ import annotations

import io
import json
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from .extract import ExtractedDocument
from .invoice import (
    FIELD_LABELS,
    MONEY_FIELDS,
    NUMBER_FIELDS,
    normalise_invoice,
    validate_invoice,
)
from .to_excel import BORDER, FONT, HEADER_FILL, _style_sheet

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def invoice_record(doc: ExtractedDocument) -> dict:
    """One invoice as a JSON-friendly dict, re-validated from its current values."""
    data = normalise_invoice(doc.invoice_data)
    warnings, missing = validate_invoice(data, doc.invoice_line_items)

    return {
        "source_file": doc.filename,
        "pages": doc.page_count,
        "ocr_used": bool(doc.ocr_pages),
        "ocr_pages": doc.ocr_pages,
        "invoice_data": data,
        "line_items": doc.invoice_line_items,
        "missing_fields": missing,
        "warnings": [w["message"] for w in warnings if w["level"] != "info"],
    }


def export_invoice_json(docs: List[ExtractedDocument], base_name: str):
    records = [invoice_record(d) for d in docs]
    body = records[0] if len(records) == 1 else {"count": len(records), "invoices": records}
    content = json.dumps(body, ensure_ascii=False, indent=4, default=str)
    name = f"{base_name}_invoice.json" if len(records) == 1 else f"{base_name}.json"
    return content.encode("utf-8"), name, "application/json"


def _put(ws, row, col, value, number_format=None):
    cell = ws.cell(row, col, value)
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"        # never let extracted text run as a formula
    if number_format:
        cell.number_format = number_format
    return cell


def _money_format(key):
    return "0.00" if key == "tax_rate" else "#,##0.00"


def export_invoice_xlsx(docs: List[ExtractedDocument], base_name: str):
    records = [invoice_record(d) for d in docs]
    wb = Workbook()
    wb.remove(wb.active)

    if len(records) == 1:
        _single_sheet(wb, records[0])
        name = f"{base_name}_invoice.xlsx"
    else:
        _multi_sheet(wb, records)
        name = f"{base_name}.xlsx"

    _line_items_sheet(wb, records)
    _warnings_sheet(wb, records)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), name, XLSX_MIME


def _single_sheet(wb, record):
    ws = wb.create_sheet("Invoice")
    ws.append(["Field", "Value", "Status"])
    data = record["invoice_data"]

    for r, (key, label) in enumerate(FIELD_LABELS.items(), start=2):
        value = data.get(key)
        ws.cell(r, 1, label)
        _put(ws, r, 2, value, _money_format(key) if key in NUMBER_FIELDS else None)
        ws.cell(r, 3, "Detected / entered" if value is not None else "Missing")
        if key in MONEY_FIELDS:
            ws.cell(r, 2).alignment = Alignment(horizontal="right")

    ws.cell(ws.max_row + 2, 1, "Source file")
    ws.cell(ws.max_row, 2, record["source_file"])
    _style_sheet(ws, 3, ws.max_row)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 20


def _multi_sheet(wb, records):
    ws = wb.create_sheet("Invoices")
    keys = list(FIELD_LABELS)
    ws.append(["Source file"] + [FIELD_LABELS[k] for k in keys] + ["Warnings"])

    for r, rec in enumerate(records, start=2):
        ws.cell(r, 1, rec["source_file"])
        for c, key in enumerate(keys, start=2):
            _put(ws, r, c, rec["invoice_data"].get(key),
                 _money_format(key) if key in NUMBER_FIELDS else None)
        ws.cell(r, len(keys) + 2, len(rec["warnings"]))

    _style_sheet(ws, len(keys) + 2, ws.max_row)

    # Grand total row so batches are easy to reconcile.
    total_row = ws.max_row + 1
    ws.cell(total_row, 1, "Total (all files)").font = Font(name=FONT, bold=True, size=10)
    for c, key in enumerate(keys, start=2):
        if key in MONEY_FIELDS:
            cell = ws.cell(total_row, c, sum((rec["invoice_data"].get(key) or 0) for rec in records))
            cell.number_format = "#,##0.00"
            cell.font = Font(name=FONT, bold=True, size=10)
            cell.border = BORDER


def _line_items_sheet(wb, records):
    rows = [(rec["source_file"], i) for rec in records for i in rec["line_items"]]
    if not rows:
        return
    ws = wb.create_sheet("Line Items")
    ws.append(["Source file", "Description", "Quantity", "Unit price", "Amount"])
    for source, item in rows:
        ws.append([source, "", item.get("quantity"), item.get("unit_price"), item.get("amount")])
        _put(ws, ws.max_row, 2, item.get("description", ""))
        for col in (4, 5):
            ws.cell(ws.max_row, col).number_format = "#,##0.00"
    _style_sheet(ws, 5, ws.max_row)


def _warnings_sheet(wb, records):
    rows = [(rec["source_file"], w) for rec in records for w in rec["warnings"]]
    if not rows:
        return
    ws = wb.create_sheet("Warnings")
    ws.append(["Source file", "Warning"])
    for source, message in rows:
        ws.append([source, message])
    _style_sheet(ws, 2, ws.max_row)
    ws.column_dimensions["B"].width = 90