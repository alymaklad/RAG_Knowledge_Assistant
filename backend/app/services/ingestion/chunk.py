"""Cleaning + token-aware recursive chunking (LangChain's RecursiveCharacterTextSplitter).

Chunk length is measured in BGE-m3 tokens, not characters, so `chunk_size_tokens` means what
it says. Chunks never cross a section boundary; the section header travels as metadata and is
prepended to the text that gets embedded (see `embedding_text`).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.ingestion.extract import Page

SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def clean_text(text: str) -> str:
    text = re.sub(r"\n?\s*Page \d+ of \d+\s*\n?", "\n", text, flags=re.I)
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)  # standalone page numbers
    text = re.sub(r"(\w+)-\s*\n(\w+)", r"\1\2", text)  # hyphenation across line breaks
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@lru_cache(maxsize=4)
def token_counter(tokenizer_name: str) -> Callable[[str], int]:
    if tokenizer_name == "approx":
        return lambda text: max(1, len(text) // 4)
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(tokenizer_name)
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)


@dataclass(slots=True)
class ChunkData:
    chunk_index: int
    text: str
    page_num: int | None
    section_header: str | None
    token_count: int

    @property
    def embedding_text(self) -> str:
        """Header + body: lets a chunk match questions phrased in terms of its section title."""
        return f"{self.section_header}\n{self.text}" if self.section_header else self.text


def chunk_pages(
    pages: list[Page], *, chunk_size: int, chunk_overlap: int, tokenizer_name: str
) -> list[ChunkData]:
    count_tokens = token_counter(tokenizer_name)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=count_tokens,
        separators=SEPARATORS,
        keep_separator="end",
    )
    chunks: list[ChunkData] = []
    for page in pages:
        for section in page.sections:
            text = clean_text(section.text)
            if not text:
                continue
            for piece in splitter.split_text(text):
                piece = piece.strip()
                if len(piece) < 20:
                    continue
                chunks.append(
                    ChunkData(
                        chunk_index=len(chunks),
                        text=piece,
                        page_num=page.page_num,
                        section_header=section.header,
                        token_count=count_tokens(piece),
                    )
                )
    return chunks
