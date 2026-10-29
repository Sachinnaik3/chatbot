"""Deterministic responder for dev, tests, and offline evals.

It reads the prompt and answers in the expected JSON shape. It cites only sources present
in the prompt and quotes only text present in the spec, so it exercises the happy path.
Guard tests use custom responders that misbehave on purpose.
"""

from __future__ import annotations

import json
import re

_SOURCE = re.compile(r'<source id="([^"]+)"')
_ITEM = re.compile(r'<item id="([^"]+)"')
_QUESTION = re.compile(r"^- id=([^:]+): ", re.M)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

TRACK_HINTS = {
    "privacy_review": ("personal", "customer data", "retention", "pii"),
    "infosec_review": ("encrypt", "access", "authentication", "api key"),
    "risk_review": ("payment", "ledger", "transaction", "reconciliation"),
}
FACT_HINTS = [
    ("vendor", ("vendor",)),
    ("data_store", ("stored", "database", "store ")),
    ("data_flow", ("sends", "flows", "transfers")),
    ("control", ("encrypt", "rotation", "logged")),
    ("integration", (" api", "integrat")),
]


def _block(user: str, label: str) -> str:
    m = re.search(rf'<untrusted_content label="{label}">\n(.*?)\n</untrusted_content>', user, re.S)
    return m.group(1) if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def _intake(user: str) -> dict:
    request = _block(user, "request")
    low = request.lower()
    data_types = [t for t in ("payment data", "personal data", "card data") if t in low]
    return {
        "summary": request[:200],
        "data_types": data_types,
        "customer_facing": "customer" in low,
        "vendors": re.findall(r"vendor (\w+)", request, re.I),
        "regions": re.findall(r"\b(EU|US|India|UK)\b", request),
        "missing_information": [],
    }


def _facts(user: str) -> dict:
    facts = []
    for sentence in _sentences(_block(user, "spec")):
        low = f" {sentence.lower()}"
        for category, keys in FACT_HINTS:
            if any(k in low for k in keys):
                name = " ".join(sentence.split()[:5])
                facts.append({"category": category, "name": name, "detail": "", "evidence": sentence})
                break
    return {"facts": facts}


def _domain_review(user: str) -> dict:
    ids = _SOURCE.findall(user)
    spec = _sentences(_block(user, "spec_facts"))
    if not ids and not spec:
        return {"findings": []}
    return {
        "findings": [
            {
                "title": "Confirm the documented control applies to this change",
                "severity": "medium",
                "description": "The change touches an area covered by an approved control.",
                "cited_source_ids": ids[:1],
                "spec_evidence": spec[0] if spec else None,
            }
        ]
    }


def _findings(user: str) -> dict:
    ids = _SOURCE.findall(user)
    out = []
    for line in (ln.strip(" -") for ln in _block(user, "notes").splitlines()):
        if not line:
            continue
        severity = "high" if ("critical" in line.lower() or "high" in line.lower()) else "medium"
        out.append(
            {
                "title": line[:80],
                "severity": severity,
                "owner_role": "project_team",
                "description": line,
                "remediation": "Apply the control approved in the cited precedent." if ids else None,
                "remediation_source_ids": ids[:1],
            }
        )
    return {"findings": out}


def _fix_verification(user: str) -> dict:
    spec = _sentences(_block(user, "spec"))
    finding = _block(user, "finding").lower()
    stems = {w[:6] for w in re.findall(r"[a-z]{6,}", finding)}
    for sentence in spec:
        if stems & {w[:6] for w in re.findall(r"[a-z]{6,}", sentence.lower())}:
            return {"addressed": True, "evidence": sentence, "explanation": "The revised spec addresses it."}
    return {"addressed": False, "evidence": None, "explanation": "No supporting text found."}


def _brief(user: str) -> dict:
    ids = _ITEM.findall(user)
    return {
        "summary": "The package has drafted answers and candidate findings that need the approver's attention.",
        "claims": [{"text": "This item needs attention before approval.", "evidence_ids": [i]} for i in ids[:3]],
    }


def _change(user: str) -> dict:
    diff = _block(user, "diff")
    added = [ln for ln in diff.splitlines() if ln.startswith("added")]
    return {"rereview_required": bool(added), "reasons": [f"Material change: {ln}" for ln in added]}


def grounded_responder(system: str, user: str) -> str:
    ids = _SOURCE.findall(user)
    if "drafting assistant" in system:
        answers = [
            {
                "question_id": qid,
                "answer": "Supported by the cited sources." if ids else None,
                "status": "drafted" if ids else "needs_input",
                "cited_source_ids": ids,
            }
            for qid in _QUESTION.findall(user)
        ]
        return json.dumps({"answers": answers})
    if "triage assistant" in system:
        low = _block(user, "request").lower()
        tracks = [
            {"track": t, "reason": "request mentions a related topic"}
            for t, keys in TRACK_HINTS.items()
            if any(k in low for k in keys)
        ]
        return json.dumps({"tracks": tracks})
    if "answer questions" in system:
        return json.dumps(
            {
                "answer": "Based on the cited sources." if ids else None,
                "status": "drafted" if ids else "needs_input",
                "cited_source_ids": ids[:2],
            }
        )
    if "read-only SQL" in system:
        return json.dumps({"sql": "SELECT COUNT(*) FROM reviews"})
    if "intake assistant" in system:
        return json.dumps(_intake(user))
    if "spec extraction assistant" in system:
        return json.dumps(_facts(user))
    if "review assistant" in system:
        return json.dumps(_domain_review(user))
    if "fix verification assistant" in system:
        return json.dumps(_fix_verification(user))
    if "findings assistant" in system:
        return json.dumps(_findings(user))
    if "decision brief assistant" in system:
        return json.dumps(_brief(user))
    if "change detection assistant" in system:
        return json.dumps(_change(user))
    if "evaluation judge" in system:
        return json.dumps({"score": 4, "rationale": "Supported by the sources."})
    return "{}"
