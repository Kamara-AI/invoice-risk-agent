"""gate_stripe node — Gate 5: payment fingerprint and Radar score check.

Checks:
1. Retrieve the Stripe payment fingerprint for the vendor's bank account.
2. Compare the current fingerprint to the one stored in vendor_ledger.
   A mismatch on a known vendor is a high-confidence BEC (Business Email
   Compromise) signal — bank account details have been swapped by an attacker.
3. Retrieve the Stripe Radar risk score for the transaction.
   Scores above a configurable threshold (default: 75) trigger gate failure.

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason.
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def gate_stripe(state: AgentState) -> AgentState:
    """Validate payment details via Stripe fingerprinting and Radar scoring.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    pass
