"""Rule-based invoice extraction, validation and line-item detection.

This is heuristic pattern matching, not an AI model: results depend on the
invoice layout and text quality, which is why every result is cross-checked
(subtotal + tax = total) and missing fields are reported as warnings.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# field catalogue (shared with the exporters and the UI)
# --------------------------------------------------------------------------
FIELD_LABELS = {
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "currency": "Currency",
    "subtotal": "Subtotal",
    "discount": "Discount",
    "shipping": "Shipping",
    "tax_rate": "Tax rate (%)",
    "tax": "Tax / VAT / GST",
    "total": "Total",
    "amount_due": "Amount due",
    "email": "Email",
    "phone": "Phone",
}
MONEY_FIELDS = ("subtotal", "discount", "shipping", "tax", "total", "amount_due")
NUMBER_FIELDS = MONEY_FIELDS + ("tax_rate",)
TEXT_FIELDS = ("invoice_number", "invoice_date", "due_date", "currency", "email", "phone")
TOLERANCE = 0.02  # allowed rounding difference when cross-checking amounts

# --------------------------------------------------------------------------
# amounts
# --------------------------------------------------------------------------
_CUR = r"PKR|USD|EUR|GBP|AED|SAR|INR|CAD|AUD|Rs\.?|[$€£₨₹]"

AMOUNT_RE = re.compile(
    rf"""
    (?<![\w.,/-])
    (?P<neg>[-−(])?\s*
    (?:(?P<cur>{_CUR})\s*)?
    (?P<num>
        \d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?        # 1,234.56
      | \d{{1,3}}(?:\.\d{{3}})+,\d{{1,2}}        # 1.234,56 (European)
      | \d+(?:[.,]\d+)?                          # 1234.56 / 1234,56 / 1234
    )
    (?![\w/])
    (?!\s*(?:items?|pcs|pieces|units?|qty|days?|hours?|hrs?)\b)
    \)?
    (?P<pct>\s*%)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SYMBOL_CODES = {"$": "USD", "€": "EUR", "£": "GBP", "₨": "PKR", "₹": "INR"}


