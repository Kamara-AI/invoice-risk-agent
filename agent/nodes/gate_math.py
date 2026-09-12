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


async def gate_math(state: AgentState) -> AgentState:
    """Verify that all arithmetic on the invoice is internally consistent.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    pass
