# DocuExtract: PDF Data Converter

A Flask web app that extracts tables and invoice data from PDFs, reads scanned documents with OCR, and merges or splits PDFs.

## Setup

    pip install -r requirements.txt

For scanned PDFs install the **Tesseract OCR** program too (the app works without it, but scanned pages are skipped with a warning):

- Windows: https://github.com/UB-Mannheim/tesseract/wiki, then set `TESSERACT_CMD` to the `tesseract.exe` path if it is not on PATH
- macOS: `brew install tesseract`
- Linux: `sudo apt install tesseract-ocr`

## Run

    python app.py        # http://127.0.0.1:5000

## Features

| Page | What it does |
|------|--------------|
| `/` | Dashboard: tools, recent conversions, privacy information |
| `/excel` `/csv` `/json` | Convert tables to Excel, CSV or JSON (multiple tables get separate preview tabs) |
| `/invoice` | Invoice number, dates, subtotal, discount, shipping, tax, total; editable fields, warnings, export to JSON or Excel |
| `/batch` | Upload several PDFs, review each, download one ZIP (or one combined invoice workbook) |
| `/merge` | Merge PDFs in a chosen order |
| `/split` | Split into single pages or ranges, or extract pages into one PDF |

Every converter page also accepts several files at once, and has Copy text / Download .txt on the Text tab.

## Error handling

Corrupted, password-protected, empty, wrongly-named (for example a PNG renamed to .pdf) and oversized files each return a specific message. PDFs with only an *owner* password (print/copy restrictions) still open.

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_FILE_MB` | 50 | Max size per uploaded file |
| `MAX_PAGES` | 300 | Max pages per PDF for extraction |
| `MAX_OCR_PAGES` | 25 | Max pages OCR'd per file |
| `TESSERACT_CMD` | (PATH) | Path to the Tesseract executable |
| `TESSERACT_LANG` | eng | OCR language(s), e.g. `eng+urd` |

## Privacy

Uploads are written to a temporary folder only while a request runs and are deleted immediately after. Nothing is stored in a database. Recent conversions (file names and counts only) are kept in the browser's local storage.

## Notes and limits

- Invoice extraction is rule-based pattern matching, not AI. Values are cross-checked (subtotal + tax = total) and unusual layouts will produce warnings. Always review important figures.
- Tables on scanned pages cannot be rebuilt; OCR text and invoice fields are still extracted.
- Command line: `python cli.py samples/sample.pdf -o result.xlsx`