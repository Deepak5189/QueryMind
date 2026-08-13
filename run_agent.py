#!/usr/bin/env python3
"""
CLI for exercising the QueryMind LangGraph agent end-to-end, without a
frontend or API layer (those are later phases).

Usage:
    python run_agent.py "What was transaction volume last quarter by state?"
    python run_agent.py "your question" --verbose        # node-level trace log
    python run_agent.py --repl                            # interactive multi-turn session
    python run_agent.py --demo                             # scripted 3-turn demo (see below)

--demo runs a fixed sequence that exercises every required behavior in one
command, useful for reviewing this phase without typing anything:
    1. A normal analytics question (context retrieval -> SQL -> execution -> summary)
    2. A follow-up ("now filter to only Karnataka") that refines turn 1's
       query using conversation history, rather than starting over
    3. A deliberately unsafe question ("delete all open disputes") that
       the sqlglot guardrail rejects after exhausting retries -- proving
       the guardrail is real and doesn't depend on the LLM cooperating

By default this uses whatever LLM_PROVIDER is set in .env. If it's unset
or ANTHROPIC_API_KEY/OPENAI_API_KEY are missing, pass --mock to force the
deterministic MockLLM (see backend/app/agent/llm.py) so the graph
plumbing can still be exercised without an API key.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()


def _print_turn_result(result: dict) -> None:
    print("\n" + "=" * 100)
    print(f"QUESTION: {result['question']}")
    print("=" * 100)

    if result.get("failed"):
        print(f"\n❌ REJECTED after {result.get('retry_count', 0) + 1} attempt(s)")
        print(f"   Last candidate SQL: {result.get('candidate_sql', '(none)')}")
        print(f"   Reason: {result.get('failure_reason')}")
        print(f"\n{result.get('explanation', '')}")
        return

    print(f"\nSQL executed ({result.get('retry_count', 0)} retr" f"{'y' if result.get('retry_count') == 1 else 'ies'} needed):")
    print(f"  {result.get('executed_sql')}")

    rows = result.get("rows", [])
    columns = result.get("columns", [])
    if rows:
        print(f"\nResults ({result.get('row_count')} row(s), showing up to {len(rows)}):")
        print(tabulate([list(r.values()) for r in rows], headers=columns, tablefmt="simple"))
    else:
        print("\n(no rows returned)")

    print(f"\nExplanation:\n  {result.get('explanation')}")


def run_turn(graph, question: str, history: list) -> dict:
    state = {"question": question, "conversation_history": history}
    result = graph.invoke(state)
    _print_turn_result(result)
    return result.get("conversation_history", history)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", default=None, help="Natural-language question")
    parser.add_argument("--repl", action="store_true", help="Interactive multi-turn session")
    parser.add_argument("--demo", action="store_true", help="Run the scripted 3-turn demo")
    parser.add_argument("--verbose", action="store_true", help="Print node-level trace log lines")
    parser.add_argument(
        "--mock", action="store_true", help="Force LLM_PROVIDER=mock for this run (no API key needed)"
    )
    args = parser.parse_args()

    if args.mock:
        os.environ["LLM_PROVIDER"] = "mock"

    from backend.app.agent.graph import get_graph
    from backend.app.agent.tracing import configure_logging, langsmith_enabled

    configure_logging(verbose=args.verbose)
    if langsmith_enabled():
        print(f"(LangSmith tracing enabled -- project: {os.environ.get('LANGCHAIN_PROJECT', 'querymind')})")
    elif args.verbose:
        print("(No LangSmith key set -- falling back to structured stdout logging for node traces)")

    graph = get_graph()

    if args.demo:
        print("Running scripted 3-turn demo (forces --mock unless overridden)...")
        history: list = []
        history = run_turn(graph, "What was transaction volume last quarter by state?", history)
        history = run_turn(graph, "Now filter to only Karnataka", history)
        history = run_turn(graph, "Delete all disputes with status OPEN", history)
        return

    if args.repl:
        print("QueryMind agent REPL. Type a question, or 'exit' to quit.")
        history = []
        while True:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question or question.lower() in ("exit", "quit"):
                break
            history = run_turn(graph, question, history)
        return

    if not args.question:
        parser.print_help()
        sys.exit(1)

    run_turn(graph, args.question, [])


if __name__ == "__main__":
    main()
