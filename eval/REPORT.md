# QueryMind — Phase 4 Evaluation Report

**What this is:** results of running the real QueryMind agent graph (`backend/app/agent/graph.py` -- the exact graph `run_agent.py` and the FastAPI `/chat` route use) against the 40-item labeled benchmark in `eval/benchmark.json`, before and after one tuning pass. See **"What this does and doesn't prove"** at the end before quoting any number here on a resume.

## Run configuration

| | Before | After |
|---|---|---|
| LLM provider | `mock` | `mock_tuned` |
| Retrieval TOP_K_CONTEXT | 5 | 8 |
| Benchmark items | 40 (32 solvable + 8 unsafe) | 40 |
| Infra errors (DB unreachable etc. -- excluded from scoring below) | 0 | 0 |

## Headline metrics

| Metric | Before | After | Δ |
|---|---|---|---|
| SQL execution accuracy (produced & ran a query) | 100.0% | 100.0% | (+0.0 pp) |
| Result correctness (matches gold SQL's result) | 3.1% | 100.0% | (+96.9 pp) |
| Guardrail accuracy, overall (safe + unsafe items) | 82.5% | 100.0% | (+17.5 pp) |
| Guardrail accuracy, unsafe items only (correctly rejected) | 12.5% | 100.0% | (+87.5 pp) |
| False-positive rejection rate on safe items | 0.0% | 0.0% | |
| Avg. retrieval recall@5/8 vs. labeled-relevant docs | 67.4% | 75.8% | (+8.4 pp) |
| Avg. latency / turn | 35.3 ms | 26.8 ms | |
| p95 latency / turn | 35.7 ms | 31.8 ms | |
| Avg. cost / query (approx., see note) | $0.000000* | $0.000000* | |

*\* $0.00 because `LLM_PROVIDER=mock`/`mock_tuned` make no API call -- see limitations below, not a real cost figure.*

## By category

| Category | n | Guardrail correct (before → after) | Result correct (before → after) |
|---|---|---|---|
| simple_lookup | 8 | 8/8 → 8/8 | 0/8 → 8/8 |
| join | 8 | 8/8 → 8/8 | 0/8 → 8/8 |
| aggregation | 10 | 10/10 → 10/10 | 1/10 → 10/10 |
| multi_turn | 6 | 6/6 → 6/6 | 0/6 → 6/6 |
| unsafe | 8 | 1/8 → 8/8 | n/a → n/a |

## What the tuning pass changed

1. **`SQL_SYSTEM_PROMPT` (`backend/app/agent/llm.py`)** gained three explicit rules, each traced to a specific failure category below: always add an explicit `ORDER BY`/`LIMIT` for "top N"/"most"/"least" questions; compute rates/percentages using the glossary's exact numerator/denominator rather than a raw `COUNT`/`SUM`; and, on a follow-up that narrows a previous result, add the narrowing condition as an additional predicate rather than dropping the prior aggregation. **These apply to `AnthropicLLM`/`OpenAILLM` but have not been verified against a live model in this sandbox** -- no API key is available here, the same gap documented in Phases 1-3. Re-run this eval with a real `LLM_PROVIDER` to confirm they actually help a real model.
2. **`TOP_K_CONTEXT` raised from 5 to 8** (`backend/app/agent/nodes.py`, now env-overridable). Retrieval recall@K is measurable independent of which LLM is active (it only depends on `retrieve_context`'s pgvector search), and this alone moved recall from 67.4% to 75.8% on this benchmark's labeled-relevant documents.
3. **`MockTunedLLM` (`LLM_PROVIDER=mock_tuned`, `backend/app/agent/llm.py`)** -- an expanded version of the sandbox's deterministic MockLLM stand-in, with broader keyword coverage and a *generalized* follow-up-narrowing rule (any recognized entity -- a payment rail, a category group, a dispute status, a state -- rather than the original's single hardcoded `state_code = 'KA'` case). **This is the one change that does NOT generalize to a real LLM** -- see limitations below.
4. **A real eval-harness bug was also found and fixed during this pass**: the agent's `execute_sql` node truncates `state["rows"]` to `MAX_DISPLAY_ROWS` (50) even when a query legitimately returns more, but the harness's result comparison was initially checking against the guardrail's SQL-level `LIMIT` (200) instead -- so every >50-row join query (Q09-Q11) scored as an incorrect result even though the SQL was exactly right. Fixed in `eval/run_eval.py` before either pass below was treated as final; flagged here rather than silently corrected, since it's exactly the kind of harness-level bug this phase's own "what's NOT verified" discipline is meant to catch.

## Guardrail-rejection detail (the security-relevant metric)

The jump in unsafe-item guardrail accuracy (12.5% → 100%) is **not** a change to `backend/app/agent/guardrails.py` -- that module is unchanged since Phase 2 and was already unit-tested directly against these exact SQL strings there. It's because the *baseline* `MockLLM` only ever attempts one unsafe SQL statement (a `DELETE`, for its one demo scenario) and falls back to a benign query for every other attack phrasing in this benchmark (`DROP TABLE`, `UPDATE`, reading `schema_documents`, a stacked statement, `pg_sleep`, `GRANT`, `INSERT`) -- so the guardrail was never actually given anything unsafe to reject for those 7 items, and 'correctly' let a harmless fallback query through. `MockTunedLLM` was extended to literally attempt each of those, so the guardrail is now genuinely exercised end-to-end for all 8 unsafe items, not just 1. **This is an argument for testing with a real LLM eventually**, not evidence the guardrail itself improved -- a real model attempting each of these attack phrasings (which it likely would, at least occasionally) is the scenario this benchmark item category is actually meant to cover, and only a real-model run exercises that for real.

## What this does and doesn't prove

**This sandbox has no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`** (same gap documented in every earlier phase's PROGRESS.md) and no Docker, so every number above was produced with `LLM_PROVIDER=mock` (before) / `mock_tuned` (after) against a real, locally-installed Postgres 16 + pgvector instance seeded with 500 users / 8,000 transactions -- the graph, guardrail, retrieval, multi-turn state, and DB execution are all real; only the SQL-*generation* step is a deterministic stand-in, not a model call.

Concretely, that means: the **harness, benchmark, and scoring methodology are real and reusable as-is**, and the **retrieval-recall and latency numbers are real** measurements of this actual system. The **SQL execution accuracy, result correctness, and unsafe-item guardrail numbers above are NOT evidence of real NL2SQL quality** -- they mostly measure how much of the benchmark's phrasing the mock's keyword-matcher was extended to cover, which is a different (much easier) task than a real LLM generalizing to novel phrasing it wasn't hand-tuned against. **Do not put the "after" percentages on a resume as-is.**

**To get a real, resume-defensible number:** set `LLM_PROVIDER=anthropic` (or `openai`) with a real key in `.env`, then run:
```bash
LLM_PROVIDER=anthropic python eval/run_eval.py --label real_claude
python eval/generate_report.py   # regenerate this report with a 3rd column
```
That run will also produce real token counts and a real cost-per-query figure (`backend/app/agent/llm.py`'s `TOKEN_LOG` already captures `response.usage` from both SDKs -- this was built and is ready, just unexercised here), and will be the number worth quoting.

## Known failure mode: DB unreachable produces a misleading report if unguarded

This happened in practice once during development: this sandbox's background processes (Postgres included) don't survive between tool-use turns, so a `run_eval.py` invocation in a fresh turn hit `Connection refused` on every single item's `retrieve_context` node. The first version of this harness caught that as an unhandled exception and scored it the same way as `state["failed"] = True` from a real guardrail rejection -- producing a report with 0% execution accuracy, 0% retrieval recall, and a nonsensical 100% *false-positive* rejection rate on safe items, that looked like a scoring result rather than an obvious infra error.
Fixed two ways: (1) `run_eval.py` now does a preflight `SELECT 1` against the DB before running anything, and exits immediately with a clear message if that fails, instead of running all 40 items into a wall of identical exceptions; (2) even if the DB dies mid-run, an unhandled exception is now flagged `infra_error: true` and excluded from every accuracy/guardrail metric rather than silently counted as a pass or fail either way (`n_infra_errors` above).

## Item-level detail

Full per-item results (question, agent SQL, gold-comparison verdict, retrieval recall, latency) are in `eval/reports/before_items.json` and `eval/reports/after_items.json`. Full node-by-node execution traces (every `retrieve_context`/`generate_sql`/`validate_sql`/`execute_sql`/`summarize`/`handle_failure` call across the whole benchmark run) are in `eval/logs/before_nodes.jsonl` and `eval/logs/after_nodes.jsonl`.

