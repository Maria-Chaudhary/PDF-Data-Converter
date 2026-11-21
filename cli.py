"""Command line:  python cli.py input.pdf [-o output.xlsx] [--pages 1,2] [--raw]"""
import argparse
import sys
from pathlib import Path

from pdfconverter import PDFProcessingError, extract_pdf, write_excel


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert PDF tables to Excel")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output")
    ap.add_argument("--pages", help="comma-separated page numbers, e.g. 1,3")
    ap.add_argument("--raw", action="store_true", help="keep every cell as text (no number/date conversion)")
    a = ap.parse_args()

    src = Path(a.pdf)
    if not src.exists():
        print(f"File not found: {src}", file=sys.stderr)
        return 1
    out = a.output or str(src.with_suffix(".xlsx"))
    pages = [int(p) for p in a.pages.split(",")] if a.pages else None

    try:
        doc = extract_pdf(str(src), pages)
    except PDFProcessingError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 2

    write_excel(doc, out, convert_types=not a.raw)
    print(f"{doc.page_count} page(s), {len(doc.tables)} table(s) -> {out}")
    if doc.ocr_pages:
        print(f"OCR used on page(s): {', '.join(map(str, doc.ocr_pages))}")
    for w in doc.warnings:
        print(f"[{w['level']}] {w['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())