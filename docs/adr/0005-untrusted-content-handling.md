# ADR 0005: Uploaded documents are untrusted data

Status: Accepted

Context: Specs and past reviews can contain text that tries to override instructions (prompt injection).

Decision: Wrap document text in labeled delimiters, scan for injection patterns, never let document text change tools or gate status, and reject any output whose citations are not in the retrieved set.

Consequences: Injection detection is a signal, not a guarantee. Layered controls are required.
