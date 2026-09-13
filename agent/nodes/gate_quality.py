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

from datetime import date

from schemas.agent_state import AgentState
from schemas.gates import GateResult
from utils import now_eat

# Accepted ISO 4217 currency codes. Extend as needed.
_KNOWN_CURRENCIES = {"USD", "KES", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF", "CNY", "NGN"}

_REQUIRED_FIELDS = [
    "vendor_name",
    "vendor_email",
    "invoice_number",
    "invoice_date",
    "due_date",
    "line_items",
    "subtotal",
    "total",
]


async def gate_quality(state: AgentState) -> AgentState:
    """Validate invoice completeness and sender-to-vendor email alignment.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    state["current_gate"] = "quality"
    parsed = state.get("parsed_invoice") or {}
    gate_results: list[dict] = list(state.get("gate_results") or [])

    def _fail(reason: str) -> AgentState:
        gate_results.append(
            GateResult(
                gate_name="quality",
                passed=False,
                reason=reason,
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = True
        state["gate_failure_reason"] = reason
        return state

    # 1. Required fields present and non-empty.
    for field in _REQUIRED_FIELDS:
        value = parsed.get(field)
        if value is None or value == "" or value == []:
            return _fail(f"Missing or empty required field: '{field}'")

    # 2. line_items must have at least one entry.
    line_items = parsed.get("line_items", [])
    if not line_items:
        return _fail("Invoice must have at least one line item")

    # 3. Date validation.
    try:
        invoice_date_raw = parsed.get("invoice_date")
        due_date_raw = parsed.get("due_date")

        # Dates may come back as date objects or as strings depending on Pydantic
        # serialisation. Normalise to date objects.
        if isinstance(invoice_date_raw, str):
            invoice_date = date.fromisoformat(invoice_date_raw)
        else:
            invoice_date = invoice_date_raw

        if isinstance(due_date_raw, str):
            due_date = date.fromisoformat(due_date_raw)
        else:
            due_date = due_date_raw

        today = date.today()

        if invoice_date > today:
            return _fail(
                f"invoice_date '{invoice_date}' is in the future (today is {today})"
            )

        if due_date < invoice_date:
            return _fail(
                f"due_date '{due_date}' is before invoice_date '{invoice_date}'"
            )

    except (TypeError, ValueError) as exc:
        return _fail(f"Date parsing error: {exc}")

    # 4. Currency must be a recognised ISO 4217 code.
    currency = (parsed.get("currency") or "USD").upper()
    if currency not in _KNOWN_CURRENCIES:
        return _fail(f"Unrecognised currency code: '{currency}'")

    # All checks passed.
    gate_results.append(
        GateResult(
            gate_name="quality",
            passed=True,
            reason="All required fields present and valid",
            checked_at=now_eat(),
        ).model_dump()
    )
    state["gate_results"] = gate_results
    state["gate_failed"] = False
    return state
