"""Upload validation: size, real content type (magic bytes), extension match, unsafe PDFs."""

from dataclasses import dataclass
from pathlib import PurePath

import filetype

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"
MD = "text/markdown"

ALLOWED: dict[str, tuple[str, ...]] = {
    PDF: (".pdf",),
    DOCX: (".docx",),
    TXT: (".txt",),
    MD: (".md", ".markdown"),
}


class InvalidUpload(ValueError):
    pass


@dataclass(slots=True)
class ValidatedFile:
    mime_type: str
    extension: str


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def validate_upload(filename: str, data: bytes, max_bytes: int) -> ValidatedFile:
    if not data:
        raise InvalidUpload("File is empty")
    if len(data) > max_bytes:
        raise InvalidUpload(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")

    ext = PurePath(filename).suffix.lower()
    kind = filetype.guess(data)  # never trust the client's Content-Type header
    if kind is not None:
        mime = kind.mime
    elif ext in (".md", ".markdown") and _looks_like_text(data):
        mime = MD
    elif _looks_like_text(data):
        mime = TXT
    else:
        raise InvalidUpload("Unrecognized file type")

    if mime not in ALLOWED:
        raise InvalidUpload(f"File type {mime} is not supported (PDF, DOCX, TXT, MD)")
    if ext not in ALLOWED[mime]:
        raise InvalidUpload("File extension does not match its content")

    if mime == PDF and (b"/JavaScript" in data or b"/JS " in data or b"/Launch" in data):
        raise InvalidUpload("PDFs with embedded scripts or launch actions are not allowed")
    return ValidatedFile(mime_type=mime, extension=ext)
