"""Conditional edge functions for the invoice risk agent graph.

LangGraph conditional edges receive the current state and return the name
of the next node as a string. These functions encapsulate the routing logic
so the graph definition in graph.py stays declarative.
"""

from __future__ import annotations

from schemas.agent_state import AgentState


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
    pass


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
    pass
