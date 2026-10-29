# ADR 0003: AI cannot pass review gates

Status: Accepted

Context: Approval decisions carry compliance and accountability requirements.

Decision: Gate endpoints reject AI and service principals. Every gate decision is written to the audit log with the human identity.

Consequences: Throughput depends on human reviewers. This is intentional.
