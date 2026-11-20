
"""
Web UI: python app.py

Routes:
http://127.0.0.1:5000       -> PDF to Excel
http://127.0.0.1:5000/csv   -> PDF to CSV
http://127.0.0.1:5000/json  -> PDF to JSON
"""

import io
import tempfile
from pathlib import Path

from flask import Flask, render_template, request, send_file

from pdfconverter import extract_pdf, write_excel
from pdfconverter.to_csv import export_csv
from pdfconverter.json_export import export_json
from pdfconverter.to_excel import convert_value

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


def _read_pdf():
    """Save uploaded PDF, extract data and return (doc, filename)."""

    f = request.files.get("pdf")

    if not f or not f.filename:
        return ("Please upload a PDF file", 400), None

    if not f.filename.lower().endswith(".pdf"):
        return ("Please upload a valid .pdf file", 400), None

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.pdf"
        f.save(src)

        try:
            doc = extract_pdf(str(src))
        except Exception:
            app.logger.exception("PDF extraction failed")
            return ("Could not read PDF. It may be corrupt or encrypted.", 422), None

    doc.filename = f.filename

    return doc, f.filename


@app.get("/")
def index():
    return render_template("index.html", mode="excel")


@app.get("/csv")
def csv_page():
    return render_template("index.html", mode="csv")


@app.get("/json")
def json_page():
    return render_template("index.html", mode="json")


@app.post("/preview")
def preview():
    doc, name = _read_pdf()

    if name is None:
        return doc

    def fmt(c):
        v = convert_value(c)[0]
        return v.strftime("%d-%m-%Y") if hasattr(v, "strftime") else v

    tables = [
        {
            "name": f"P{t.page}_Table{t.index}",
            "header": t.header,
            "rows": [
                [fmt(c) for c in r]
                for r in t.rows[:200]
            ],
            "raw": t.rows[:200],
            "total_rows": len(t.rows)
        }
        for t in doc.tables
    ]

    return {
        "pages": doc.page_count,
        "tables": tables
    }


@app.post("/convert")
def convert():
    """Convert PDF to Excel."""

    doc, name = _read_pdf()

    if name is None:
        return doc

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "output.xlsx"

        write_excel(
            doc,
            str(out),
            convert_types=request.form.get("raw") != "on"
        )

        data = out.read_bytes()

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=Path(name).stem + ".xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.post("/convert-csv")
def convert_csv():
    """Convert PDF to CSV."""

    doc, name = _read_pdf()

    if name is None:
        return doc

    data, fname, mime = export_csv(doc, Path(name).stem)

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=fname,
        mimetype=mime
    )


@app.post("/convert-json")
def convert_json():
    """Convert PDF to structured JSON."""

    doc, name = _read_pdf()

    if name is None:
        return doc

    data, fname, mime = export_json(doc, Path(name).stem)

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=fname,
        mimetype=mime
    )


if __name__ == "__main__":
    app.run(debug=True)
