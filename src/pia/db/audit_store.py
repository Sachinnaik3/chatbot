"""Database-backed, hash-chained audit log.

Same chaining rule as the in-memory log. Two writers racing for the same sequence number
collide on the primary key; the loser retries against the new head, so the chain never forks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pia.audit import GENESIS, AuditEvent, _digest
from pia.db.models import AuditRow

MAX_RETRIES = 5


def _to_event(row: AuditRow) -> AuditEvent:
    return AuditEvent(
        seq=row.seq,
        ts=row.ts,
        actor=row.actor,
        actor_type=row.actor_type,
        action=row.action,
        review_id=row.review_id,
        payload=row.payload,
        prev_hash=row.prev_hash,
        hash=row.hash,
    )


class SqlAuditLog:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def append(
        self,
        actor: str,
        actor_type: str,
        action: str,
        review_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        for _ in range(MAX_RETRIES):
            try:
                with self._sf() as session, session.begin():
                    head = session.execute(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)).scalar_one_or_none()
                    body = {
                        "seq": (head.seq + 1) if head else 1,
                        "ts": datetime.now(UTC).isoformat(),
                        "actor": actor,
                        "actor_type": actor_type,
                        "action": action,
                        "review_id": review_id,
                        "payload": payload or {},
                        "prev_hash": head.hash if head else GENESIS,
                    }
                    row = AuditRow(hash=_digest(body), **body)
                    session.add(row)
                return _to_event(row)
            except IntegrityError:
                continue
        raise RuntimeError("audit append failed after retries")

    def events(self, review_id: str | None = None) -> list[AuditEvent]:
        with self._sf() as session:
            stmt = select(AuditRow).order_by(AuditRow.seq)
            if review_id is not None:
                stmt = stmt.where(AuditRow.review_id == review_id)
            return [_to_event(r) for r in session.execute(stmt).scalars()]

    def verify(self) -> bool:
        prev = GENESIS
        for event in self.events():
            if event.prev_hash != prev or _digest(event.body()) != event.hash:
                return False
            prev = event.hash
        return True
