"""Production retrieval on PostgreSQL: keyword leg (tsvector/ts_rank) and vector leg (pgvector cosine),
fused with reciprocal rank fusion. The access filter is part of both SQL queries, so chunks the
caller cannot see are never scored. Requires migrations/0001_init.sql.
"""

from __future__ import annotations

from sqlalchemy import text

from pia.retrieval.embeddings import Embedder
from pia.retrieval.index import Chunk, Hit, reciprocal_rank_fusion

_KEYWORD_SQL = text(
    """
    SELECT chunk_id, source_id, source_type, version, owner, text, teams
    FROM knowledge_chunks
    WHERE NOT retired AND teams && :teams
      AND to_tsvector('english', text) @@ plainto_tsquery('english', :q)
    ORDER BY ts_rank(to_tsvector('english', text), plainto_tsquery('english', :q)) DESC
    LIMIT :pool
    """
)
_VECTOR_SQL = text(
    """
    SELECT chunk_id, source_id, source_type, version, owner, text, teams
    FROM knowledge_chunks
    WHERE NOT retired AND teams && :teams
    ORDER BY embedding <=> CAST(:qv AS vector)
    LIMIT :pool
    """
)


def _chunk(row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        source_type=row["source_type"],
        version=row["version"],
        owner=row["owner"],
        text=row["text"],
        teams=frozenset(row["teams"]),
    )


class PgVectorIndex:
    def __init__(self, session_factory, embedder: Embedder) -> None:
        self._sf = session_factory
        self._embedder = embedder

    def search(self, query: str, teams: frozenset[str], k: int = 5, pool: int = 20) -> list[Hit]:
        if not teams:
            return []
        params = {"teams": sorted(teams), "pool": pool}
        with self._sf() as session:
            kw = session.execute(_KEYWORD_SQL, {**params, "q": query}).mappings().all()
            vec = session.execute(_VECTOR_SQL, {**params, "qv": str(self._embedder.embed(query))}).mappings().all()
        chunks = {r["chunk_id"]: _chunk(r) for r in [*kw, *vec]}
        fused = reciprocal_rank_fusion([[r["chunk_id"] for r in kw], [r["chunk_id"] for r in vec]])[:k]
        return [Hit(chunks[cid], score) for cid, score in fused]
