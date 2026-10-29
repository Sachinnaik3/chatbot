# ADR 0002: Hybrid retrieval in PostgreSQL with pgvector

Status: Accepted

Context: Control IDs and policy numbers need exact keyword matching. Paraphrased precedent needs semantic matching. Access rules must apply inside retrieval.

Decision: Keyword and vector retrieval combined with reciprocal rank fusion. Access filters run before scoring. Storage in PostgreSQL with pgvector keeps data in the existing controlled database.

Consequences: The keyword leg is in-process BM25 in dev. The production keyword leg uses tsvector and is a planned extension.
