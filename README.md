<<<<<<< HEAD
# PDF Converter — Step 1: PDF → Excel

## Setup
    pip install -r requirements.txt

## Use
**Command line**

    python cli.py samples/sample.pdf -o result.xlsx
    python cli.py report.pdf --pages 1,2      # only some pages
    python cli.py report.pdf --raw            # keep every cell as text

**Web app**

    python app.py        # open http://127.0.0.1:5000

## How it works
1. `pdfconverter/extract.py` finds tables with pdfplumber (ruled tables first, then
   whitespace-aligned fallback), cleans cells, detects headers, merges tables that
   continue across pages.
2. `pdfconverter/to_excel.py` writes one sheet per table plus a Summary sheet, converts
   numbers/dates/percentages to real Excel values, styles headers, freezes panes, adds filters.

## Limits
- Scanned (image) PDFs have no text layer; they need OCR (planned add-on).
- Complex merged-cell tables may need tweaking.

## Roadmap
- [ ] Step 2: PDF → CSV (reuse `extract_pdf`, ~10 lines)
- [ ] Step 3: PDF → JSON (blocks, tables, bounding boxes like your Image 2)
- [ ] OCR for scanned PDFs
=======
# PDF-Data-Converter
A Python-based web application that extracts tabular data from PDF files and converts it into Excel, CSV, and JSON formats. It provides a simple interface to upload PDFs, preview extracted tables, and download converted files.
>>>>>>> 6979425f16243313705b62d0ace218ad39aaca27
