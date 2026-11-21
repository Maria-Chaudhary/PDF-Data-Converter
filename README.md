# DocuExtract: PDF Data Converter

A simple Flask web app that turns PDFs into structured data. It extracts tables and invoice details, reads scanned PDFs with OCR, and can merge or split PDFs.

## Features

- **PDF to Excel, CSV and JSON**, with a separate preview tab for each table
- **Invoice extraction:** invoice number, dates, subtotal, tax and total, with warnings for missing or mismatched values and editable fields
- **Scanned PDF support** using OCR (Tesseract)
- **Batch upload:** process many PDFs at once
- **Merge and split PDFs**
- **Copy extracted text** and download results
- **Dashboard** with recent conversions, progress bars and a mobile-friendly layout
- **Clear error messages** for corrupted, password-protected and unsupported files

## Setup

1. Install the requirements:

       pip install -r requirements.txt

2. For scanned PDFs, also install **Tesseract OCR** (optional; the app works without it):
   - Windows: https://github.com/UB-Mannheim/tesseract/wiki
   - macOS: `brew install tesseract`
   - Linux: `sudo apt install tesseract-ocr`

   If Tesseract is not found on Windows, set its path:

       $env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"

## Run

    python app.py

Then open http://127.0.0.1:5000

## Pages

| Page | Use |
|------|-----|
| `/` | Dashboard |
| `/excel`, `/csv`, `/json` | Convert tables |
| `/invoice` | Invoice data extraction |
| `/batch` | Batch convert |
| `/merge` | Merge PDFs |
| `/split` | Split PDFs |

## Settings (optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_FILE_MB` | 50 | Max file size |
| `MAX_PAGES` | 300 | Max pages per PDF |
| `MAX_OCR_PAGES` | 25 | Max pages read with OCR |
| `TESSERACT_CMD` | auto | Path to Tesseract |
| `TESSERACT_LANG` | eng | OCR language, e.g. `eng+urd` |

## Privacy

Uploaded PDFs are processed in a temporary folder and deleted right after. Nothing is saved on the server. Recent conversions (file names and counts only) are stored in your browser.

## Notes

- Invoice extraction uses pattern matching, not AI. Always check important figures.
- Tables in scanned pages cannot be rebuilt, but the text and invoice fields are still extracted.
- Command line: `python cli.py samples/sample.pdf -o result.xlsx`

## Tech stack

Python, Flask, pdfplumber, pypdf, Tesseract OCR, openpyxl, JavaScript, HTML/CSS
