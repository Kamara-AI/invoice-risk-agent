"""LangGraph agent graph definition.

Graph topology (linear with conditional short-circuit):

    parse_invoice
        ↓
    gate_quality  ──[fail]──→ route_invoice
        ↓ [pass]
    gate_math     ──[fail]──→ route_invoice
        ↓ [pass]
    gate_duplicate──[fail]──→ route_invoice
        ↓ [pass]
    gate_ofac     ──[fail]──→ route_invoice
        ↓ [pass]
    gate_stripe   ──[fail]──→ route_invoice
        ↓ [pass]
    llm_score
        ↓
    route_invoice
        ↓
    END

Conditional edges (defined in agent/edges.py):
- after_gate: if state.gate_failed → "route_invoice", else → next gate name
- after_scoring: always → "route_invoice" (kept for future branching)

All nodes are async. The graph is compiled once at module level and reused
across requests — LangGraph compiled graphs are thread-safe and stateless
between runs.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.graph import CompiledGraph

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
    pass
