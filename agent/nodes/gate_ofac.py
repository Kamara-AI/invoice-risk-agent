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

from schemas.agent_state import AgentState


async def gate_ofac(state: AgentState) -> AgentState:
    """Screen the invoice vendor against the OFAC sanctions list.

    Args:
        state: Agent state with parsed_invoice populated.

    Returns:
        Updated state with gate_results appended and gate_failed set if applicable.
    """
    pass
