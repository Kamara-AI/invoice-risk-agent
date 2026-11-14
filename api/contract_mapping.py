"""Map the final LangGraph state onto the flat contract response.

Pure functions, no I/O. This is the single place where Kagua's internal state
shape is translated to what the UiPath bot sees, so internal refactors only
ever touch this file, never the contract.
"""

from __future__ import annotations

from schemas.contract import ProcessInvoiceResponse

# Error codes set by graph nodes that mean "this input will never succeed":
# the route answers 422 (Business Rule Exception, no retry). Any other graph
# error is treated as transient and answered with 500 (System Exception, retry).
NON_RETRYABLE_ERROR_CODES: frozenset[str] = frozenset(
    {"unreadable_pdf", "not_an_invoice", "extraction_failed"}
)

# A gate failure is an unconditional block and the LLM never runs, so there is
# no LLM score. 100 keeps the response consistent with the block band (90–100).
GATE_FAILURE_RISK_SCORE = 100


def build_process_invoice_response(state: dict, replayed: bool = False) -> ProcessInvoiceResponse:
    """Translate a completed graph run into the contract response.

    Args:
        state: Final AgentState returned by the graph (no error set).
        replayed: Whether this response is being replayed from the ledger.

    Returns:
        A validated ProcessInvoiceResponse.

    Raises:
        ValueError: If the state has no usable routing decision or score —
            an internal inconsistency the route reports as 500.
    """
    routing_decision = state.get("routing_decision")
    if routing_decision not in ("auto_approve", "human_review", "block"):
        raise ValueError(f"graph finished without a valid routing_decision: {routing_decision!r}")

    risk = state.get("risk_score")
    if risk:
        risk_score = int(risk["score"])
        risk_flags = [str(flag) for flag in (risk.get("flags") or [])]
        risk_reasoning = risk.get("reasoning") or ""
    elif state.get("gate_failed"):
        risk_score = GATE_FAILURE_RISK_SCORE
        risk_flags = [
            f"gate_{result.get('gate_name')}_failed"
            for result in (state.get("gate_results") or [])
            if not result.get("passed")
        ]
        risk_reasoning = state.get("gate_failure_reason") or "Blocked by a fraud detection gate"
    else:
        raise ValueError("graph finished with neither a risk score nor a gate failure")

    parsed = state.get("parsed_invoice") or {}
    return ProcessInvoiceResponse(
        invoice_id=str(state["invoice_id"]),
        routing_decision=routing_decision,
        risk_score=risk_score,
        risk_flags=risk_flags,
        risk_reasoning=risk_reasoning,
        replayed=replayed,
        invoice_number=parsed.get("invoice_number") or None,
        vendor_name=parsed.get("vendor_name") or None,
    )
