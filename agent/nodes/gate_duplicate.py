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

from datetime import date, timedelta

from db.queries import get_vendor_by_name
from db.client import supabase
from schemas.agent_state import AgentState
from schemas.gates import GateResult
from utils import now_eat


async def gate_duplicate(state: AgentState) -> AgentState:
    """Query invoice_history to detect duplicate or near-duplicate submissions.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    state["current_gate"] = "duplicate"
    parsed = state.get("parsed_invoice") or {}
    gate_results: list[dict] = list(state.get("gate_results") or [])

    def _fail(reason: str, details: dict | None = None) -> AgentState:
        gate_results.append(
            GateResult(
                gate_name="duplicate",
                passed=False,
                reason=reason,
                details=details,
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = True
        state["gate_failure_reason"] = reason
        return state

    invoice_number = parsed.get("invoice_number", "")
    vendor_name = parsed.get("vendor_name", "")
    total = float(parsed.get("total", 0))
    invoice_date_raw = parsed.get("invoice_date")

    # Normalise invoice_date to a date object.
    if isinstance(invoice_date_raw, str):
        try:
            invoice_date = date.fromisoformat(invoice_date_raw)
        except ValueError:
            invoice_date = None
    elif isinstance(invoice_date_raw, date):
        invoice_date = invoice_date_raw
    else:
        invoice_date = None

    # Look up the vendor in vendor_ledger.
    vendor = get_vendor_by_name(vendor_name)

    if vendor is None:
        # New vendor — no history to check against, pass immediately.
        gate_results.append(
            GateResult(
                gate_name="duplicate",
                passed=True,
                reason="New vendor — no prior invoice history to check",
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = False
        return state

    vendor_id = vendor.get("vendor_id")

    # Check 1: Same invoice_number + vendor_id in invoice_history.
    existing_by_number = (
        supabase.table("invoice_history")
        .select("invoice_id, invoice_number, status")
        .eq("invoice_number", invoice_number)
        .eq("vendor_id", vendor_id)
        .execute()
    )
    if existing_by_number.data:
        existing = existing_by_number.data[0]
        return _fail(
            f"Duplicate invoice number '{invoice_number}' already exists for vendor '{vendor_name}'",
            details={"existing_invoice_id": existing.get("invoice_id"), "status": existing.get("status")},
        )

    # Check 2: Same total + vendor_id within a 7-day window of invoice_date.
    if invoice_date is not None:
        window_start = (invoice_date - timedelta(days=7)).isoformat()
        window_end = (invoice_date + timedelta(days=7)).isoformat()

        existing_by_amount = (
            supabase.table("invoice_history")
            .select("invoice_id, invoice_number, amount, status")
            .eq("vendor_id", vendor_id)
            .eq("amount", total)
            .gte("submitted_at", window_start)
            .lte("submitted_at", window_end)
            .execute()
        )
        if existing_by_amount.data:
            existing = existing_by_amount.data[0]
            return _fail(
                f"Potential duplicate: same amount ({total}) for vendor '{vendor_name}' "
                f"within 7 days of invoice date '{invoice_date}'",
                details={
                    "existing_invoice_id": existing.get("invoice_id"),
                    "existing_invoice_number": existing.get("invoice_number"),
                    "status": existing.get("status"),
                },
            )

    # No duplicates found.
    gate_results.append(
        GateResult(
            gate_name="duplicate",
            passed=True,
            reason="No duplicate invoice found in history",
            details={"vendor_id": vendor_id, "invoice_number": invoice_number},
            checked_at=now_eat(),
        ).model_dump()
    )
    state["gate_results"] = gate_results
    state["gate_failed"] = False
    return state
