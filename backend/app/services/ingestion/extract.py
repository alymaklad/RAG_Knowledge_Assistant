"""Text extraction. Returns one `Page` per PDF page; DOCX/TXT/MD become a single page with
section headers detected from heading styles or markdown `#` lines."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.services.ingestion.validate import DOCX, MD, PDF, TXT

MIN_PAGE_CHARS = 50  # below this a page is probably an image-only slide


@dataclass(slots=True)
class Section:
    header: str | None
    text: str


@dataclass(slots=True)
class Page:
    page_num: int | None
    sections: list[Section] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(s.text for s in self.sections)


@dataclass(slots=True)
class Extracted:
    pages: list[Page]
    page_count: int
    skipped_pages: list[int]


_NUMBERED_HEADING = re.compile(
    r"^(chapter|section|week|lecture|part)?\s*\d+(\.\d+)*[.:)]?\s+\S", re.I
)


def _pdf_page_sections(page: pymupdf.Page) -> list[Section]:
    """Split a PDF page into sections, treating lines in a noticeably larger font as headers."""
    data = page.get_text("dict")
    lines: list[tuple[str, float, bool]] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            size = max(s.get("size", 0.0) for s in spans)
            bold = all(s.get("flags", 0) & 16 for s in spans)
            lines.append((text, size, bold))
        lines.append(("", 0.0, False))  # block boundary -> paragraph break

    sizes = sorted(size for text, size, _ in lines if text)
    if not sizes:
        return []
    body = sizes[len(sizes) // 2]

    sections: list[Section] = []
    header: str | None = None
    buf: list[str] = []
    for text, size, bold in lines:
        is_header = (
            bool(text)
            and len(text) <= 120
            and (size >= body * 1.25 or (bold and _NUMBERED_HEADING.match(text) is not None))
        )
        if is_header:
            if "".join(buf).strip():
                sections.append(Section(header, "\n".join(buf).strip()))
            header, buf = text, []
        else:
            buf.append(text)
    if "".join(buf).strip():
        sections.append(Section(header, "\n".join(buf).strip()))
    return sections


def extract_pdf(path: str) -> Extracted:
    pages: list[Page] = []
    skipped: list[int] = []
    last_header: str | None = None
    with pymupdf.open(path) as doc:
        count = doc.page_count
        for i, page in enumerate(doc, start=1):
            sections = _pdf_page_sections(page)
            if sum(len(s.text) for s in sections) < MIN_PAGE_CHARS:
                skipped.append(i)
                continue
            # A page without its own header continues the previous page's section.
            for s in sections:
                if s.header is None:
                    s.header = last_header
                last_header = s.header
            pages.append(Page(page_num=i, sections=sections))
    return Extracted(pages=pages, page_count=count, skipped_pages=skipped)


def extract_docx(path: str) -> Extracted:
    import docx

    document = docx.Document(path)
    sections: list[Section] = []
    header: str | None = None
    buf: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "") if para.style is not None else ""
        if style.lower().startswith(("heading", "title")):
            if buf:
                sections.append(Section(header, "\n\n".join(buf)))
            header, buf = text, []
        else:
            buf.append(text)
    for table in document.tables:
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
        buf.append("\n".join(rows))
    if buf:
        sections.append(Section(header, "\n\n".join(buf)))
    return Extracted(
        pages=[Page(None, sections)] if sections else [], page_count=1, skipped_pages=[]
    )


def extract_text(path: str, markdown: bool) -> Extracted:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    if not markdown:
        return Extracted(pages=[Page(None, [Section(None, raw)])], page_count=1, skipped_pages=[])
    sections: list[Section] = []
    header: str | None = None
    buf: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if m:
            if "".join(buf).strip():
                sections.append(Section(header, "\n".join(buf).strip()))
            header, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append(Section(header, "\n".join(buf).strip()))
    return Extracted(pages=[Page(None, sections)], page_count=1, skipped_pages=[])


def extract(path: str, mime_type: str) -> Extracted:
    if mime_type == PDF:
        return extract_pdf(path)
    if mime_type == DOCX:
        return extract_docx(path)
    if mime_type in (TXT, MD):
        return extract_text(path, markdown=mime_type == MD)
    raise ValueError(f"Unsupported mime type {mime_type}")
