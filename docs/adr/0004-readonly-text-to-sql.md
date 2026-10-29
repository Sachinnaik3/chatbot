# ADR 0004: Read-only, allowlisted text-to-SQL

Status: Accepted

Context: Generated SQL is untrusted. Review data includes sensitive records.

Decision: Parse every generated query with sqlglot. Allow a single SELECT only, against allowlisted tables, with denied functions blocked and a row limit added. Execute under a database role with SELECT grants only and row-level security.

Consequences: Some valid questions will be refused. Refusals are logged and reviewed to improve the allowlist.
