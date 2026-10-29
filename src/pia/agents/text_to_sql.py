"""Text-to-SQL agent and executor. Generated SQL is validated before it can run. See ADR 0004.

Execution runs in a READ ONLY transaction, under a SELECT-only role, with a statement timeout
and a row cap. Validation and the database role are independent layers; either alone blocks writes.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.guardrails.sql import validate_sql
from pia.prompts.registry import wrap_untrusted
from pia.sql_allowlist import SqlAllowlist

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class SqlProposal(BaseModel):
    sql: str = Field(max_length=4000)


class TextToSqlAgent(Agent):
    prompt_name = "insight_sql"

    def generate(
        self,
        *,
        scope: str,
        question: str,
        schema_text: str | None = None,
        allowed_tables: frozenset[str] | None = None,
        allowlist: SqlAllowlist | None = None,
    ) -> str:
        if allowlist is not None:
            schema_text, allowed_tables = allowlist.schema_text(), allowlist.table_names
        if schema_text is None or allowed_tables is None:
            raise ValueError("schema and allowed tables are required")
        out, _, _ = self._invoke(scope, SqlProposal, schema=schema_text, question=wrap_untrusted("question", question))
        return validate_sql(
            out.sql, allowed_tables, allowed_columns=allowlist.columns if allowlist is not None else None
        )


class ReadOnlySqlExecutor:
    def __init__(self, session_factory, *, role: str | None, timeout_ms: int = 5000, max_rows: int = 1000) -> None:
        if role is not None and not _IDENT.match(role):
            raise ValueError("invalid role name")
        self._sf = session_factory
        self._role = role
        self._timeout_ms = int(timeout_ms)
        self._max_rows = int(max_rows)

    def run(self, validated_sql: str) -> list[dict[str, Any]]:
        with self._sf() as session, session.begin():
            conn = session.connection()
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {self._timeout_ms}")
                if self._role:
                    conn.exec_driver_sql(f"SET LOCAL ROLE {self._role}")
            result = conn.exec_driver_sql(validated_sql)
            rows = result.mappings().fetchmany(self._max_rows)
            data = [dict(r) for r in rows]
            session.rollback()
        return data
