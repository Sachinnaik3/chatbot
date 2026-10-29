"""Output guardrails: every drafted claim must cite a retrieved, accessible source."""

from __future__ import annotations


class GuardrailViolation(Exception):
    pass


def resolve_citations(cited: list[str], allowed: set[str]) -> tuple[list[str], list[str]]:
    """Split citations into (valid, invalid), preserving order and removing duplicates."""
    seen: set[str] = set()
    valid: list[str] = []
    invalid: list[str] = []
    for cid in cited:
        if cid in seen:
            continue
        seen.add(cid)
        (valid if cid in allowed else invalid).append(cid)
    return valid, invalid


def enforce_supported(status: str, answer: str | None, valid_citations: list[str]) -> str:
    """An answer is only 'drafted' when it has text and at least one valid citation.
    Anything else becomes 'needs_input'. Unsupported text is never shown as a draft."""
    if status == "drafted" and answer and answer.strip() and valid_citations:
        return "drafted"
    return "needs_input"


def normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def is_grounded_quote(quote: str | None, source_text: str, *, min_chars: int = 8) -> bool:
    """True only if the quote appears in the source text (whitespace and case normalized).
    Short quotes are rejected because they match too easily."""
    if not quote:
        return False
    q = normalize_text(quote)
    return len(q) >= min_chars and q in normalize_text(source_text)


def numbers_in(text: str) -> set[str]:
    import re

    return set(re.findall(r"\d+(?:\.\d+)?", text))
