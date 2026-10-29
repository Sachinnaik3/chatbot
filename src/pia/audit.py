"""Append-only, hash-chained audit log.

Each event includes the hash of the previous event. Editing or deleting any event
breaks the chain, and verify() detects it. Payloads must contain IDs, counts, and
decisions, never document text or answers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    ts: str
    actor: str
    actor_type: str
    action: str
    review_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    def body(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "action": self.action,
            "review_id": self.review_id,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }


def _digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(
        self,
        actor: str,
        actor_type: str,
        action: str,
        review_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        prev = self._events[-1].hash if self._events else GENESIS
        body = {
            "seq": len(self._events) + 1,
            "ts": datetime.now(UTC).isoformat(),
            "actor": actor,
            "actor_type": actor_type,
            "action": action,
            "review_id": review_id,
            "payload": payload or {},
            "prev_hash": prev,
        }
        event = AuditEvent(hash=_digest(body), **body)
        self._events.append(event)
        return event

    def events(self, review_id: str | None = None) -> list[AuditEvent]:
        if review_id is None:
            return list(self._events)
        return [e for e in self._events if e.review_id == review_id]

    def verify(self) -> bool:
        prev = GENESIS
        for event in self._events:
            if event.prev_hash != prev or _digest(event.body()) != event.hash:
                return False
            prev = event.hash
        return True
