"""
Unit tests for backend/app/agent/guardrails.py.

These are the same cases documented (as manual `python -c "..."` output)
in PROGRESS.md's Phase 2 section, turned into a real pytest suite so CI
(.github/workflows/ci.yml) has something concrete and fast to run on every
push -- no Postgres, no API key, no Docker required. This is deliberately
the guardrail specifically: it's the one module in the whole project
that's pure logic with zero external dependencies, which makes it the
right thing to gate merges on. The eval harness (eval/run_eval.py) is a
separate, heavier CI job that needs a live Postgres service container --
see the "eval-smoke" job in the workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow `pytest` to be run from the repo root without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agent.guardrails import validate_sql  # noqa: E402


class TestSafeQueriesPass:
    def test_simple_select(self):
        result = validate_sql("SELECT * FROM transactions LIMIT 10")
        assert result.is_valid
        assert result.cleaned_sql is not None

    def test_cte_over_allowed_table(self):
        result = validate_sql(
            "WITH t AS (SELECT * FROM transactions) SELECT * FROM t"
        )
        assert result.is_valid
        # No explicit LIMIT was given, so the guardrail should inject its
        # default cap rather than let an unbounded query through.
        assert "LIMIT" in result.cleaned_sql.upper()

    def test_join_across_allowed_tables(self):
        result = validate_sql(
            "SELECT m.name, COUNT(*) FROM transactions t "
            "JOIN merchants m ON m.merchant_id = t.merchant_id "
            "GROUP BY m.name LIMIT 50"
        )
        assert result.is_valid

    def test_missing_limit_gets_injected(self):
        result = validate_sql("SELECT state_code FROM users")
        assert result.is_valid
        assert "LIMIT" in result.cleaned_sql.upper()

    def test_excessive_limit_gets_capped(self):
        result = validate_sql("SELECT * FROM transactions LIMIT 999999")
        assert result.is_valid
        # Cap is documented as 1000 in PROGRESS.md's Phase 2 section.
        assert "999999" not in result.cleaned_sql
        assert "1000" in result.cleaned_sql


class TestUnsafeQueriesAreRejected:
    def test_delete_is_rejected(self):
        result = validate_sql("DELETE FROM disputes WHERE status = 'OPEN'")
        assert not result.is_valid
        assert "delete" in result.error.lower()

    def test_drop_table_is_rejected(self):
        result = validate_sql("DROP TABLE users")
        assert not result.is_valid

    def test_update_is_rejected(self):
        result = validate_sql("UPDATE users SET segment = 'Premium'")
        assert not result.is_valid

    def test_insert_is_rejected(self):
        result = validate_sql("INSERT INTO users (name) VALUES ('x')")
        assert not result.is_valid

    def test_stacked_statement_injection_is_rejected(self):
        result = validate_sql("SELECT * FROM transactions; DROP TABLE users;")
        assert not result.is_valid
        assert "single" in result.error.lower() or "statement" in result.error.lower()

    def test_select_into_new_table_is_rejected(self):
        result = validate_sql("SELECT * INTO new_table FROM transactions")
        assert not result.is_valid

    def test_out_of_scope_table_is_rejected(self):
        result = validate_sql("SELECT * FROM pg_catalog.pg_tables")
        assert not result.is_valid

    def test_rag_infrastructure_table_is_rejected(self):
        """schema_documents (the pgvector RAG store) must never be
        queryable by the agent, even though it lives in the same
        database as the 8 business tables -- it's infrastructure, not
        analytics data."""
        result = validate_sql("SELECT * FROM schema_documents")
        assert not result.is_valid
        assert "schema_documents" in result.error

    def test_rag_infrastructure_table_is_rejected_inside_a_cte(self):
        """A CTE alias shouldn't launder access to a disallowed table --
        the CTE body itself is still checked."""
        result = validate_sql(
            "WITH t AS (SELECT * FROM schema_documents) SELECT * FROM t"
        )
        assert not result.is_valid

    @pytest.mark.parametrize(
        "fn",
        ["pg_sleep(5)", "pg_read_file('/etc/passwd')", "pg_terminate_backend(1)"],
    )
    def test_blocked_functions_are_rejected(self, fn):
        result = validate_sql(f"SELECT {fn}")
        assert not result.is_valid
        assert "function" in result.error.lower()

    def test_empty_sql_is_rejected(self):
        result = validate_sql("")
        assert not result.is_valid


class TestErrorMessagesAreActionable:
    """validate_sql()'s error text is fed straight back into the LLM as
    regeneration feedback (see generate_sql in nodes.py) -- these tests
    exist to guard against that text becoming vague or empty, which
    would silently degrade the retry loop's usefulness."""

    def test_rejection_error_is_nonempty_string(self):
        result = validate_sql("DELETE FROM disputes")
        assert isinstance(result.error, str)
        assert len(result.error) > 10

    def test_valid_result_has_no_error(self):
        result = validate_sql("SELECT * FROM transactions LIMIT 10")
        assert result.error is None
