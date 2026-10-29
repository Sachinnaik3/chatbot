import pytest

from pia.guardrails.sql import SQLViolation, validate_sql

ALLOWED = frozenset({"reviews", "drafts"})


def test_simple_select_passes_and_gets_limit():
    out = validate_sql("SELECT review_id FROM reviews", ALLOWED)
    assert "LIMIT 1000" in out.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM reviews",
        "UPDATE reviews SET stage = 'x'",
        "SELECT * FROM users",
        "SELECT 1; DROP TABLE reviews",
        "SELECT pg_sleep(10)",
        "WITH x AS (DELETE FROM reviews RETURNING *) SELECT * FROM x",
        "not sql at all (((",
    ],
)
def test_unsafe_sql_is_rejected(sql):
    with pytest.raises(SQLViolation):
        validate_sql(sql, ALLOWED)


def test_oversized_limit_is_capped():
    out = validate_sql("SELECT review_id FROM reviews LIMIT 999999", ALLOWED, max_rows=100)
    assert "LIMIT 100" in out.upper()
