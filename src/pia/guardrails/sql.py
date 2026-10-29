"""Text-to-SQL validator. Generated SQL is untrusted.

Rules: one statement, SELECT only, allowlisted tables only, no data-modifying nodes,
no denied functions, and a row limit. Execution also runs under a read-only role
with row-level security (see migrations and ADR 0004).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class SQLViolation(Exception):
    pass


FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)
DENIED_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_ls_dir",
    "pg_terminate_backend",
    "dblink",
    "lo_import",
    "lo_export",
    "set_config",
}


def validate_sql(
    sql: str,
    allowed_tables: frozenset[str],
    *,
    max_rows: int = 1000,
    allowed_columns: frozenset[str] | None = None,
) -> str:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLViolation("unparseable SQL") from exc

    if len(statements) != 1:
        raise SQLViolation("exactly one statement is required")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise SQLViolation("only SELECT is allowed")
    if any(True for _ in tree.find_all(*FORBIDDEN_NODES)):
        raise SQLViolation("data-modifying construct found")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
    unknown = tables - cte_names - {t.lower() for t in allowed_tables}
    if unknown:
        raise SQLViolation(f"table not allowed: {sorted(unknown)}")

    if allowed_columns is not None:
        aliases = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
        columns = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
        bad = columns - aliases - {c.lower() for c in allowed_columns}
        if bad:
            raise SQLViolation(f"column not allowed: {sorted(bad)}")

    for fn in tree.find_all(exp.Func):
        name = (fn.name or "").lower()
        if name in DENIED_FUNCTIONS:
            raise SQLViolation(f"function not allowed: {name}")

    current = tree.args.get("limit")
    if current is None:
        tree = tree.limit(max_rows)
    else:
        try:
            n = int(current.expression.name)
        except (AttributeError, ValueError) as exc:
            raise SQLViolation("LIMIT must be a literal number") from exc
        if n > max_rows:
            tree = tree.limit(max_rows)

    return tree.sql(dialect="postgres")
