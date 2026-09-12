"""route_invoice node — apply business rules and dispatch the invoice.

This node is the terminal action node. It:
1. Reads gate_failed, risk_score, and routing_decision to determine the action.
2. Writes the final routing_decision to state.
3. Dispatches the outcome:
   - auto_approve: writes to invoice_history (status='approved'), labels Gmail
     message, writes audit log.
   - human_review: posts a Slack review card to SLACK_REVIEW_CHANNEL_ID,
     stores slack_message_ts in state and invoice_history.
   - block: posts a Slack alert to SLACK_ALERT_CHANNEL_ID, writes to
     invoice_history (status='blocked'), writes audit log.

Business-rule thresholds (override LLM recommendation upward only):
- gate_failed=True → always block (regardless of LLM score)
- risk_score >= 90  → always block
- risk_score >= 50  → at minimum human_review
- risk_score < 50   → auto_approve (if LLM also recommends it)
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def route_invoice(state: AgentState) -> AgentState:
    """Apply business-rule thresholds and dispatch the invoice to its destination.

    Args:
        state: Agent state with risk_score and gate_results populated.

    Returns:
        Updated state with routing_decision set and all persistence side-effects
        completed (Supabase write, Slack post, Gmail label).
    """
    pass
