"""
SQL safety guardrail for the QueryMind agent.

This is the primary defense layer (checked BEFORE anything touches the
database): it parses the LLM's candidate SQL with sqlglot and rejects
anything that isn't a single, scoped, read-only SELECT. A second,
independent layer -- a Postgres role with SELECT-only grants
(backend/app/db/connection.py:get_readonly_connection, see
data/seed/create_readonly_role.sql) -- backs this up at execution time,
so a bug here isn't the only thing standing between a bad query and the
database.

validate_sql() never raises for "the SQL is unsafe" -- it returns a
ValidationResult with is_valid=False and a human-readable error message
that gets fed straight back to the LLM as regeneration feedback. It only
raises for genuinely unexpected internal errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp

DIALECT = "postgres"

# The only tables the agent is allowed to read. Deliberately excludes
# schema_documents (the RAG/embedding storage table, Phase 1) -- that's
# infrastructure, not analytics data, and should never appear in a
# user-facing query result.
ALLOWED_TABLES = {
    "states",
    "banks",
    "merchant_categories",
    "users",
    "merchants",
    "cards",
    "transactions",
    "disputes",
}

# Functions with no legitimate place in a read-only analytics query --
# timing/DoS vectors, filesystem/network access, or session tampering.
# Not an exhaustive security boundary on its own (that's what the
# read-only DB role is for) but catches obviously hostile queries before
# they're even attempted.
BLOCKED_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "dblink",
    "dblink_connect",
    "lo_import",
    "lo_export",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "set_config",
    "current_setting",
}

DEFAULT_ROW_LIMIT = 200
MAX_ROW_LIMIT = 1000


@dataclass
class ValidationResult:
    is_valid: bool
    cleaned_sql: Optional[str] = None
    error: Optional[str] = None


def _cte_names(statement: exp.Expression) -> set[str]:
    """Names introduced by WITH ... AS (...) -- not real tables, so they're
    exempt from the ALLOWED_TABLES check (the CTE's own body is still
    checked, since it's walked separately by find_all(exp.Table))."""
    with_clause = statement.args.get("with")
    if not with_clause:
        return set()
    return {cte.alias.lower() for cte in with_clause.expressions if cte.alias}


def validate_sql(sql: str) -> ValidationResult:
    sql = sql.strip().rstrip(";")
    if not sql:
        return ValidationResult(is_valid=False, error="Generated SQL was empty.")

    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except Exception as e:  # sqlglot.errors.ParseError, among others
        return ValidationResult(is_valid=False, error=f"SQL failed to parse: {e}")

    statements = [s for s in statements if s is not None]
    if len(statements) == 0:
        return ValidationResult(is_valid=False, error="Generated SQL was empty.")
    if len(statements) > 1:
        return ValidationResult(
            is_valid=False,
            error=(
                f"Only a single SQL statement is allowed, but {len(statements)} "
                "statements were found (check for a stray semicolon). Return "
                "exactly one SELECT statement."
            ),
        )

    statement = statements[0]

    # Reject anything that isn't a SELECT or a UNION/INTERSECT/EXCEPT of
    # SELECTs. Every mutating/DDL statement type (Insert, Update, Delete,
    # Drop, Create, Alter, TruncateTable, Grant, ...) parses to its own
    # sqlglot expression class, never exp.Select/exp.Union, so this single
    # isinstance check is what actually enforces "read-only."
    if not isinstance(statement, (exp.Select, exp.Union)):
        return ValidationResult(
            is_valid=False,
            error=(
                f"Only SELECT statements are allowed. This query was parsed as "
                f"a {type(statement).__name__} statement, which is not permitted. "
                "Rewrite it as a single read-only SELECT."
            ),
        )

    # SELECT ... INTO new_table would create a table -- reject even though
    # it's nominally a "Select" node.
    if statement.args.get("into"):
        return ValidationResult(
            is_valid=False,
            error="SELECT ... INTO is not allowed (it creates a table). Remove the INTO clause.",
        )

    # Scoped-table check. Exempt CTE aliases (they're not real tables).
    exempt = _cte_names(statement)
    referenced_tables = {t.name.lower() for t in statement.find_all(exp.Table)}
    disallowed = referenced_tables - ALLOWED_TABLES - exempt
    if disallowed:
        return ValidationResult(
            is_valid=False,
            error=(
                f"Query references table(s) not in the allowed schema: "
                f"{', '.join(sorted(disallowed))}. Allowed tables are: "
                f"{', '.join(sorted(ALLOWED_TABLES))}."
            ),
        )

    # Blocked-function check (covers both known builtins that sqlglot
    # recognizes as exp.Func subclasses, and functions it doesn't
    # recognize, which parse as exp.Anonymous).
    called_functions = set()
    for node in statement.find_all((exp.Func, exp.Anonymous)):
        name = getattr(node, "name", None) or getattr(node, "this", None)
        if isinstance(name, str):
            called_functions.add(name.lower())
    blocked = called_functions & BLOCKED_FUNCTIONS
    if blocked:
        return ValidationResult(
            is_valid=False,
            error=f"Query calls disallowed function(s): {', '.join(sorted(blocked))}.",
        )

    # Enforce a row LIMIT: inject the default if absent, cap it if the
    # LLM specified something excessive. Only meaningful on a top-level
    # Select; a Union's outer LIMIT is set on the Union node itself in
    # sqlglot, which .args.get("limit") also reaches correctly.
    existing_limit = statement.args.get("limit")
    if existing_limit is None:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_ROW_LIMIT)))
    else:
        try:
            n = int(existing_limit.expression.this)
            if n > MAX_ROW_LIMIT:
                statement.set(
                    "limit", exp.Limit(expression=exp.Literal.number(MAX_ROW_LIMIT))
                )
        except (AttributeError, ValueError, TypeError):
            # Non-literal LIMIT expression (unusual) -- overwrite with the
            # safe default rather than risk an unbounded query.
            statement.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_ROW_LIMIT)))

    cleaned_sql = statement.sql(dialect=DIALECT)
    return ValidationResult(is_valid=True, cleaned_sql=cleaned_sql)
