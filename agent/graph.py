"""LangGraph agent graph definition.

Graph topology (linear with conditional short-circuit):

    parse_invoice
        |
    gate_quality  --[fail]--> route_invoice
        | [pass]
    gate_math     --[fail]--> route_invoice
        | [pass]
    gate_duplicate--[fail]--> route_invoice
        | [pass]
    gate_ofac     --[fail]--> route_invoice
        | [pass]
    gate_stripe   --[fail]--> route_invoice
        | [pass]
    llm_score
        |
    route_invoice
        |
    END

Conditional edges (defined in agent/edges.py):
- after_gate: if state.gate_failed -> "route_invoice", else -> next gate name
- after_scoring: always -> "route_invoice" (kept for future branching)

All nodes are async. The graph is compiled once at module level and reused
across requests — LangGraph compiled graphs are thread-safe and stateless
between runs.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as CompiledGraph

from agent.edges import after_gate, after_scoring
from agent.nodes.gate_duplicate import gate_duplicate
from agent.nodes.gate_math import gate_math
from agent.nodes.gate_ofac import gate_ofac
from agent.nodes.gate_quality import gate_quality
from agent.nodes.gate_stripe import gate_stripe
from agent.nodes.llm_score import llm_score
from agent.nodes.parse_invoice import parse_invoice
from agent.nodes.route import route_invoice
from schemas.agent_state import AgentState


def build_graph() -> CompiledGraph:
    """Construct and compile the invoice risk agent graph.

    Nodes are registered by name; edges wire the control flow. Conditional
    edges use functions from agent/edges.py to read gate_failed from state
    and decide the next node at runtime.

    Returns:
        A compiled LangGraph StateGraph ready to invoke with an AgentState dict.
    """
    graph = StateGraph(AgentState)

    # Register all nodes.
    graph.add_node("parse_invoice", parse_invoice)
    graph.add_node("gate_quality", gate_quality)
    graph.add_node("gate_math", gate_math)
    graph.add_node("gate_duplicate", gate_duplicate)
    graph.add_node("gate_ofac", gate_ofac)
    graph.add_node("gate_stripe", gate_stripe)
    graph.add_node("llm_score", llm_score)
    graph.add_node("route_invoice", route_invoice)

    # Entry point.
    graph.set_entry_point("parse_invoice")

    # Direct edge: parse always goes to the first gate.
    graph.add_edge("parse_invoice", "gate_quality")

    # Conditional edges for each gate — after_gate decides next node from state.
    _all_possible_next = {
        "gate_math": "gate_math",
        "gate_duplicate": "gate_duplicate",
        "gate_ofac": "gate_ofac",
        "gate_stripe": "gate_stripe",
        "llm_score": "llm_score",
        "route_invoice": "route_invoice",
    }

    for gate_name in ["gate_quality", "gate_math", "gate_duplicate", "gate_ofac", "gate_stripe"]:
        graph.add_conditional_edges(gate_name, after_gate, _all_possible_next)

    # After LLM scoring, always route.
    graph.add_conditional_edges(
        "llm_score",
        after_scoring,
        {"route_invoice": "route_invoice"},
    )

    # Terminal edge.
    graph.add_edge("route_invoice", END)

    return graph.compile()
