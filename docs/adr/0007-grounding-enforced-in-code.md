# ADR 0007: Grounding is enforced in code, not trusted from the model

Status: Accepted

Context: Prompts ask models to cite and quote, but models do not always comply.

Decision: Every agent checks grounding after the model returns: citations must be in the retrieved, accessible set; quotes must appear in the source text; counts come from records; deterministic rules set floors the model cannot lower. Each guard has a misbehaving-model test and a mutation check.

Consequences: Some correct but unquoted model output is discarded. That trade favors precision, which is right for risk review.
