"""Short-term memory: recent conversation turns for one user's session.

Sessions are keyed by user and session ID, so one user can never read another user's turns.
Turns are PII-redacted before storage and expire with a TTL.
"""

from __future__ import annotations

from pia.cache import Cache, cache_key
from pia.guardrails.input import redact_pii


class SessionMemory:
    def __init__(self, cache: Cache, *, max_turns: int = 10, ttl_s: int = 1800) -> None:
        self._cache = cache
        self._max_turns = max_turns
        self._ttl = ttl_s

    def _key(self, user_id: str, session_id: str) -> str:
        return cache_key("session", user_id, session_id)

    def recent(self, user_id: str, session_id: str) -> list[dict[str, str]]:
        import json

        raw = self._cache.get(self._key(user_id, session_id))
        return json.loads(raw) if raw else []

    def append(self, user_id: str, session_id: str, role: str, content: str) -> None:
        import json

        redacted, _ = redact_pii(content[:2000])
        turns = self.recent(user_id, session_id) + [{"role": role, "content": redacted}]
        self._cache.set(self._key(user_id, session_id), json.dumps(turns[-self._max_turns :]), self._ttl)
