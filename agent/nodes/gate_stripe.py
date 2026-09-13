"""gate_stripe node — Gate 5: payment fingerprint and Radar score check.

Checks:
1. If vendor is known, compare the current bank_account string to the stored
   stripe_fingerprint in vendor_ledger. A mismatch is a BEC (Business Email
   Compromise) signal — the attacker has swapped the bank account.
2. Retrieve the Stripe Radar risk score for the transaction amount.
   Scores above 75 trigger gate failure.

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason.
"""

from __future__ import annotations

import logging

from db.queries import get_vendor_by_name
from integrations.stripe_client import StripeClient
from schemas.agent_state import AgentState
from schemas.gates import GateResult
from utils import now_eat

logger = logging.getLogger(__name__)

_RADAR_THRESHOLD = 75.0


async def gate_stripe(state: AgentState) -> AgentState:
    """Validate payment details via Stripe fingerprinting and Radar scoring.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    state["current_gate"] = "stripe"
    parsed = state.get("parsed_invoice") or {}
    gate_results: list[dict] = list(state.get("gate_results") or [])

    vendor_name = parsed.get("vendor_name", "")
    vendor_email = parsed.get("vendor_email", "")
    vendor_bank_account = parsed.get("vendor_bank_account")
    total = float(parsed.get("total", 0))

    failure_reasons: list[str] = []
    details: dict = {}

    # --- BEC Detection: bank account fingerprint check ---
    try:
        vendor = get_vendor_by_name(vendor_name)
        if vendor is not None:
            stored_fingerprint = vendor.get("stripe_fingerprint")
            if stored_fingerprint and vendor_bank_account:
                if vendor_bank_account.strip() != stored_fingerprint.strip():
                    reason = (
                        f"Bank account fingerprint mismatch for known vendor '{vendor_name}' — "
                        "potential BEC fraud (bank details have changed)"
                    )
                    failure_reasons.append(reason)
                    details["bec_check"] = {
                        "stored_fingerprint_prefix": stored_fingerprint[:8] + "...",
                        "current_account_prefix": vendor_bank_account[:8] + "...",
                    }
                else:
                    details["bec_check"] = "fingerprint match"
            else:
                details["bec_check"] = "skipped (no stored fingerprint or no bank account on invoice)"
        else:
            details["bec_check"] = "new vendor — no prior fingerprint to compare"
    except Exception as exc:
        logger.warning("Stripe BEC check failed for vendor '%s': %s", vendor_name, exc)
        details["bec_check"] = f"error: {exc}"

    # --- Radar Score ---
    radar_score = 0.0
    try:
        stripe_client = StripeClient()
        radar_score = stripe_client.get_radar_score(total, vendor_email)
        details["radar_score"] = radar_score

        if radar_score > _RADAR_THRESHOLD:
            failure_reasons.append(
                f"Stripe Radar score {radar_score:.1f} exceeds threshold ({_RADAR_THRESHOLD})"
            )
    except Exception as exc:
        logger.warning("Stripe Radar score call failed for vendor '%s': %s", vendor_name, exc)
        details["radar_error"] = str(exc)

    # Determine gate outcome.
    if failure_reasons:
        reason = "; ".join(failure_reasons)
        gate_results.append(
            GateResult(
                gate_name="stripe",
                passed=False,
                reason=reason,
                details=details,
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = True
        state["gate_failure_reason"] = reason
    else:
        gate_results.append(
            GateResult(
                gate_name="stripe",
                passed=True,
                reason="Payment fingerprint and Radar score within acceptable thresholds",
                details=details,
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = False

    return state
