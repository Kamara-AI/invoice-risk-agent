"""gate_duplicate node — Gate 3: duplicate invoice detection.

Checks:
1. No existing row in invoice_history shares the same invoice_number + vendor_id.
2. No existing row shares the same total + vendor_id + invoice_date within a
   7-day window (catches re-submissions with a different invoice number).

Duplicate invoices are one of the most common AP fraud vectors. Checking both
the explicit invoice number and the financial fingerprint catches both
naive and sophisticated re-submissions.

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason.
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def gate_duplicate(state: AgentState) -> AgentState:
    """Query invoice_history to detect duplicate or near-duplicate submissions.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    pass
