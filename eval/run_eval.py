#!/usr/bin/env python3
"""
Phase 4 evaluation harness.

Runs every item in eval/benchmark.json through the real QueryMind agent
graph (backend/app/agent/graph.py -- the exact same graph run_agent.py and
the FastAPI /chat route use, not a separate eval-only code path), and scores:

  1. SQL execution accuracy   -- for solvable items, did the agent produce
                                  and successfully execute a query at all
                                  (failed=False)?
  2. Result correctness       -- for solvable items, does the agent's actual
                                  query result match the hand-written gold
                                  SQL's result? (execution-accuracy style
                                  comparison -- see build_benchmark.py's
                                  docstring for why text-match isn't used.)
  3. Guardrail accuracy       -- for BOTH unsafe items (must be rejected)
                                  and solvable items (must NOT be rejected),
                                  did the guardrail make the correct call?
  4. Retrieval recall@K       -- did retrieve_context's top-K actually
                                  include the human-labeled relevant
                                  schema/glossary docs for this question?
  5. Latency                  -- wall-clock ms per graph.invoke() call.
  6. Token usage / approx cost -- read from backend.app.agent.llm.TOKEN_LOG
                                  (populated by AnthropicLLM/OpenAILLM; zero
                                  for mock/mock_tuned, which make no API call).

Multi-turn items (depends_on set) are run in the same order they appear in
the benchmark, threading the REAL conversation_history returned by the
previous turn's graph.invoke() call into the next -- exactly how a live
multi-turn conversation actually behaves, not a scripted shortcut.

Usage:
    python eval/run_eval.py --label before                # LLM_PROVIDER from .env / env
    LLM_PROVIDER=mock_tuned TOP_K_CONTEXT=8 python eval/run_eval.py --label after
    python eval/run_eval.py --label before --verbose       # + per-item console detail
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))  # noqa: E402

# Approximate published list prices, USD per 1M tokens, as of this project's
# development (Jan 2026 era). NOT pulled live, NOT exact billing -- for a
# rough "cost per query" order-of-magnitude figure only. Update if pricing
# has changed since; the eval report labels this explicitly as an estimate.
APPROX_PRICING_PER_MTOK = {
    ("anthropic", "claude-sonnet-4-6"): {"input": 3.00, "output": 15.00},
    ("openai", "gpt-4o"): {"input": 2.50, "output": 10.00},
}
DEFAULT_PRICING = {"input": 3.00, "output": 15.00}  # fallback if model unrecognized

BENCHMARK_PATH = Path(__file__).parent / "benchmark.json"
REPORTS_DIR = Path(__file__).parent / "reports"
LOGS_DIR = Path(__file__).parent / "logs"


# ------------------------------------------------------------------ result comparison

def _normalize_value(v):
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 2)
    if v is None:
        return None
    return str(v)


def _normalize_row(row: dict) -> tuple:
    """Order-and-column-name-agnostic row signature: a sorted tuple of
    normalized values. This means an agent query that returns the same
    values in a different column order, or with different column aliases
    than gold_sql, still scores as matching -- only the VALUES matter,
    which is what a user actually cares about."""
    return tuple(sorted((_normalize_value(v) for v in row.values()), key=lambda x: (x is None, str(x))))


def results_match(gold_rows: list[dict], agent_rows: list[dict], guardrail_cap: int) -> tuple[bool, str]:
    """Compares gold_sql's result to the agent's actual result.

    If gold has more rows than the guardrail's row cap (see
    backend/app/agent/guardrails.py DEFAULT_ROW_LIMIT), the agent's result
    is legitimately truncated -- so we only require the agent's rows to be
    a subset of gold's (multiset-wise) in that case. Otherwise we require
    an exact multiset match.
    """
    from collections import Counter

    gold_sig = Counter(_normalize_row(r) for r in gold_rows)
    agent_sig = Counter(_normalize_row(r) for r in agent_rows)

    if len(gold_rows) > guardrail_cap:
        # Agent should be capped; every agent row must appear in gold.
        if not agent_sig - gold_sig == Counter():
            return False, f"agent returned row(s) not present in gold result (expected subset, gold has {len(gold_rows)} > cap {guardrail_cap})"
        return True, "subset match (gold exceeds row cap)"

    if gold_sig == agent_sig:
        return True, "exact match"
    return False, f"row mismatch: gold={dict(gold_sig)!r:.200s} agent={dict(agent_sig)!r:.200s}"


# ------------------------------------------------------------------ eval run

def run_eval(label: str, verbose: bool = False) -> dict:
    # Import AFTER env vars (LLM_PROVIDER, TOP_K_CONTEXT) are set by the
    # caller's shell environment -- these modules read os.environ at import
    # time (module-level constants), so a subprocess-per-run is what makes
    # "before" vs "after" configuration actually take effect.
    from backend.app.agent.graph import get_graph
    from backend.app.agent import llm as llm_module
    from backend.app.agent import nodes as nodes_module
    from backend.app.agent.guardrails import DEFAULT_ROW_LIMIT
    from backend.app.db.connection import get_readonly_connection

    # Preflight: fail loudly and immediately if Postgres isn't reachable,
    # instead of letting all 40 items die inside graph.invoke() and produce
    # a report that LOOKS like a guardrail/scoring result (0% execution,
    # 100% "false-positive rejections") but is actually just "the DB was
    # down." This exact failure mode happened in practice -- see
    # eval/REPORT.md's "A preflight check was added after a real incident"
    # note -- and is worth guarding against explicitly rather than trusting
    # every future run to notice a wall of identical exceptions.
    try:
        _conn = get_readonly_connection()
        with _conn.cursor() as _cur:
            _cur.execute("SELECT 1")
        _conn.close()
    except Exception as e:
        print(f"\n[FATAL] Cannot reach Postgres via READONLY_DATABASE_URL: {e}\n"
              f"        Is Postgres running? (service postgresql start / docker compose up -d)\n"
              f"        Is .env present with the right DATABASE_URL / READONLY_DATABASE_URL?\n"
              f"        Refusing to run the benchmark against an unreachable DB -- every item "
              f"would fail on retrieve_context and produce a misleading all-zero report rather "
              f"than a clear error.", file=sys.stderr)
        sys.exit(1)

    # execute_sql (nodes.py) truncates what it puts in state["rows"] to
    # MAX_DISPLAY_ROWS even when the SQL itself returned more (row_count
    # still reflects the true count) -- so THAT'S the effective cap for
    # comparing state["rows"] against gold, not the guardrail's SQL-level
    # LIMIT, which is usually larger. Missing this the first time through
    # produced false "result mismatch" verdicts on every >50-row join
    # query -- exactly the kind of bug an eval harness needs to catch in
    # itself, not just in the agent; fixed here before either eval pass
    # was taken as final.
    effective_row_cap = min(DEFAULT_ROW_LIMIT, nodes_module.MAX_DISPLAY_ROWS)

    llm_module.reset_token_log()
    graph = get_graph()

    # Node-level observability: attach a dedicated file handler to the
    # agent's logger (backend/app/agent/tracing.py) at DEBUG level, so
    # EVERY node call (retrieve_context, generate_sql, validate_sql,
    # execute_sql, summarize, handle_failure) across the whole benchmark
    # run is captured as a structured JSON line -- not just the per-item
    # summary this script writes itself. This is what "every run in the
    # benchmark is traceable end-to-end" means concretely in a sandbox
    # with no LangSmith key: a full node-level trace file per eval run,
    # the same shape `python run_agent.py --verbose` produces for a single
    # question, just accumulated across all 40.
    import logging as _logging
    agent_logger = _logging.getLogger("querymind.agent")
    agent_logger.setLevel(_logging.DEBUG)
    node_trace_path = LOGS_DIR / f"{label}_nodes.jsonl"
    LOGS_DIR.mkdir(exist_ok=True, parents=True)
    file_handler = _logging.FileHandler(node_trace_path, mode="w")
    file_handler.setLevel(_logging.DEBUG)
    file_handler.setFormatter(_logging.Formatter("%(message)s"))
    agent_logger.addHandler(file_handler)

    benchmark = json.loads(BENCHMARK_PATH.read_text())

    provider = os.environ.get("LLM_PROVIDER", "mock")
    top_k = nodes_module.TOP_K_CONTEXT

    LOGS_DIR.mkdir(exist_ok=True, parents=True)
    log_path = LOGS_DIR / f"{label}.jsonl"
    log_f = log_path.open("w")

    def log_event(event: dict):
        log_f.write(json.dumps(event, default=str) + "\n")

    log_event({"event": "eval_run_start", "label": label, "provider": provider,
               "top_k_context": top_k, "n_items": len(benchmark), "ts": time.time()})

    results = []
    # thread real conversation_history across depends_on chains
    history_by_id: dict[str, list] = {}

    gold_conn_cache: dict[str, list] = {}

    for item in benchmark:
        question = item["question"]
        prior_history = history_by_id.get(item["depends_on"], []) if item.get("depends_on") else []

        t0 = time.perf_counter()
        state_in = {"question": question, "conversation_history": prior_history}
        infra_error = False
        try:
            state_out = graph.invoke(state_in)
            error = None
        except Exception as e:  # an unhandled agent crash -- a real failure, not a graceful reject
            state_out = {"failed": True, "failure_reason": f"UNHANDLED EXCEPTION: {e}",
                         "conversation_history": prior_history}
            error = str(e)
            infra_error = True  # NOT a guardrail decision -- see run_eval()'s preflight-check
            # comment above. An unhandled exception means some node crashed (DB connection lost
            # mid-run, a bug, etc.), not that validate_sql looked at SQL and rejected it. Scoring
            # this as a guardrail outcome either way is exactly the bug that produced a
            # nonsensical all-zero report the first time this harness hit a dead DB -- excluded
            # from guardrail/execution scoring below instead.
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        history_by_id[item["id"]] = state_out.get("conversation_history", prior_history)

        # ---- guardrail accuracy ----
        agent_rejected = bool(state_out.get("failed"))
        expected_reject = item["expected_reject"]
        # An infra error (DB down, unhandled exception) is not a guardrail
        # decision either way -- it's scored as neither correct nor
        # incorrect, and excluded from the guardrail/execution denominators
        # below, rather than silently counted as "the guardrail rejected
        # this" just because state["failed"] happens to be True in both
        # cases.
        guardrail_correct = (agent_rejected == expected_reject) if not infra_error else None

        # ---- retrieval recall@K ----
        retrieved_titles = [d["title"] for d in state_out.get("retrieved_context", [])]
        expected_titles = item.get("expected_context_titles", [])
        if expected_titles:
            hit = sum(1 for t in expected_titles if t in retrieved_titles)
            retrieval_recall = round(hit / len(expected_titles), 3)
        else:
            retrieval_recall = None

        # ---- execution / correctness (only meaningful for non-unsafe items) ----
        executed_ok = None
        result_correct = None
        correctness_note = ""
        if not expected_reject:
            executed_ok = False if infra_error else (not agent_rejected)
            if executed_ok and item.get("gold_sql"):
                cache_key = item["gold_sql"]
                if cache_key not in gold_conn_cache:
                    conn = get_readonly_connection()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(item["gold_sql"])
                            cols = [d[0] for d in cur.description]
                            gold_rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                        gold_conn_cache[cache_key] = gold_rows
                    finally:
                        conn.close()
                gold_rows = gold_conn_cache[cache_key]
                agent_rows = state_out.get("rows", [])
                result_correct, correctness_note = results_match(gold_rows, agent_rows, effective_row_cap)
            elif not executed_ok:
                correctness_note = state_out.get("failure_reason", "execution failed")

        row = {
            "id": item["id"],
            "category": item["category"],
            "question": question,
            "expected_reject": expected_reject,
            "agent_rejected": agent_rejected,
            "infra_error": infra_error,
            "guardrail_correct": guardrail_correct,
            "executed_ok": executed_ok,
            "result_correct": result_correct,
            "correctness_note": correctness_note,
            "retrieval_recall": retrieval_recall,
            "latency_ms": elapsed_ms,
            "agent_sql": state_out.get("executed_sql") or state_out.get("candidate_sql"),
            "retry_count": state_out.get("retry_count", 0),
            "error": error,
        }
        results.append(row)
        log_event({"event": "item_result", **row})
        if verbose:
            status = "OK" if (guardrail_correct and (result_correct in (True, None))) else "FAIL"
            print(f"[{status}] {item['id']:>5} ({item['category']:<13}) "
                  f"guardrail={'ok' if guardrail_correct else 'WRONG'} "
                  f"correct={result_correct} recall={retrieval_recall} {elapsed_ms}ms")

    # ---- aggregate metrics ----
    n = len(results)
    n_infra_errors = sum(1 for r in results if r["infra_error"])
    non_infra = [r for r in results if not r["infra_error"]]
    solvable = [r for r in non_infra if not r["expected_reject"]]
    unsafe = [r for r in non_infra if r["expected_reject"]]

    exec_acc = sum(1 for r in solvable if r["executed_ok"]) / len(solvable) if solvable else None
    correctness_scored = [r for r in solvable if r["result_correct"] is not None]
    result_acc = (sum(1 for r in correctness_scored if r["result_correct"]) / len(correctness_scored)
                  if correctness_scored else None)
    guardrail_correct_items = [r for r in non_infra]
    guardrail_acc_all = (sum(1 for r in guardrail_correct_items if r["guardrail_correct"]) / len(guardrail_correct_items)
                         if guardrail_correct_items else None)
    guardrail_acc_unsafe = (sum(1 for r in unsafe if r["guardrail_correct"]) / len(unsafe)) if unsafe else None
    false_positive_rate = (sum(1 for r in solvable if r["agent_rejected"]) / len(solvable)) if solvable else None

    recall_scored = [r["retrieval_recall"] for r in results if r["retrieval_recall"] is not None]
    avg_recall = round(sum(recall_scored) / len(recall_scored), 3) if recall_scored else None

    avg_latency = round(sum(r["latency_ms"] for r in results) / n, 1)
    p95_latency = round(sorted(r["latency_ms"] for r in results)[int(0.95 * (n - 1))], 1)

    token_log = llm_module.TOKEN_LOG
    total_input_tok = sum(e["input_tokens"] for e in token_log)
    total_output_tok = sum(e["output_tokens"] for e in token_log)
    model_used = token_log[0]["model"] if token_log else provider
    provider_used = token_log[0]["provider"] if token_log else provider
    pricing = APPROX_PRICING_PER_MTOK.get((provider_used, model_used), DEFAULT_PRICING)
    total_cost_usd = (total_input_tok / 1_000_000) * pricing["input"] + \
                      (total_output_tok / 1_000_000) * pricing["output"]
    avg_cost_per_query = round(total_cost_usd / n, 6) if n else 0.0
    is_zero_cost_provider = provider_used in ("mock", "mock_tuned")

    summary = {
        "label": label,
        "provider": provider,
        "top_k_context": top_k,
        "n_items": n,
        "n_solvable": len(solvable),
        "n_unsafe": len(unsafe),
        "n_infra_errors": n_infra_errors,
        "infra_error_ids": [r["id"] for r in results if r["infra_error"]],
        "sql_execution_accuracy": exec_acc,
        "result_correctness": result_acc,
        "guardrail_accuracy_overall": guardrail_acc_all,
        "guardrail_accuracy_unsafe_only": guardrail_acc_unsafe,
        "false_positive_rejection_rate_on_safe": false_positive_rate,
        "avg_retrieval_recall_at_k": avg_recall,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "total_input_tokens": total_input_tok,
        "total_output_tokens": total_output_tok,
        "avg_cost_per_query_usd": avg_cost_per_query,
        "cost_is_real": not is_zero_cost_provider,
        "by_category": _by_category(results),
    }

    log_event({"event": "eval_run_summary", **summary})
    log_f.close()
    agent_logger.removeHandler(file_handler)
    file_handler.close()

    REPORTS_DIR.mkdir(exist_ok=True, parents=True)
    (REPORTS_DIR / f"{label}_summary.json").write_text(json.dumps(summary, indent=2))
    (REPORTS_DIR / f"{label}_items.json").write_text(json.dumps(results, indent=2))

    return {"summary": summary, "results": results}


def _by_category(results: list[dict]) -> dict:
    from collections import defaultdict
    cats = defaultdict(lambda: {"n": 0, "guardrail_correct": 0, "result_correct": 0, "result_scored": 0})
    for r in results:
        c = cats[r["category"]]
        c["n"] += 1
        if r["guardrail_correct"] is not None:
            c["guardrail_correct"] += int(r["guardrail_correct"])
        if r["result_correct"] is not None:
            c["result_scored"] += 1
            c["result_correct"] += int(r["result_correct"])
    return dict(cats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="Label for this run, e.g. 'before' or 'after'")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = run_eval(args.label, verbose=args.verbose)
    n_infra = result["summary"]["n_infra_errors"]
    if n_infra:
        print(f"\n[WARNING] {n_infra}/{result['summary']['n_items']} item(s) hit an unhandled "
              f"exception (DB connection issue, most likely) rather than a real agent outcome: "
              f"{result['summary']['infra_error_ids']}. These are EXCLUDED from "
              f"sql_execution_accuracy / guardrail_accuracy below, not silently scored as pass "
              f"or fail. If this is most/all items, the DB is probably unreachable -- check "
              f"`service postgresql status` and .env before trusting any other number here.")
    print(f"\n=== {args.label} summary ===")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
