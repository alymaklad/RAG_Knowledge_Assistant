"""Render the Markdown handouts in eval/corpus into multi-page PDFs (eval/corpus/pdf/).

`# ` is the document title, `## ` a section heading (rendered in a larger font so the
ingestion pipeline detects it), and a line `---page---` starts a new PDF page.

Run from the backend environment:  uv run --project backend python eval/build_corpus.py
"""

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent / "corpus"
OUT = ROOT / "pdf"
MARGIN = 64
WIDTH, HEIGHT = 612, 792


def render(md: str) -> bytes:
    doc = pymupdf.open()
    pages = [p.strip() for p in md.split("---page---")]
    for page_md in pages:
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        y = MARGIN
        for block in page_md.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            if block.startswith("# "):
                size, text, gap = 22, block[2:], 14
            elif block.startswith("## "):
                size, text, gap = 15, block[3:], 8
            else:
                size, text, gap = 10.5, " ".join(block.split("\n")), 9
            rect = pymupdf.Rect(MARGIN, y, WIDTH - MARGIN, HEIGHT - MARGIN)
            spare = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
            if spare < 0:
                raise ValueError(f"Page overflow while placing: {text[:60]!r}")
            used = rect.height - spare
            y += used + gap
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return bytes(data)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for md_path in sorted(ROOT.glob("*.md")):
        pdf = render(md_path.read_text(encoding="utf-8"))
        target = OUT / f"{md_path.stem}.pdf"
        target.write_bytes(pdf)
        print(f"{target.name}: {len(pdf) // 1024} KB")


if __name__ == "__main__":
    main()
