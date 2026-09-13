"""gate_math node — Gate 2: arithmetic integrity check.

Checks:
1. Each line_item.line_total ≈ quantity × unit_price (within 0.01 epsilon).
2. sum(line_totals) ≈ subtotal (within 0.01 epsilon).
3. subtotal + tax ≈ total (within 0.01 epsilon).

Even small discrepancies are a significant fraud signal — legitimate invoicing
software does not produce arithmetic errors. Flag, do not silently pass.

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason.
"""

from __future__ import annotations

from schemas.agent_state import AgentState
from schemas.gates import GateResult
from utils import now_eat

EPSILON = 0.01


async def gate_math(state: AgentState) -> AgentState:
    """Verify that all arithmetic on the invoice is internally consistent.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    state["current_gate"] = "math"
    parsed = state.get("parsed_invoice") or {}
    gate_results: list[dict] = list(state.get("gate_results") or [])

    def _fail(reason: str) -> AgentState:
        gate_results.append(
            GateResult(
                gate_name="math",
                passed=False,
                reason=reason,
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = True
        state["gate_failure_reason"] = reason
        return state

    line_items = parsed.get("line_items", [])
    subtotal = float(parsed.get("subtotal", 0))
    tax = float(parsed.get("tax", 0))
    total = float(parsed.get("total", 0))

    # 1. Check each line item's arithmetic.
    line_totals: list[float] = []
    for i, item in enumerate(line_items):
        qty = float(item.get("quantity", 0))
        unit_price = float(item.get("unit_price", 0))
        line_total = float(item.get("line_total", 0))
        expected = qty * unit_price

        if abs(line_total - expected) > EPSILON:
            return _fail(
                f"Line item {i + 1} ('{item.get('description', '')}') math error: "
                f"declared line_total={line_total:.4f}, "
                f"expected quantity({qty}) × unit_price({unit_price}) = {expected:.4f}"
            )
        line_totals.append(line_total)

    # 2. Sum of line totals must equal subtotal.
    computed_subtotal = sum(line_totals)
    if abs(computed_subtotal - subtotal) > EPSILON:
        return _fail(
            f"Subtotal mismatch: sum of line totals={computed_subtotal:.4f}, "
            f"declared subtotal={subtotal:.4f}"
        )

    # 3. subtotal + tax must equal total.
    computed_total = subtotal + tax
    if abs(computed_total - total) > EPSILON:
        return _fail(
            f"Total mismatch: subtotal({subtotal:.4f}) + tax({tax:.4f}) = {computed_total:.4f}, "
            f"declared total={total:.4f}"
        )

    # All arithmetic checks passed.
    gate_results.append(
        GateResult(
            gate_name="math",
            passed=True,
            reason="All line item and total arithmetic verified",
            details={
                "computed_subtotal": computed_subtotal,
                "declared_subtotal": subtotal,
                "computed_total": computed_total,
                "declared_total": total,
            },
            checked_at=now_eat(),
        ).model_dump()
    )
    state["gate_results"] = gate_results
    state["gate_failed"] = False
    return state