def parse_amount(value: Any) -> Optional[float]:
    """Parse '1,234.56', '1.234,56', '(50.00)', '$ 99' ... into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    raw = str(value).strip()
    if not raw:
        return None

    negative = raw.startswith("-") or raw.startswith("−") or (
        raw.startswith("(") and raw.endswith(")")
    )
    s = re.sub(r"[^\d.,]", "", raw).strip(".,")
    if not s:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):          # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                     # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if s.count(",") > 1 or (len(tail) == 3 and head):
            s = s.replace(",", "")                # thousands separator
        else:
            s = head + "." + tail                 # decimal comma
    elif s.count(".") > 1:
        s = s.replace(".", "")

    try:
        number = float(s)
    except ValueError:
        return None

    return -number if negative else number


def _currency_code(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    token = token.strip().rstrip(".").upper()
    if token == "RS":
        return "PKR"
    return _SYMBOL_CODES.get(token, token)


def _amounts_in(segment: str) -> List[dict]:
    """All money-looking numbers in a text segment (percentages excluded)."""
    found = []
    for match in AMOUNT_RE.finditer(segment):
        if match.group("pct"):
            continue
        value = parse_amount(match.group(0))
        if value is None:
            continue
        num = match.group("num")
        found.append({
            "value": value,
            "currency": _currency_code(match.group("cur")),
            # "strong" amounts have a currency, decimals or thousands separators,
            # which separates them from stray integers such as "(3 items)".
            "strong": bool(match.group("cur")) or bool(re.search(r"[.,]", num)),
        })
    return found


def _pick(amounts: List[dict]) -> Optional[dict]:
    """The right-most amount, preferring 'strong' ones."""
    strong = [a for a in amounts if a["strong"]]
    pool = strong or amounts
    return pool[-1] if pool else None


_BOUNDARY = re.compile(
    r"\b(?:sub[\s\-]?total|total|tax|vat|gst|discount|shipping|freight|"
    r"balance|amount\s+due)\b",
    re.IGNORECASE,
)


def _label_amounts(lines: List[str], label: re.Pattern) -> List[dict]:
    """For each line containing the label, return the amount it refers to."""
    results = []

    for i, line in enumerate(lines):
        match = label.search(line)
        if not match:
            continue

        start = match.end()
        boundary = _BOUNDARY.search(line, start)
        chosen = _pick(_amounts_in(line[start: boundary.start() if boundary else None]))

        if not chosen and boundary:  # "Tax Total 100.00": modifier, not a new label
            chosen = _pick(_amounts_in(line[start:]))

        if not chosen and i + 1 < len(lines):  # value printed on the next line
            nxt = lines[i + 1].strip()
            if AMOUNT_RE.fullmatch(nxt) and not AMOUNT_RE.fullmatch(nxt).group("pct"):
                chosen = _pick(_amounts_in(nxt))

        if chosen:
            results.append({"line": i, "text": line, "match": match, **chosen})

    return results


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# --------------------------------------------------------------------------
# label patterns
# --------------------------------------------------------------------------
_TOTAL_NOT_FOLLOWED = (
    r"(?!\s*\(?\s*(?:tax|vat|gst|qty|quantity|items?|units?|discount|weight|"
    r"hours|before|excl|ex\b|net\s+of|pages?|savings?|paid|received))"
)
TOTAL_PRIORITY = [
    _rx(r"\bgrand\s*total\b|\binvoice\s*total\b|\btotal\s*invoice\b|"
        r"\btotal\s*amount\b|\btotal\s*due\b|\btotal\s*payable\b|"
        r"\btotal\s*\(?\s*(?:incl\w*|inc\.?|with)\b"),
    _rx(r"(?<!sub )(?<!sub-)\btotal\b" + _TOTAL_NOT_FOLLOWED),
]
AMOUNT_DUE = _rx(r"\bamount\s*due\b|\bbalance\s*due\b|\bamount\s*payable\b|\bnet\s*payable\b")
SUBTOTAL = _rx(
    r"\bsub[\s\-]?total\b|\btotal\s*\(?\s*(?:excl\w*|ex\.?|before)\s*\.?\s*(?:tax|vat|gst)|"
    r"\bamount\s+before\s+tax\b"
)
TOTAL_TAX = _rx(r"\btotal\s+(?:tax|vat|gst)\b")
SPLIT_TAX = _rx(r"\b(?:cgst|sgst|igst)\b")
TAX = _rx(
    r"\b(?:tax|vat|gst|hst|sst)\b"
    r"(?!\s*(?:invoice|id\b|no\b|no\.|number|reg|registration|code|#|"
    r"identification|exempt|included|inclusive))"
)
DISCOUNT = _rx(r"\b(?:total\s+)?discount\b")
SHIPPING = _rx(r"\b(?:shipping|freight|delivery|postage|handling)(?:\s+(?:charges?|fees?|cost))?\b")

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
DATE_RE = re.compile(
    rf"""
      \d{{1,2}}[/\-.]\d{{1,2}}[/\-.]\d{{2,4}}
    | \d{{4}}[/\-.]\d{{1,2}}[/\-.]\d{{1,2}}
    | \d{{1,2}}(?:st|nd|rd|th)?[\s\-]+{_MONTH}\.?,?[\s\-]+\d{{2,4}}
    | {_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}
    """,
    re.IGNORECASE | re.VERBOSE,
)
_DATE_FORMATS = [
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d-%m-%y", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y",
    "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
]


def parse_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", str(text).strip(), flags=re.I)
    s = re.sub(r"[.,]", " ", s) if re.search(r"[A-Za-z]", s) else s
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# text fields
# --------------------------------------------------------------------------
def _clean_text(page_text: Dict[int, str]) -> str:
    if not page_text:
        return ""
    return "\n".join(str(t or "") for _, t in sorted(page_text.items()))


def _find_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"(?:tax\s+)?(?:invoice|inv|bill|receipt)\s*(?:number|no\.?|num\.?|#|id)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/_\-]*)",
        r"\binvoice\s*:\s*([A-Z0-9][A-Z0-9/_\-]*)",
        r"\binvoice\s+#\s*([A-Z0-9][A-Z0-9/_\-]*)",
        r"\b(INV[-/_ ]?\d[A-Z0-9/_\-]*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).strip("-_/ ")
            if any(ch.isdigit() for ch in value):   # "Invoice No: Date" is not a number
                return value
    return None


def _find_date(lines: List[str], labels: List[str], skip_before: str = "") -> Optional[str]:
    for label in labels:
        label_re = re.compile(label, re.IGNORECASE)
        for line in lines:
            for match in label_re.finditer(line):
                if skip_before and re.search(skip_before, line[:match.start()], re.I):
                    continue
                found = DATE_RE.search(line[match.end(): match.end() + 45])
                if found:
                    return found.group(0).strip()
    return None


def _find_email(text: str) -> Optional[str]:
    match = re.search(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
    return match.group(0) if match else None


def _find_phone(text: str) -> Optional[str]:
    labelled = re.search(
        r"\b(?:phone|tel(?:ephone)?|mobile|cell|contact|ph)\b\.?\s*(?:no\.?|#)?\s*[:\-]?\s*"
        r"(\+?\(?\d[\d\s().\-]{6,}\d)",
        text, re.IGNORECASE,
    )
    if labelled:
        return labelled.group(1).strip()

    for match in re.finditer(r"(?<![\w/.-])(\+\d[\d\s().\-]{7,}\d|\(?0\d{2,4}\)?[\s.\-]?\d{3,}[\d\s.\-]*\d)", text):
        digits = re.sub(r"\D", "", match.group(1))
        if 9 <= len(digits) <= 15 and not DATE_RE.fullmatch(match.group(1).strip()):
            return match.group(1).strip()
    return None


def _detect_currency(text: str, total_line: Optional[str]) -> Optional[str]:
    if total_line:
        for m in AMOUNT_RE.finditer(total_line):
            code = _currency_code(m.group("cur"))
            if code:
                return code

    counts: Dict[str, int] = {}
    for m in re.finditer(rf"(?<![A-Za-z])({_CUR})(?=\s*[\d(])", text, re.IGNORECASE):
        code = _currency_code(m.group(1))
        if code:
            counts[code] = counts.get(code, 0) + 1
    return max(counts, key=counts.get) if counts else None


# --------------------------------------------------------------------------
# line items
# --------------------------------------------------------------------------
_SUMMARY_ROW = re.compile(
    r"^\s*(?:sub[\s\-]?total|total|grand|tax|vat|gst|discount|shipping|"
    r"balance|amount\s+due|payment|paid)\b",
    re.IGNORECASE,
)


def _column_roles(header: List[str]) -> Dict[str, int]:
    roles: Dict[str, int] = {}
    for i, name in enumerate(header):
        h = name.lower()
        if "description" not in roles and re.search(r"descr|item|product|service|particular|detail|name", h):
            roles["description"] = i
        elif "quantity" not in roles and re.search(r"\bqty\b|quant|units?\b|hours", h):
            roles["quantity"] = i
        elif "unit_price" not in roles and re.search(r"unit|price|rate|cost", h) and "total" not in h:
            roles["unit_price"] = i
        elif "amount" not in roles and re.search(r"amount|total|line|net|value", h):
            roles["amount"] = i
    return roles


def extract_line_items(tables) -> List[dict]:
    """Rows of the first table that looks like an invoice line-item table."""
    for table in tables or []:
        header = [str(h) for h in getattr(table, "header", [])]
        roles = _column_roles(header)
        if "description" not in roles or "amount" not in roles:
            continue

        items = []
        for row in table.rows:
            def cell(role):
                idx = roles.get(role)
                return row[idx] if idx is not None and idx < len(row) else ""

            description = cell("description").strip()
            amount = parse_amount(cell("amount"))

            if amount is None or _SUMMARY_ROW.match(description):
                continue

            items.append({
                "description": description,
                "quantity": parse_amount(cell("quantity")),
                "unit_price": parse_amount(cell("unit_price")),
                "amount": amount,
            })

        if items:
            return items
    return []


# --------------------------------------------------------------------------
# normalisation + validation
# --------------------------------------------------------------------------
def normalise_invoice(data: Optional[dict]) -> Dict[str, Any]:
    """Coerce (possibly user-edited) values: numbers -> float, blanks -> None."""
    data = data or {}
    clean: Dict[str, Any] = {}

    for key in FIELD_LABELS:
        value = data.get(key)
        if key in NUMBER_FIELDS:
            clean[key] = parse_amount(value)
        else:
            text = str(value).strip() if value not in (None, "") else ""
            clean[key] = (text.upper() if key == "currency" else text) or None

    clean["extraction_method"] = data.get("extraction_method", "rule-based")
    return clean


def _w(level: str, code: str, message: str, field: Optional[str] = None) -> dict:
    return {"level": level, "code": code, "field": field, "message": message}


def _money(value: float) -> str:
    return f"{value:,.2f}"


def validate_invoice(data: dict, line_items: Optional[List[dict]] = None) -> Tuple[List[dict], List[str]]:
    """Return (warnings, missing_fields) for invoice values."""
    inv = normalise_invoice(data)
    warnings: List[dict] = []
    missing: List[str] = []

    required = [
        ("invoice_number", "warning"),
        ("invoice_date", "warning"),
        ("total", "error"),
    ]
    for key, level in required:
        if inv[key] is None:
            missing.append(key)
            warnings.append(_w(level, "missing_field",
                               f"{FIELD_LABELS[key]} was not found. Enter it manually if it is on the invoice.", key))

    for key in ("subtotal", "tax"):
        if inv[key] is None:
            missing.append(key)
            note = (" This is fine if the invoice has no tax." if key == "tax"
                    else " Cross-checking the total is not possible without it.")
            warnings.append(_w("info", "missing_field", f"{FIELD_LABELS[key]} was not found.{note}", key))

    sub, tax, total = inv["subtotal"], inv["tax"], inv["total"]
    discount, shipping = abs(inv["discount"] or 0), inv["shipping"] or 0

    if total is not None and total <= 0:
        warnings.append(_w("warning", "non_positive_total", "Total is zero or negative. Check the value.", "total"))

    if sub is not None and total is not None and (tax is not None or sub != total):
        expected = sub - discount + shipping + (tax or 0)
        if abs(expected - total) > TOLERANCE:
            diff = total - expected
            warnings.append(_w(
                "warning", "total_mismatch",
                f"Subtotal + tax{' - discount' if discount else ''}{' + shipping' if shipping else ''} "
                f"= {_money(expected)}, but the total is {_money(total)} "
                f"(difference {_money(abs(diff))}). A fee, discount or rounding line may be missing, "
                "or a value was read incorrectly.", "total"))

    if tax is not None and sub is not None and tax > sub and sub > 0:
        warnings.append(_w("warning", "tax_exceeds_subtotal", "Tax is larger than the subtotal. Check the tax value.", "tax"))

    items = line_items or []
    if items and sub is not None:
        line_sum = round(sum(i.get("amount") or 0 for i in items), 2)
        candidates = {round(sub, 2), round(sub + discount, 2)}
        if total is not None:
            candidates.add(round(total, 2))
        if all(abs(line_sum - c) > TOLERANCE for c in candidates):
            warnings.append(_w(
                "warning", "line_items_mismatch",
                f"The {len(items)} line item(s) add up to {_money(line_sum)}, which doesn't match "
                f"the subtotal ({_money(sub)}). Some rows may be missing or merged.", "subtotal"))

    issued, due = parse_date(inv["invoice_date"]), parse_date(inv["due_date"])
    if inv["invoice_date"] and not issued:
        warnings.append(_w("info", "date_format", "Invoice date format wasn't recognised. Check it.", "invoice_date"))
    if issued and due and due < issued:
        warnings.append(_w("warning", "due_before_issue", "Due date is earlier than the invoice date.", "due_date"))

    return warnings, missing


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def looks_like_invoice(text: str, data: dict) -> bool:
    if re.search(r"\binvoice\b|\breceipt\b|\bbill\s+to\b", text, re.IGNORECASE):
        return True
    return bool(data.get("invoice_number") or (data.get("total") is not None and (data.get("subtotal") is not None or data.get("tax") is not None)))


def analyze_invoice(page_text: Dict[int, str], tables=None) -> Dict[str, Any]:
    """Extract invoice fields and validate them.

    Returns {data, line_items, warnings, missing, is_invoice}.
    """
    text = _clean_text(page_text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # --- totals ----------------------------------------------------------
    total_hit = None
    for pattern in TOTAL_PRIORITY:
        hits = _label_amounts(lines, pattern)
        if hits:
            total_hit = hits[-1]          # totals sit at the bottom of the invoice
            break

    due_hits = _label_amounts(lines, AMOUNT_DUE)
    amount_due = due_hits[-1]["value"] if due_hits else None
    total = total_hit["value"] if total_hit else None
    if total is None and amount_due is not None:
        total = amount_due

    sub_hits = _label_amounts(lines, SUBTOTAL)
    subtotal = sub_hits[-1]["value"] if sub_hits else None

    # --- tax ---------------------------------------------------------------
    tax = tax_rate = None
    tax_hits = _label_amounts(lines, TOTAL_TAX)
    split_hits = _label_amounts(lines, SPLIT_TAX)
    plain_hits = _label_amounts(lines, TAX)

    if tax_hits:
        chosen_line = tax_hits[-1]
        tax = chosen_line["value"]
    elif split_hits:
        tax = round(sum(h["value"] for h in split_hits), 2)
        chosen_line = split_hits[-1]
    elif plain_hits:
        chosen_line = plain_hits[-1]
        tax = chosen_line["value"]
    else:
        chosen_line = None

    rate_source = (chosen_line or {}).get("text") or next(
        (ln for ln in lines if TAX.search(ln) and "%" in ln), "")
    rate_match = re.search(r"(\d+(?:\.\d+)?)\s*%", rate_source)
    if rate_match:
        tax_rate = float(rate_match.group(1))

    discount_hits = _label_amounts(lines, DISCOUNT)
    shipping_hits = _label_amounts(lines, SHIPPING)

    data = {
        "invoice_number": _find_invoice_number(text),
        "invoice_date": _find_date(
            lines,
            [r"\binvoice\s*date\b", r"\bdate\s*of\s*(?:invoice|issue)\b", r"\bissue\s*date\b",
             r"\bissued(?:\s*on)?\b", r"\bbilling\s*date\b", r"\bbill\s*date\b", r"\bdate\b"],
            skip_before=r"(due|payment|ship|delivery|order|expiry|valid)\s*$",
        ),
        "due_date": _find_date(
            lines,
            [r"\bdue\s*date\b", r"\bpayment\s*due(?:\s*date)?\b", r"\bpay\s*by\b", r"\bdate\s*due\b", r"\bdue\s*on\b"],
        ),
        "currency": _detect_currency(text, total_hit["text"] if total_hit else None),
        "subtotal": subtotal,
        "discount": abs(discount_hits[-1]["value"]) if discount_hits else None,
        "shipping": shipping_hits[-1]["value"] if shipping_hits else None,
        "tax_rate": tax_rate,
        "tax": tax,
        "total": total,
        "amount_due": amount_due if amount_due != total else None,
        "email": _find_email(text),
        "phone": _find_phone(text),
        "extraction_method": "rule-based",
    }

    line_items = extract_line_items(tables)
    warnings, missing = validate_invoice(data, line_items)

    return {
        "data": data,
        "line_items": line_items,
        "warnings": warnings,
        "missing": missing,
        "is_invoice": looks_like_invoice(text, data),
    }


def extract_invoice_data(page_text: Dict[int, str], tables=None) -> Dict[str, Any]:
    """Backward-compatible helper: just the extracted fields."""
    return analyze_invoice(page_text, tables)["data"]