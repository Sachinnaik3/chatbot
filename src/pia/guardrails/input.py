"""Input guardrails: prompt-injection signals and PII redaction.

Injection scanning is a detection signal, not a guarantee. It is one layer of several
(delimiters, schema validation, citation checks, no tool or gate authority from text).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (all |any |the )?(previous|prior|above) (instructions|prompts|rules)",
        r"disregard (the )?(system|previous|prior) (prompt|instructions)",
        r"mark (all )?(controls|findings|gates?) as (passed|approved|closed)",
        r"approve (this|the) (review|request|project)",
        r"reveal (your|the) (system )?(prompt|instructions)",
        r"you are now (in )?(developer|unrestricted|admin) mode",
    ]
]

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_NATIONAL_ID = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?\d{10}(?!\d)")


@dataclass(frozen=True)
class ScanResult:
    text: str
    injection_hits: list[str]
    pii_counts: dict[str, int]


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    counts: Counter[str] = Counter()

    def card_sub(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            counts["card"] += 1
            return "[CARD]"
        return match.group(0)

    text = _CARD.sub(card_sub, text)
    text, n = _NATIONAL_ID.subn("[ID]", text)
    counts["national_id"] += n
    text, n = _EMAIL.subn("[EMAIL]", text)
    counts["email"] += n
    text, n = _PHONE.subn("[PHONE]", text)
    counts["phone"] += n
    return text, {k: v for k, v in counts.items() if v}


def scan_input(text: str) -> ScanResult:
    hits = [p.pattern for p in INJECTION_PATTERNS if p.search(text)]
    redacted, counts = redact_pii(text)
    return ScanResult(text=redacted, injection_hits=hits, pii_counts=counts)
