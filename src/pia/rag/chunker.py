"""Paragraph-aware chunking with overlap, so a fact is not cut in half at a boundary."""

from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    if max_chars <= overlap:
        raise ValueError("max_chars must be greater than overlap")
    paragraphs = [p.strip() for p in _PARA.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        while len(para) > max_chars:
            cut = para.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if buf and len(buf) + 2 + len(para) > max_chars:
            chunks.append(buf)
            buf = buf[-overlap:].strip()
        buf = f"{buf}\n\n{para}".strip() if buf else para
    if buf:
        chunks.append(buf)
    return chunks
