"""
DocuExtract - PDF data extraction & tools

Run:
    python app.py

Pages:
    /          Dashboard
    /excel     PDF to Excel          /csv      PDF to CSV
    /json      PDF to JSON           /invoice  Invoice extraction
    /batch     Batch convert         /merge    Merge PDFs
    /split     Split PDFs

Privacy: uploads live in a temporary folder only while a request is being
handled and are deleted straight afterwards. Nothing is written to a database.
"""

import io
import os
import re
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from pdfconverter import extract_pdf
from pdfconverter.errors import (
    FileTooLargeError,
    InvalidRequestError,
    PDFProcessingError,
    UnsupportedFileError,
)
from pdfconverter.export import build_export
from pdfconverter.invoice import analyze_invoice, normalise_invoice, validate_invoice
from pdfconverter.pdfcheck import validate_pdf
from pdfconverter.tools import merge_pdfs, split_pdf

MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "50"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "300"))
MAX_BATCH_FILES = 20

app = Flask(__name__)
# Whole request (a batch / merge can carry several files).
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * MAX_BATCH_FILES * 1024 * 1024


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _clean_name(raw: str) -> str:
    """Keep unicode (e.g. Urdu) file names; strip paths and unsafe characters."""
    name = Path((raw or "").replace("\\", "/")).name
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    return name


def _save_upload(storage, folder: str, index: int = 0):
    """Save one uploaded file into `folder`. Returns (path, display_name)."""
    if storage is None or not storage.filename:
        raise InvalidRequestError("Please choose a PDF file.")

    name = _clean_name(storage.filename)

    if not name.lower().endswith(".pdf"):
        raise UnsupportedFileError("Only PDF files are supported.", filename=name)

    if name.lower() == ".pdf":
        name = "document.pdf"

    path = Path(folder) / f"upload_{index}.pdf"
    storage.save(path)

    if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise FileTooLargeError(
            f"This file is larger than the {MAX_FILE_MB} MB limit.", filename=name
        )

    return path, name


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidRequestError("Expected a JSON request body.")
    return body


def _file_response(data: bytes, name: str, mimetype: str, **headers):
    response = send_file(
        io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mimetype
    )
    for key, value in headers.items():
        response.headers[key] = str(value)
    return response


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@app.get("/")
def dashboard():
    return render_template("dashboard.html", mode="dashboard")


def _converter(mode):
    def view():
        return render_template(
            "index.html", mode=mode,
            max_file_mb=MAX_FILE_MB, max_files=MAX_BATCH_FILES,
        )
    view.__name__ = f"{mode}_page"
    return view


for _mode in ("excel", "csv", "json", "invoice", "batch"):
    app.add_url_rule(f"/{_mode}", f"{_mode}_page", _converter(_mode), methods=["GET"])


@app.get("/merge")
def merge_page():
    return render_template("merge.html", mode="merge", max_file_mb=MAX_FILE_MB, max_files=MAX_BATCH_FILES)


@app.get("/split")
def split_page():
    return render_template("split.html", mode="split", max_file_mb=MAX_FILE_MB)


# --------------------------------------------------------------------------
# API: inspect, preview, export
# --------------------------------------------------------------------------
@app.post("/info")
def info():
    """Cheap check used on drop: page count, size and early error detection."""
    with tempfile.TemporaryDirectory() as tmp:
        path, name = _save_upload(request.files.get("pdf"), tmp)
        try:
            pages = validate_pdf(str(path))
        except PDFProcessingError as exc:
            exc.filename = name
            raise
        return jsonify(name=name, size=path.stat().st_size, pages=pages)


