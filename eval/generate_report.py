#!/usr/bin/env python3
"""
Builds eval/REPORT.md from eval/reports/{before,after}_summary.json +
eval/reports/{before,after}_items.json -- the human-readable artifact meant
to back up any resume claim about this project's SQL-generation accuracy.

Run after both `python eval/run_eval.py --label before` and
`... --label after` have completed.
"""
import json
from pathlib import Path

REPORTS = Path(__file__).parent / "reports"
OUT = Path(__file__).parent / "REPORT.md"


def load(label):
    summary = json.loads((REPORTS / f"{label}_summary.json").read_text())
    items = json.loads((REPORTS / f"{label}_items.json").read_text())
    return summary, items


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def delta_pct(before, after):
    if before is None or after is None:
        return ""
    d = (after - before) * 100
    sign = "+" if d >= 0 else ""
    return f" ({sign}{d:.1f} pp)"


def main():
    before, before_items = load("before")
    after, after_items = load("after")

    lines = []
    lines.append("# QueryMind — Phase 4 Evaluation Report")
    lines.append("")
    lines.append(
        "**What this is:** results of running the real QueryMind agent graph "
        "(`backend/app/agent/graph.py` -- the exact graph `run_agent.py` and the "
        "FastAPI `/chat` route use) against the 40-item labeled benchmark in "
        "`eval/benchmark.json`, before and after one tuning pass. See "
        "**\"What this does and doesn't prove\"** at the end before quoting any "
        "number here on a resume."
    )
    lines.append("")

    lines.append("## Run configuration")
    lines.append("")
    lines.append("| | Before | After |")
    lines.append("|---|---|---|")
    lines.append(f"| LLM provider | `{before['provider']}` | `{after['provider']}` |")
    lines.append(f"| Retrieval TOP_K_CONTEXT | {before['top_k_context']} | {after['top_k_context']} |")
    lines.append(f"| Benchmark items | {before['n_items']} ({before['n_solvable']} solvable + {before['n_unsafe']} unsafe) | {after['n_items']} |")
    lines.append(f"| Infra errors (DB unreachable etc. -- excluded from scoring below) | {before['n_infra_errors']} | {after['n_infra_errors']} |")
    if before["n_infra_errors"] or after["n_infra_errors"]:
        lines.append("")
        lines.append(
            "**⚠️ At least one run above hit an infra error (see `infra_error_ids` in "
            "the raw summary JSON).** Every metric below excludes those items rather than "
            "scoring them as guardrail rejections, but a non-zero count here means the run "
            "wasn't fully clean -- check Postgres is running and `.env` is correct before "
            "trusting the numbers below at face value."
        )
    lines.append("")

    lines.append("## Headline metrics")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    lines.append(f"| SQL execution accuracy (produced & ran a query) | {pct(before['sql_execution_accuracy'])} | {pct(after['sql_execution_accuracy'])} |{delta_pct(before['sql_execution_accuracy'], after['sql_execution_accuracy'])} |")
    lines.append(f"| Result correctness (matches gold SQL's result) | {pct(before['result_correctness'])} | {pct(after['result_correctness'])} |{delta_pct(before['result_correctness'], after['result_correctness'])} |")
    lines.append(f"| Guardrail accuracy, overall (safe + unsafe items) | {pct(before['guardrail_accuracy_overall'])} | {pct(after['guardrail_accuracy_overall'])} |{delta_pct(before['guardrail_accuracy_overall'], after['guardrail_accuracy_overall'])} |")
    lines.append(f"| Guardrail accuracy, unsafe items only (correctly rejected) | {pct(before['guardrail_accuracy_unsafe_only'])} | {pct(after['guardrail_accuracy_unsafe_only'])} |{delta_pct(before['guardrail_accuracy_unsafe_only'], after['guardrail_accuracy_unsafe_only'])} |")
    lines.append(f"| False-positive rejection rate on safe items | {pct(before['false_positive_rejection_rate_on_safe'])} | {pct(after['false_positive_rejection_rate_on_safe'])} | |")
    lines.append(f"| Avg. retrieval recall@{before['top_k_context']}/{after['top_k_context']} vs. labeled-relevant docs | {pct(before['avg_retrieval_recall_at_k'])} | {pct(after['avg_retrieval_recall_at_k'])} |{delta_pct(before['avg_retrieval_recall_at_k'], after['avg_retrieval_recall_at_k'])} |")
    lines.append(f"| Avg. latency / turn | {before['avg_latency_ms']} ms | {after['avg_latency_ms']} ms | |")
    lines.append(f"| p95 latency / turn | {before['p95_latency_ms']} ms | {after['p95_latency_ms']} ms | |")
    lines.append(f"| Avg. cost / query (approx., see note) | ${before['avg_cost_per_query_usd']:.6f}{'*' if not before['cost_is_real'] else ''} | ${after['avg_cost_per_query_usd']:.6f}{'*' if not after['cost_is_real'] else ''} | |")
    if not before["cost_is_real"] or not after["cost_is_real"]:
        lines.append("")
        lines.append("*\\* $0.00 because `LLM_PROVIDER=mock`/`mock_tuned` make no API call -- see limitations below, not a real cost figure.*")
    lines.append("")

    lines.append("## By category")
    lines.append("")
    lines.append("| Category | n | Guardrail correct (before → after) | Result correct (before → after) |")
    lines.append("|---|---|---|---|")
    for cat in before["by_category"]:
        b = before["by_category"][cat]
        a = after["by_category"][cat]
        b_res = f"{b['result_correct']}/{b['result_scored']}" if b["result_scored"] else "n/a"
        a_res = f"{a['result_correct']}/{a['result_scored']}" if a["result_scored"] else "n/a"
        lines.append(f"| {cat} | {b['n']} | {b['guardrail_correct']}/{b['n']} → {a['guardrail_correct']}/{a['n']} | {b_res} → {a_res} |")
    lines.append("")

    lines.append("## What the tuning pass changed")
    lines.append("")
    lines.append(
        "1. **`SQL_SYSTEM_PROMPT` (`backend/app/agent/llm.py`)** gained three explicit "
        "rules, each traced to a specific failure category below: always add an "
        "explicit `ORDER BY`/`LIMIT` for \"top N\"/\"most\"/\"least\" questions; compute "
        "rates/percentages using the glossary's exact numerator/denominator rather than "
        "a raw `COUNT`/`SUM`; and, on a follow-up that narrows a previous result, add the "
        "narrowing condition as an additional predicate rather than dropping the prior "
        "aggregation. **These apply to `AnthropicLLM`/`OpenAILLM` but have not been "
        "verified against a live model in this sandbox** -- no API key is available here, "
        "the same gap documented in Phases 1-3. Re-run this eval with a real "
        "`LLM_PROVIDER` to confirm they actually help a real model."
    )
    lines.append(
        "2. **`TOP_K_CONTEXT` raised from 5 to 8** (`backend/app/agent/nodes.py`, now "
        "env-overridable). Retrieval recall@K is measurable independent of which LLM "
        "is active (it only depends on `retrieve_context`'s pgvector search), and this "
        "alone moved recall from {b} to {a} on this benchmark's labeled-relevant "
        "documents.".format(b=pct(before["avg_retrieval_recall_at_k"]), a=pct(after["avg_retrieval_recall_at_k"]))
    )
    lines.append(
        "3. **`MockTunedLLM` (`LLM_PROVIDER=mock_tuned`, `backend/app/agent/llm.py`)** "
        "-- an expanded version of the sandbox's deterministic MockLLM stand-in, with "
        "broader keyword coverage and a *generalized* follow-up-narrowing rule (any "
        "recognized entity -- a payment rail, a category group, a dispute status, a "
        "state -- rather than the original's single hardcoded `state_code = 'KA'` "
        "case). **This is the one change that does NOT generalize to a real LLM** -- "
        "see limitations below."
    )
    lines.append(
        "4. **A real eval-harness bug was also found and fixed during this pass**: the "
        "agent's `execute_sql` node truncates `state[\"rows\"]` to `MAX_DISPLAY_ROWS` "
        "(50) even when a query legitimately returns more, but the harness's result "
        "comparison was initially checking against the guardrail's SQL-level `LIMIT` "
        "(200) instead -- so every >50-row join query (Q09-Q11) scored as an incorrect "
        "result even though the SQL was exactly right. Fixed in `eval/run_eval.py` "
        "before either pass below was treated as final; flagged here rather than "
        "silently corrected, since it's exactly the kind of harness-level bug this "
        "phase's own \"what's NOT verified\" discipline is meant to catch."
    )
    lines.append("")

    lines.append("## Guardrail-rejection detail (the security-relevant metric)")
    lines.append("")
    lines.append(
        "The jump in unsafe-item guardrail accuracy (12.5% → 100%) is **not** a change "
        "to `backend/app/agent/guardrails.py` -- that module is unchanged since Phase 2 "
        "and was already unit-tested directly against these exact SQL strings there. "
        "It's because the *baseline* `MockLLM` only ever attempts one unsafe SQL "
        "statement (a `DELETE`, for its one demo scenario) and falls back to a benign "
        "query for every other attack phrasing in this benchmark (`DROP TABLE`, "
        "`UPDATE`, reading `schema_documents`, a stacked statement, `pg_sleep`, "
        "`GRANT`, `INSERT`) -- so the guardrail was never actually given anything "
        "unsafe to reject for those 7 items, and 'correctly' let a harmless fallback "
        "query through. `MockTunedLLM` was extended to literally attempt each of "
        "those, so the guardrail is now genuinely exercised end-to-end for all 8 "
        "unsafe items, not just 1. **This is an argument for testing with a real "
        "LLM eventually**, not evidence the guardrail itself improved -- a real model "
        "attempting each of these attack phrasings (which it likely would, at least "
        "occasionally) is the scenario this benchmark item category is actually meant "
        "to cover, and only a real-model run exercises that for real."
    )
    lines.append("")

    lines.append("## What this does and doesn't prove")
    lines.append("")
    lines.append(
        "**This sandbox has no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`** (same gap "
        "documented in every earlier phase's PROGRESS.md) and no Docker, so every "
        "number above was produced with `LLM_PROVIDER=mock` (before) / `mock_tuned` "
        "(after) against a real, locally-installed Postgres 16 + pgvector instance "
        "seeded with 500 users / 8,000 transactions -- the graph, guardrail, retrieval, "
        "multi-turn state, and DB execution are all real; only the SQL-*generation* "
        "step is a deterministic stand-in, not a model call."
    )
    lines.append("")
    lines.append(
        "Concretely, that means: the **harness, benchmark, and scoring methodology are "
        "real and reusable as-is**, and the **retrieval-recall and latency numbers "
        "are real** measurements of this actual system. The **SQL execution accuracy, "
        "result correctness, and unsafe-item guardrail numbers above are NOT evidence "
        "of real NL2SQL quality** -- they mostly measure how much of the benchmark's "
        "phrasing the mock's keyword-matcher was extended to cover, which is a "
        "different (much easier) task than a real LLM generalizing to novel phrasing "
        "it wasn't hand-tuned against. **Do not put the \"after\" percentages on a "
        "resume as-is.**"
    )
    lines.append("")
    lines.append(
        "**To get a real, resume-defensible number:** set `LLM_PROVIDER=anthropic` "
        "(or `openai`) with a real key in `.env`, then run:"
    )
    lines.append("```bash")
    lines.append("LLM_PROVIDER=anthropic python eval/run_eval.py --label real_claude")
    lines.append("python eval/generate_report.py   # regenerate this report with a 3rd column")
    lines.append("```")
    lines.append(
        "That run will also produce real token counts and a real cost-per-query "
        "figure (`backend/app/agent/llm.py`'s `TOKEN_LOG` already captures "
        "`response.usage` from both SDKs -- this was built and is ready, just "
        "unexercised here), and will be the number worth quoting."
    )
    lines.append("")

    lines.append("## Known failure mode: DB unreachable produces a misleading report if unguarded")
    lines.append("")
    lines.append(
        "This happened in practice once during development: this sandbox's background "
        "processes (Postgres included) don't survive between tool-use turns, so a "
        "`run_eval.py` invocation in a fresh turn hit `Connection refused` on every "
        "single item's `retrieve_context` node. The first version of this harness caught "
        "that as an unhandled exception and scored it the same way as `state[\"failed\"] "
        "= True` from a real guardrail rejection -- producing a report with 0% execution "
        "accuracy, 0% retrieval recall, and a nonsensical 100% *false-positive* rejection "
        "rate on safe items, that looked like a scoring result rather than an obvious "
        "infra error."
    )
    lines.append(
        "Fixed two ways: (1) `run_eval.py` now does a preflight `SELECT 1` against the "
        "DB before running anything, and exits immediately with a clear message if that "
        "fails, instead of running all 40 items into a wall of identical exceptions; "
        "(2) even if the DB dies mid-run, an unhandled exception is now flagged "
        "`infra_error: true` and excluded from every accuracy/guardrail metric rather "
        "than silently counted as a pass or fail either way (`n_infra_errors` above)."
    )
    lines.append("")

    lines.append("## Item-level detail")
    lines.append("")
    lines.append("Full per-item results (question, agent SQL, gold-comparison verdict, "
                  "retrieval recall, latency) are in `eval/reports/before_items.json` and "
                  "`eval/reports/after_items.json`. Full node-by-node execution traces "
                  "(every `retrieve_context`/`generate_sql`/`validate_sql`/`execute_sql`/"
                  "`summarize`/`handle_failure` call across the whole benchmark run) are "
                  "in `eval/logs/before_nodes.jsonl` and `eval/logs/after_nodes.jsonl`.")
    lines.append("")

    OUT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
