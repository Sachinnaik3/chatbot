"""Long-term memory: durable facts per user, retrieved by similarity.

Reuses the hybrid index, so the same access filter applies: each user's memories are
visible only to that user. forget() supports right-to-erasure requests.
"""

from __future__ import annotations

import uuid

from pia.guardrails.input import redact_pii
from pia.retrieval.embeddings import Embedder
from pia.retrieval.index import Chunk, HybridIndex


def _owner_team(user_id: str) -> str:
    return f"user:{user_id}"


class LongTermMemory:
    def __init__(self, embedder: Embedder) -> None:
        self._index = HybridIndex(embedder)

    def remember(self, user_id: str, text: str, kind: str = "note") -> str:
        redacted, _ = redact_pii(text[:2000])
        chunk = Chunk(
            chunk_id=f"mem-{uuid.uuid4().hex}",
            source_id=f"memory:{user_id}",
            source_type=kind,
            version="1",
            owner=user_id,
            text=redacted,
            teams=frozenset({_owner_team(user_id)}),
        )
        self._index.add([chunk])
        return chunk.chunk_id

    def recall(self, user_id: str, query: str, k: int = 3) -> list[str]:
        hits = self._index.search(query, frozenset({_owner_team(user_id)}), k=k)
        return [h.chunk.text for h in hits]

    def forget(self, user_id: str) -> int:
        owner = _owner_team(user_id)
        return self._index.retire_where(lambda c: owner in c.teams)
