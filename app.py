
"""
PDF Data Extraction & Conversion Tool

Run:
    python app.py

Routes:
    /          PDF to Excel
    /csv       PDF to CSV
    /json      PDF to JSON
    /invoice   Invoice data extraction
"""

import io
import json
import tempfile
from pathlib import Path

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from pdfconverter import extract_pdf, write_excel
from pdfconverter.to_csv import export_csv
from pdfconverter.json_export import export_json
from pdfconverter.to_excel import convert_value
from pdfconverter.invoice import extract_invoice_data


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def _read_pdf():
    """Save uploaded PDF temporarily and extract its content."""

    uploaded = request.files.get("pdf")

    if not uploaded or not uploaded.filename:
        return ("Please upload a PDF file.", 400), None

    original_name = secure_filename(uploaded.filename)

    if not original_name or not original_name.lower().endswith(".pdf"):
        return ("Please upload a valid PDF file.", 400), None

    try:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.pdf"
            uploaded.save(source)

            doc = extract_pdf(str(source))

        doc.filename = original_name

        # Extract common invoice fields from normal PDF text or OCR text.
        doc.invoice_data = extract_invoice_data(doc.page_text)

        return doc, original_name

    except Exception:
        app.logger.exception("PDF extraction failed")
        return (
            "Could not read this PDF. It may be corrupt, encrypted, "
            "or unsupported.",
            422
        ), None


def _format_preview_value(value):
    converted = convert_value(value)[0]

    if hasattr(converted, "strftime"):
        return converted.strftime("%d-%m-%Y")

    return converted


def _build_tables_preview(doc):
    """Build a limited preview without changing the complete export data."""

    return [
        {
            "name": f"P{table.page}_Table{table.index}",
            "page": table.page,
            "header": table.header,
            "rows": [
                [_format_preview_value(cell) for cell in row]
                for row in table.rows[:200]
            ],
            "raw": table.rows[:200],
            "total_rows": len(table.rows)
        }
        for table in doc.tables
    ]


@app.get("/")
def index():
    return render_template("index.html", mode="excel")


@app.get("/csv")
def csv_page():
    return render_template("index.html", mode="csv")


@app.get("/json")
def json_page():
    return render_template("index.html", mode="json")


@app.get("/invoice")
def invoice_page():
    return render_template("index.html", mode="invoice")


@app.post("/preview")
def preview():
    doc, name = _read_pdf()

    if name is None:
        message, status = doc
        return message, status

    tables = _build_tables_preview(doc)

    ocr_pages = getattr(doc, "ocr_pages", [])

    return {
        "filename": name,
        "pages": doc.page_count,
        "tables": tables,
        "invoice": getattr(doc, "invoice_data", {}),
        "ocr_used": bool(ocr_pages),
        "ocr_pages": ocr_pages,
        "document_type": (
            "invoice"
            if any(
                doc.invoice_data.get(key)
                for key in ("invoice_number", "total", "invoice_date")
            )
            else "document"
        )
    }


@app.post("/convert")
def convert():
    """Export extracted PDF data to Excel."""

    doc, name = _read_pdf()

    if name is None:
        message, status = doc
        return message, status

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.xlsx"

        write_excel(
            doc,
            str(output),
            convert_types=request.form.get("raw") != "on"
        )

        data = output.read_bytes()

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=Path(name).stem + ".xlsx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )


@app.post("/convert-csv")
def convert_csv():
    """Export extracted PDF tables to CSV."""

    doc, name = _read_pdf()

    if name is None:
        message, status = doc
        return message, status

    data, filename, mimetype = export_csv(doc, Path(name).stem)

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype
    )


@app.post("/convert-json")
def convert_json():
    """Export tables, page text and invoice fields to JSON."""

    doc, name = _read_pdf()

    if name is None:
        message, status = doc
        return message, status

    data, filename, mimetype = export_json(doc, Path(name).stem)

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype
    )


@app.post("/convert-invoice")
def convert_invoice():
    """Download extracted invoice fields as JSON."""

    doc, name = _read_pdf()

    if name is None:
        message, status = doc
        return message, status

    invoice = {
        "source_file": name,
        "pages": doc.page_count,
        "ocr_used": bool(getattr(doc, "ocr_pages", [])),
        "ocr_pages": getattr(doc, "ocr_pages", []),
        "invoice_data": getattr(doc, "invoice_data", {})
    }

    content = json.dumps(
        invoice,
        ensure_ascii=False,
        indent=4
    ).encode("utf-8")

    return send_file(
        io.BytesIO(content),
        as_attachment=True,
        download_name=Path(name).stem + "_invoice.json",
        mimetype="application/json"
    )


@app.errorhandler(413)
def file_too_large(_error):
    return "File is too large. Maximum upload size is 50 MB.", 413


if __name__ == "__main__":
    app.run(debug=True)
