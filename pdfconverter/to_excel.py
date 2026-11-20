"""Write extracted tables to a clean, formatted .xlsx file."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .extract import ExtractedDocument

FONT = "Arial"
HEADER_FILL = PatternFill("solid", start_color="1E7B45")
BAND_FILL = PatternFill("solid", start_color="EAF4EC")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

_NUM = re.compile(r"^\(?[-+]?[$€£]?\s?\d{1,3}(,\d{3})*(\.\d+)?\)?%?$|^\(?[-+]?[$€£]?\s?\d+(\.\d+)?\)?%?$")
_DATES = ["%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d-%b-%Y"]


def convert_value(text: str) -> tuple[Any, str | None]:
    """Turn text into a number/date when it clearly is one. Returns (value, number_format)."""
    s = text.strip()
    if not s:
        return None, None
    if _NUM.match(s):
        neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
        pct = s.endswith("%")
        digits = re.sub(r"[^\d.]", "", s)
        if digits and digits.count(".") <= 1:
            # leave long digit strings (IDs, phone numbers, leading zeros) as text
            if len(digits.replace(".", "")) > 12 or (digits.startswith("0") and len(digits) > 1 and "." not in digits):
                return s, None
            val = float(digits)
            val = -val if neg else val
            if pct:
                return val / 100, "0.0%"
            if "," in s or "$" in s or "€" in s or "£" in s:
                return val, "#,##0.00" if "." in digits else "#,##0"
            return (int(val), "0") if val.is_integer() else (val, "General")
    for fmt in _DATES:
        try:
            return datetime.strptime(s, fmt), "dd-mmm-yyyy"
        except ValueError:
            pass
    return s, None


def _sheet_name(base: str, used: set) -> str:
    name = re.sub(r"[\[\]\*\?/\\:]", "_", base)[:31]
    i, final = 2, name
    while final in used:
        suffix = f"_{i}"
        final = name[: 31 - len(suffix)] + suffix
        i += 1
    used.add(final)
    return final


def write_excel(doc: ExtractedDocument, out_path: str, convert_types: bool = True) -> str:
    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()

    if not doc.tables:
        # Fallback: no tables found -> dump text lines so the user still gets something
        ws = wb.create_sheet(_sheet_name("Text", used))
        ws.append(["Page", "Text"])
        for p, txt in doc.page_text.items():
            for line in txt.splitlines():
                ws.append([p, line])
        _style_sheet(ws, 2, ws.max_row)
    for t in doc.tables:
        ws = wb.create_sheet(_sheet_name(f"P{t.page}_Table{t.index}", used))
        ws.append(t.header)
        for r in t.rows:
            row = []
            for c in r:
                row.append(convert_value(c)[0] if convert_types else c)
            ws.append(row)
        if convert_types:
            for r_idx, r in enumerate(t.rows, start=2):
                for c_idx, c in enumerate(r, start=1):
                    _, fmt = convert_value(c)
                    if fmt:
                        ws.cell(r_idx, c_idx).number_format = fmt
        _style_sheet(ws, len(t.header), ws.max_row)

    # Summary sheet
    s = wb.create_sheet("Summary", 0)
    s.append(["Source file", doc.filename])
    s.append(["Pages", doc.page_count])
    s.append(["Tables found", len(doc.tables)])
    s.append([])
    s.append(["Sheet", "Page", "Rows", "Columns"])
    for ws, t in zip([w for w in wb.worksheets if w.title != "Summary"], doc.tables):
        s.append([ws.title, t.page, len(t.rows), len(t.header)])
    for row in s.iter_rows():
        for c in row:
            c.font = Font(name=FONT, size=10)
    for c in s[5]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
    for c in s["A"][:3]:
        c.font = Font(name=FONT, bold=True, size=10)
    s.column_dimensions["A"].width = 24
    s.column_dimensions["B"].width = 30

    wb.save(out_path)
    return out_path


def _style_sheet(ws, ncols: int, nrows: int) -> None:
    for c in ws[1]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    for r in range(2, nrows + 1):
        for c in ws[r]:
            c.font = Font(name=FONT, size=10)
            c.border = BORDER
            if r % 2 == 1:
                c.fill = BAND_FILL
            if isinstance(c.value, (int, float)):
                c.alignment = Alignment(horizontal="right")
    for i in range(1, ws.max_column + 1):
        letter = get_column_letter(i)
        longest = max((len(str(c.value)) for c in ws[letter] if c.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(longest + 3, 10), 50)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
