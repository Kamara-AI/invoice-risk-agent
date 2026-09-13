"""Conditional edge functions for the invoice risk agent graph.

LangGraph conditional edges receive the current state and return the name
of the next node as a string. These functions encapsulate the routing logic
so the graph definition in graph.py stays declarative.
"""

from __future__ import annotations

from schemas.agent_state import AgentState

# Canonical gate order — must match the graph topology in graph.py.
_GATE_ORDER = ["quality", "math", "duplicate", "ofac", "stripe"]


def after_gate(state: AgentState) -> str:
    """Decide the next node after any gate has run.

    If a gate set gate_failed=True, we skip remaining gates and go directly
    to route_invoice — no point running further checks on a blocked invoice.
    The route node reads gate_failed and gate_failure_reason to make its decision.

    Args:
        state: Current agent state after a gate node has executed.

    Returns:
        Name of the next node: "route_invoice" on failure, or the name of the
        next gate / "llm_score" if all gates have passed.
    """
    if state.get("gate_failed"):
        return "route_invoice"

    current = state.get("current_gate", "")
    try:
        idx = _GATE_ORDER.index(current)
        if idx < len(_GATE_ORDER) - 1:
            return f"gate_{_GATE_ORDER[idx + 1]}"
        else:
            # All gates passed — proceed to LLM scoring.
            return "llm_score"
    except ValueError:
        # current_gate not in the list — route_invoice is the safe fallback;
        # routing to llm_score would run the LLM on an empty/None parsed_invoice.
        return "route_invoice"


def after_scoring(state: AgentState) -> str:
    """Decide the next node after llm_score has run.

    Currently always routes to route_invoice. Kept as a named function rather
    than a direct edge so future branching (e.g. escalation path) can be added
    without changing the graph topology.

    Args:
        state: Current agent state after the llm_score node has executed.

    Returns:
        Always "route_invoice".
    """
    return "route_invoice"
