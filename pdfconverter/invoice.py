
"""Basic rule-based invoice information extraction."""
from __future__ import annotations

import re


def extract_invoice_data(page_text: dict) -> dict:
    text = "\n".join(page_text.values())

    def find(pattern):
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.MULTILINE
        )
        return match.group(1).strip() if match else None

    invoice_number = find(
        r"(?:invoice\s*(?:number|no|#|id))\s*[:#\-]?\s*([A-Z0-9\-/]+)"
    )

    invoice_date = find(
        r"(?:invoice\s*date|date)\s*[:\-]?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"\d{4}-\d{2}-\d{2})"
    )

    email = find(
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
    )

    phone = find(
        r"(?:phone|mobile|tel)\s*[:\-]?\s*"
        r"([+()\d\s\-]{7,})"
    )

    total = find(
        r"(?:grand\s+total|total\s+amount|amount\s+due|"
        r"total)\s*[:\-]?\s*"
        r"((?:PKR|USD|EUR|GBP|Rs\.?|[$€£])?\s*[\d,]+(?:\.\d{2})?)"
    )

    subtotal = find(
        r"subtotal\s*[:\-]?\s*"
        r"((?:PKR|USD|EUR|GBP|Rs\.?|[$€£])?\s*[\d,]+(?:\.\d{2})?)"
    )

    tax = find(
        r"(?:tax|VAT|GST)\s*[:\-]?\s*"
        r"((?:PKR|USD|EUR|GBP|Rs\.?|[$€£])?\s*[\d,]+(?:\.\d{2})?)"
    )

    return {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "email": email,
        "phone": phone,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "extraction_method": "rule_based_text_extraction"
    }
