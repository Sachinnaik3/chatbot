"""Turn a knowledge document into indexed chunks. Every chunk keeps its source, version, owner, and access teams."""

from __future__ import annotations

from dataclasses import dataclass

from pia.rag.chunker import chunk_text
from pia.retrieval.index import Chunk


@dataclass(frozen=True)
class KnowledgeDoc:
    source_id: str
    source_type: str
    version: str
    owner: str
    teams: frozenset[str]
    text: str


def chunks_from_doc(doc: KnowledgeDoc) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"{doc.source_id}#{i}",
            source_id=doc.source_id,
            source_type=doc.source_type,
            version=doc.version,
            owner=doc.owner,
            text=piece,
            teams=doc.teams,
        )
        for i, piece in enumerate(chunk_text(doc.text))
    ]
