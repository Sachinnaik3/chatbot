"""Hybrid retrieval: BM25 keyword scoring + cosine vector scoring, fused with reciprocal rank fusion.

Access control runs before scoring. A chunk the caller cannot see is never scored,
ranked, or returned, so it cannot leak through ranking or result counts.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from pia.retrieval.embeddings import Embedder, tokenize

RRF_K = 60


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    source_type: str
    version: str
    owner: str
    text: str
    teams: frozenset[str]
    retired: bool = False


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridIndex:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: dict[str, Chunk] = {}
        self._tf: dict[str, Counter[str]] = {}
        self._length: dict[str, int] = {}
        self._df: Counter[str] = Counter()
        self._vectors: dict[str, list[float]] = {}

    def __len__(self) -> int:
        return sum(1 for c in self._chunks.values() if not c.retired)

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_id in self._chunks:
                raise ValueError(f"duplicate chunk: {chunk.chunk_id}")
            tokens = tokenize(chunk.text)
            tf = Counter(tokens)
            self._chunks[chunk.chunk_id] = chunk
            self._tf[chunk.chunk_id] = tf
            self._length[chunk.chunk_id] = len(tokens)
            self._df.update(tf.keys())
            self._vectors[chunk.chunk_id] = self._embedder.embed(chunk.text)

    def retire_where(self, predicate: Callable[[Chunk], bool]) -> int:
        """Soft-delete chunks. Used for expired policies and for right-to-erasure requests."""
        count = 0
        for cid, chunk in list(self._chunks.items()):
            if not chunk.retired and predicate(chunk):
                self._chunks[cid] = replace(chunk, retired=True)
                count += 1
        return count

    def search(self, query: str, teams: frozenset[str], k: int = 5, pool: int = 20) -> list[Hit]:
        visible = [cid for cid, c in self._chunks.items() if not c.retired and (c.teams & teams)]
        if not visible:
            return []
        keyword = self._bm25(query, visible)
        semantic = self._cosine(query, visible)
        ranked_kw = sorted(keyword, key=keyword.get, reverse=True)[:pool]
        ranked_sem = sorted(semantic, key=semantic.get, reverse=True)[:pool]
        fused = reciprocal_rank_fusion([ranked_kw, ranked_sem])[:k]
        return [Hit(self._chunks[cid], score) for cid, score in fused]

    def _bm25(self, query: str, candidates: list[str], k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
        n = len(self._chunks)
        avgdl = sum(self._length.values()) / max(n, 1) or 1.0
        terms = set(tokenize(query))
        scores: dict[str, float] = {}
        for cid in candidates:
            tf = self._tf[cid]
            dl = self._length[cid]
            score = 0.0
            for term in terms:
                if term not in tf:
                    continue
                df = self._df[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                f = tf[term]
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
            if score > 0:
                scores[cid] = score
        return scores

    def _cosine(self, query: str, candidates: list[str]) -> dict[str, float]:
        qv = self._embedder.embed(query)
        scores: dict[str, float] = {}
        for cid in candidates:
            dot = sum(a * b for a, b in zip(qv, self._vectors[cid], strict=True))
            if dot > 0:
                scores[cid] = dot
        return scores
