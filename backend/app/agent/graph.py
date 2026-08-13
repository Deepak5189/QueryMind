"""
Assembles the QueryMind agent as a LangGraph StateGraph.

    START
      -> retrieve_context
      -> generate_sql
      -> validate_sql --(valid)--------------> execute_sql --(ok)--> summarize -> END
                      \\--(invalid, retries left)--> generate_sql   \\--(db error)--> handle_failure -> END
                       \\--(invalid, retries exhausted)--> handle_failure -> END

retry_count (state.py) is capped at MAX_RETRIES=2 (backend/app/agent/nodes.py),
so validate_sql is reached at most 3 times per turn (1 initial attempt + 2
retries), matching the phase spec.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.app.agent.nodes import (
    execute_sql,
    generate_sql,
    handle_failure,
    retrieve_context,
    route_after_execute,
    route_after_validate,
    summarize,
    validate_sql,
)
from backend.app.agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("summarize", summarize)
    graph.add_node("handle_failure", handle_failure)

    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")

    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {"execute": "execute_sql", "retry": "generate_sql", "fail": "handle_failure"},
    )
    
    # graph.add_conditional_edges(
    #     "execute_sql",
    #     route_after_execute,
    #     {"summarize": "summarize", "fail": "handle_failure"},
    # )
    
    graph.add_conditional_edges(
    "execute_sql",
    route_after_execute,
    {
        "summarize": "summarize",
        "retry": "generate_sql",
        "fail": "handle_failure",
    },
)

    graph.add_edge("summarize", END)
    graph.add_edge("handle_failure", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    """Lazily compile once and reuse -- compilation isn't free and every
    CLI invocation of run_agent.py only needs one instance."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
