"""gate_ofac node — Gate 4: OFAC sanctions screening.

Checks:
1. vendor_name against the OFAC SDN (Specially Designated Nationals) list.
2. Updates vendor_ledger.ofac_status to 'clear' or 'flagged' after the check.

This gate calls the OFAC API (integrations/ofac.py). A 'flagged' result is
a hard block — do not route to human_review, route directly to block.
The gate_failed flag handles this; the route node applies the block action.

OFAC hits must be escalated to compliance immediately. The route node sends
a Slack alert to SLACK_ALERT_CHANNEL_ID (not the review channel).

On pass: appends a GateResult(passed=True) to gate_results, continues.
On fail: appends a GateResult(passed=False), sets gate_failed=True and
         gate_failure_reason.
"""

from __future__ import annotations

import logging

from integrations.ofac import OFACClient
from schemas.agent_state import AgentState
from schemas.gates import GateResult
from utils import now_eat

logger = logging.getLogger(__name__)


async def gate_ofac(state: AgentState) -> AgentState:
    """Screen the invoice vendor against the OFAC sanctions list.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    state["current_gate"] = "ofac"
    parsed = state.get("parsed_invoice") or {}
    gate_results: list[dict] = list(state.get("gate_results") or [])

    vendor_name = parsed.get("vendor_name", "")

    try:
        client = OFACClient()
        result = client.check_vendor(vendor_name)

        score = result.get("score", 0.0)
        matches = result.get("matches", [])

        if score >= 90:
            # Hard block — high-confidence sanctions match.
            match_summary = "; ".join(
                m.get("sanction", {}).get("name", "unknown") for m in matches[:3]
            )
            reason = f"OFAC SDN confirmed match (score {score:.0f}) for vendor '{vendor_name}': {match_summary}"
            gate_results.append(
                GateResult(
                    gate_name="ofac",
                    passed=False,
                    reason=reason,
                    details={"score": score, "tier": "hard_block", "match_count": len(matches), "matches": matches[:3]},
                    checked_at=now_eat(),
                ).model_dump()
            )
            state["gate_results"] = gate_results
            state["gate_failed"] = True
            state["gate_failure_reason"] = reason
            return state

        if score >= 75:
            # Soft flag — partial/ambiguous match. Gate passes but LLM sees the warning.
            match_summary = "; ".join(
                m.get("sanction", {}).get("name", "unknown") for m in matches[:2]
            )
            reason = (
                f"OFAC partial match (score {score:.0f}, below hard-block threshold) "
                f"for vendor '{vendor_name}': {match_summary} — escalating to LLM review"
            )
            gate_results.append(
                GateResult(
                    gate_name="ofac",
                    passed=True,
                    reason=reason,
                    details={"score": score, "tier": "soft_flag", "match_count": len(matches)},
                    checked_at=now_eat(),
                ).model_dump()
            )
            state["gate_results"] = gate_results
            state["gate_failed"] = False
            return state

        # No meaningful match — gate passes cleanly.
        gate_results.append(
            GateResult(
                gate_name="ofac",
                passed=True,
                reason=f"Vendor '{vendor_name}' cleared OFAC SDN screening (score {score:.0f})",
                details={"score": score, "tier": "clear"},
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = False

    except Exception as exc:
        # OFAC API failure is NOT a sanctions hit. Log the warning and pass the gate
        # so the invoice is not erroneously blocked by an infrastructure failure.
        logger.warning("OFAC API call failed for vendor '%s': %s", vendor_name, exc)
        gate_results.append(
            GateResult(
                gate_name="ofac",
                passed=True,
                reason=f"OFAC API unavailable — screening skipped (not a sanctions hit): {exc}",
                details={"api_error": str(exc)},
                checked_at=now_eat(),
            ).model_dump()
        )
        state["gate_results"] = gate_results
        state["gate_failed"] = False

    return state
