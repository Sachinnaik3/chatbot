"""Builds the source block the model sees, and the SourceRef returned to callers."""

from __future__ import annotations

from collections.abc import Iterable

from pia.retrieval.index import Chunk
from pia.schemas import SourceRef

SNIPPET_CHARS = 1200


def build_sources_block(chunks: Iterable[Chunk]) -> str:
    return "\n".join(
        f'<source id="{c.chunk_id}" type="{c.source_type}" owner="{c.owner}" version="{c.version}">\n'
        f"{c.text[:SNIPPET_CHARS]}\n</source>"
        for c in chunks
    )


def source_ref(chunk: Chunk) -> SourceRef:
    return SourceRef(
        source_id=chunk.chunk_id,
        source_type=chunk.source_type,
        version=chunk.version,
        owner=chunk.owner,
        excerpt=chunk.text[:500],
    )
