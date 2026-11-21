"""Typed errors so the API can tell users exactly what went wrong."""
from __future__ import annotations


class PDFProcessingError(Exception):
    """Base class for every expected, user-facing PDF problem."""

    code = "pdf_error"
    status = 422
    message = "This PDF could not be processed."

    def __init__(self, message: str | None = None, filename: str | None = None):
        self.message = message or self.message
        self.filename = filename
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"error": self.message, "code": self.code, "filename": self.filename}


class UnsupportedFileError(PDFProcessingError):
    code = "unsupported_file"
    status = 415
    message = "Only PDF files are supported."


class CorruptPDFError(PDFProcessingError):
    code = "corrupt_pdf"
    message = (
        "This PDF looks corrupted or incomplete and can't be read. "
        "Try downloading or exporting it again."
    )


class EncryptedPDFError(PDFProcessingError):
    code = "password_protected"
    message = (
        "This PDF is password-protected. Remove the password in your PDF "
        "viewer (save a copy without a password) and upload it again."
    )


class EmptyPDFError(PDFProcessingError):
    code = "empty_pdf"
    message = "This PDF has no pages."


class FileTooLargeError(PDFProcessingError):
    code = "file_too_large"
    status = 413
    message = "This file is too large."


class TooManyPagesError(PDFProcessingError):
    code = "too_many_pages"
    status = 413
    message = "This PDF has too many pages to process at once."


class InvalidRequestError(PDFProcessingError):
    code = "bad_request"
    status = 400
    message = "The request was not valid."