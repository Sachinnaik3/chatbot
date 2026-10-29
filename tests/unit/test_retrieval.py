from pia.rag.chunker import chunk_text
from pia.rag.ingest import KnowledgeDoc, chunks_from_doc
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex, reciprocal_rank_fusion


def _index() -> HybridIndex:
    idx = HybridIndex(HashingEmbedder(256))
    idx.add(
        chunks_from_doc(
            KnowledgeDoc(
                "enc",
                "policy",
                "v1",
                "infosec",
                frozenset({"project"}),
                "Payment data must be encrypted at rest with AES-256.",
            )
        )
    )
    idx.add(
        chunks_from_doc(
            KnowledgeDoc(
                "secret",
                "past_review",
                "v1",
                "security",
                frozenset({"security"}),
                "Restricted incident response exercise for encryption drills.",
            )
        )
    )
    return idx


def test_access_filter_hides_restricted_chunks():
    hits = _index().search("encryption incident response", frozenset({"project"}))
    assert all("project" in h.chunk.teams for h in hits)
    assert "secret" not in {h.chunk.source_id for h in hits}


def test_relevant_chunk_ranks_first():
    hits = _index().search("encrypted at rest AES-256", frozenset({"project"}))
    assert hits and hits[0].chunk.source_id == "enc"


def test_retired_chunks_are_not_returned():
    idx = _index()
    idx.retire_where(lambda c: c.source_id == "enc")
    assert idx.search("encrypted at rest", frozenset({"project"})) == []


def test_rrf_rewards_agreement():
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    assert {fused[0][0], fused[1][0]} == {"a", "b"}
    fused2 = reciprocal_rank_fusion([["x", "y"], ["x", "z"]])
    assert fused2[0][0] == "x"


def test_chunker_respects_max_size():
    text = ("Sentence number %d describes a control. " * 3 + "\n\n") * 40
    chunks = chunk_text(text, max_chars=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 + 50 + 2 for c in chunks)