@app.post("/preview")
def preview():
    """Extract tables, text, OCR and invoice fields from one PDF."""
    with tempfile.TemporaryDirectory() as tmp:
        path, name = _save_upload(request.files.get("pdf"), tmp)
        try:
            doc = extract_pdf(str(path), max_pages=MAX_PAGES)
        except PDFProcessingError as exc:
            exc.filename = name
            raise

    doc.filename = name
    invoice = analyze_invoice(doc.page_text, doc.tables)

    return jsonify({
        "filename": name,
        "pages": doc.page_count,
        "kind": doc.kind,
        "ocr_available": doc.ocr_available,
        "ocr_used": bool(doc.ocr_pages),
        "ocr_pages": doc.ocr_pages,
        "scanned_pages": doc.scanned_pages,
        "warnings": doc.warnings,
        "pages_detail": [
            {**info_, "text": doc.page_text.get(info_["page"], "")}
            for info_ in doc.page_info
        ],
        "tables": [
            {
                "name": f"P{t.page}_Table{t.index}",
                "page": t.page,
                "index": t.index,
                "header": t.header,
                "rows": t.rows,
            }
            for t in doc.tables
        ],
        "invoice": invoice["data"],
        "line_items": invoice["line_items"],
        "invoice_warnings": invoice["warnings"],
        "invoice_missing": invoice["missing"],
        "is_invoice": invoice["is_invoice"],
    })


@app.post("/invoice-check")
def invoice_check():
    """Re-validate invoice values after the user edits them."""
    body = _json_body()
    items = body.get("line_items") if isinstance(body.get("line_items"), list) else []
    warnings, missing = validate_invoice(body.get("invoice"), items)
    return jsonify(invoice=normalise_invoice(body.get("invoice")), warnings=warnings, missing=missing)


@app.post("/export")
def export():
    """Create a download from already-extracted data (one file or a batch)."""
    body = _json_body()
    files = body.get("files")

    if not isinstance(files, list):
        raise InvalidRequestError("Nothing to export.")

    data, name, mimetype = build_export(files, str(body.get("format")), raw=bool(body.get("raw")))
    return _file_response(data, name, mimetype)


# --------------------------------------------------------------------------
# API: merge & split
# --------------------------------------------------------------------------
@app.post("/merge-pdf")
def merge_pdf():
    uploads = [f for f in request.files.getlist("pdf") if f and f.filename]

    if len(uploads) < 2:
        raise InvalidRequestError("Add at least two PDFs to merge.")
    if len(uploads) > MAX_BATCH_FILES:
        raise InvalidRequestError(f"You can merge up to {MAX_BATCH_FILES} PDFs at once.")

    with tempfile.TemporaryDirectory() as tmp:
        items = []
        for i, storage in enumerate(uploads):
            path, name = _save_upload(storage, tmp, i)
            items.append((name, str(path)))

        data, pages = merge_pdfs(items)

    return _file_response(data, "merged.pdf", "application/pdf", **{"X-Pages": pages})


@app.post("/split-pdf")
def split_pdf_route():
    mode = request.form.get("mode", "")
    spec = request.form.get("ranges", "")

    with tempfile.TemporaryDirectory() as tmp:
        path, name = _save_upload(request.files.get("pdf"), tmp)
        data, filename, mimetype, parts = split_pdf(str(path), name, mode, spec)

    return _file_response(data, filename, mimetype, **{"X-Parts": parts})


# --------------------------------------------------------------------------
# errors (always JSON so the UI can show a clear message)
# --------------------------------------------------------------------------
@app.errorhandler(PDFProcessingError)
def handle_pdf_error(error):
    return jsonify(error.to_dict()), error.status


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(
        error=f"Upload too large. Each file can be up to {MAX_FILE_MB} MB "
              f"and a batch up to {MAX_BATCH_FILES} files.",
        code="file_too_large",
    ), 413


@app.errorhandler(Exception)
def unexpected(error):
    if isinstance(error, HTTPException):
        return error

    app.logger.exception("Unexpected error")
    return jsonify(
        error="Something went wrong while processing this file. "
              "It may be damaged or use an unsupported feature.",
        code="processing_failed",
    ), 500


if __name__ == "__main__":
    app.run(debug=True)