"""Small demo corpus for dev. Synthetic content only. Replace with the knowledge service in stage and prod."""

from pia.rag.ingest import KnowledgeDoc

DEMO_DOCS: list[KnowledgeDoc] = [
    KnowledgeDoc(
        source_id="policy-enc-001",
        source_type="policy",
        version="v3",
        owner="infosec-policy-owner",
        teams=frozenset({"infosec", "risk", "project"}),
        text=(
            "Customer payment data must be encrypted at rest using AES-256. "
            "Encryption keys are managed in the approved key management service.\n\n"
            "Key rotation occurs at least annually, and rotation events are logged."
        ),
    ),
    KnowledgeDoc(
        source_id="past-review-2024-117",
        source_type="past_review",
        version="v1",
        owner="risk-team",
        teams=frozenset({"risk", "project"}),
        text=(
            "Past review of a ledger change. Reviewers asked how reconciliation failures are detected. "
            "Approved control: a daily reconciliation job with alerting to the finance operations queue."
        ),
    ),
    KnowledgeDoc(
        source_id="policy-priv-004",
        source_type="policy",
        version="v2",
        owner="privacy-office",
        teams=frozenset({"privacy", "project"}),
        text=(
            "Personal data may be retained only for the period defined in the retention schedule. "
            "Retention exceptions require privacy office approval."
        ),
    ),
    KnowledgeDoc(
        source_id="restricted-review-2025-009",
        source_type="past_review",
        version="v1",
        owner="security",
        teams=frozenset({"security"}),
        text="Restricted review: details of an incident response exercise. Visible only to the security team.",
    ),
]
