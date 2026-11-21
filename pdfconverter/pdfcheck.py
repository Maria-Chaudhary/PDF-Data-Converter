"""Fast PDF sanity checks: real PDF? corrupted? password-protected?"""
from __future__ import annotations

import logging
import os
from typing import Optional

from pypdf import PdfReader

from .errors import (
    CorruptPDFError,
    EmptyPDFError,
    EncryptedPDFError,
    PDFProcessingError,
    TooManyPagesError,
    UnsupportedFileError,
)

try:  # pypdf raises this when AES support (cryptography) is missing
    from pypdf.errors import DependencyError
except Exception:  # pragma: no cover
    class DependencyError(Exception):
        pass

# pypdf logs a warning for every slightly-damaged file; we report errors ourselves.
logging.getLogger("pypdf").setLevel(logging.ERROR)

_SIGNATURES = [
    (b"\x89PNG", "a PNG image"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"GIF8", "a GIF image"),
    (b"PK\x03\x04", "a ZIP / Office file (.docx, .xlsx, .pptx ...)"),
    (b"\xd0\xcf\x11\xe0", "an older Office file (.doc, .xls, .ppt)"),
    (b"{\\rtf", "an RTF document"),
]


def check_signature(path: str) -> None:
    """Make sure the file really is a PDF, whatever its extension says."""
    if os.path.getsize(path) == 0:
        raise CorruptPDFError("This file is empty (0 bytes).")

    with open(path, "rb") as handle:
        head = handle.read(1024)

    # The PDF spec allows up to 1024 bytes of junk before the header.
    if b"%PDF-" in head:
        return

    for magic, label in _SIGNATURES:
        if head.startswith(magic):
            raise UnsupportedFileError(
                f"This file is {label}, not a PDF. Please upload a real PDF."
            )

    raise UnsupportedFileError(
        "This file doesn't look like a PDF. It may be damaged or a different "
        "file type renamed to .pdf."
    )


def open_pdf(path: str) -> PdfReader:
    """Open a PDF for reading, raising a friendly error if that isn't possible.

    PDFs protected only by an *owner* password (print/copy restrictions) open
    with an empty password and are accepted. PDFs that need a *user* password
    are rejected with EncryptedPDFError.
    """
    check_signature(path)

    try:
        reader = PdfReader(path, strict=False)

        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except DependencyError as exc:
                raise PDFProcessingError(
                    "This PDF uses AES encryption and the server is missing the "
                    "'cryptography' package (pip install cryptography)."
                ) from exc
            except Exception as exc:
                raise EncryptedPDFError() from exc

            if not unlocked:
                raise EncryptedPDFError()

        count = len(reader.pages)
        if count:
            reader.pages[0]  # touch the page tree to surface structural damage
    except PDFProcessingError:
        raise
    except Exception as exc:
        raise CorruptPDFError() from exc

    if count == 0:
        raise EmptyPDFError()

    return reader


def validate_pdf(path: str, max_pages: Optional[int] = None) -> int:
    """Return the page count, or raise a PDFProcessingError."""
    count = len(open_pdf(path).pages)

    if max_pages and count > max_pages:
        raise TooManyPagesError(
            f"This PDF has {count} pages. The limit is {max_pages} pages per file."
        )

    return count