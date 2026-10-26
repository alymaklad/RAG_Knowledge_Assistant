"""Printable quiz PDFs, laid out with PyMuPDF's Story (HTML + CSS that flows across pages)."""

import html
import io
from typing import Any

import pymupdf

CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.4; color: #1f2544; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; }
p.meta { color: #5c6577; font-size: 9pt; margin: 0 0 14pt 0; }
div.q { margin: 0 0 14pt 0; }
p.stem { font-weight: bold; margin: 0 0 4pt 0; }
p.opt { margin: 0 0 2pt 12pt; }
p.ans { margin: 6pt 0 0 12pt; color: #2f7a55; }
p.src { margin: 2pt 0 0 12pt; color: #5c6577; font-size: 9pt; }
h2 { font-size: 13pt; margin: 18pt 0 8pt 0; }
"""


def _e(text: object) -> str:
    return html.escape(str(text or ""))


def quiz_pdf(
    title: str,
    questions: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    *,
    include_answers: bool,
) -> bytes:
    by_index = {s.get("index"): s for s in sources}
    parts = [f"<h1>{_e(title)}</h1><p class='meta'>{len(questions)} questions</p>"]
    for i, q in enumerate(questions, 1):
        parts.append("<div class='q'>")
        parts.append(f"<p class='stem'>{i}. {_e(q.get('question'))}</p>")
        for letter in "ABCD":
            parts.append(f"<p class='opt'>{letter}. {_e(q.get('options', {}).get(letter))}</p>")
        parts.append("</div>")
    if include_answers:
        parts.append("<h2>Answers</h2>")
        for i, q in enumerate(questions, 1):
            src = by_index.get(q.get("source"))
            where = ""
            if src:
                where = _e(src.get("document_name"))
                if src.get("page_num"):
                    where += f", page {src['page_num']}"
            parts.append("<div class='q'>")
            parts.append(
                f"<p class='stem'>{i}. {_e(q.get('correct_answer'))}</p>"
                f"<p class='opt'>{_e(q.get('explanation'))}</p>"
            )
            if where:
                parts.append(f"<p class='src'>Source: {where}</p>")
            parts.append("</div>")

    story = pymupdf.Story(html="".join(parts), user_css=CSS)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    where = page + (54, 54, -54, -54)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
