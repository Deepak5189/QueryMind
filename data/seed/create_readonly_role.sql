-- Phase 2: dedicated read-only role for the agent's SQL execution node.
--
-- This is the second, independent layer of defense behind the sqlglot
-- guardrail in backend/app/agent/guardrails.py: even if a validation bug
-- ever let a mutating statement slip through, this role has no INSERT/
-- UPDATE/DELETE/DDL privileges at the database level, so the statement
-- would fail regardless. It also has no grants at all on schema_documents,
-- so the agent's execution connection cannot read the RAG/embedding table
-- (that table is only for the retrieval node, via the normal DATABASE_URL
-- connection).
--
-- Run once against the seeded database:
--   psql "$DATABASE_URL" -f data/seed/create_readonly_role.sql
-- (idempotent: safe to re-run)

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'querymind_readonly') THEN
        CREATE ROLE querymind_readonly WITH LOGIN PASSWORD 'querymind_readonly';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE querymind TO querymind_readonly;
GRANT USAGE ON SCHEMA public TO querymind_readonly;

-- Only the 8 business tables the agent is allowed to query -- explicitly
-- NOT schema_documents (RAG/embedding storage, not analytics data).
GRANT SELECT ON
    states, banks, merchant_categories, users, merchants, cards,
    transactions, disputes
TO querymind_readonly;

-- No sequence grants, no DML/DDL grants of any kind (default is already
-- "none" for a fresh role, this is just explicit documentation of intent).
