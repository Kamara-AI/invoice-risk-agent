"""gate_quality node — Gate 1: document completeness and sender authenticity.

Checks:
1. All required ParsedInvoice fields are present and non-empty.
2. The sender email from the Gmail envelope matches the vendor_email on the invoice
   (BEC invoices often arrive from lookalike domains).
3. invoice_date is not in the future; due_date is after invoice_date.
4. currency is a recognised ISO 4217 code.

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason, which triggers the short-circuit edge.
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def gate_quality(state: AgentState) -> AgentState:
    """Validate invoice completeness and sender-to-vendor email alignment.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    pass
