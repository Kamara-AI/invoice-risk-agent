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

import logging
from typing import Literal

from config import settings
from db.queries import create_invoice_record, update_invoice_status, upsert_vendor, write_audit_log
from db.queries import get_vendor_by_name
from integrations.slack import SlackClient
from schemas.agent_state import AgentState
from schemas.audit import AuditRecord
from utils import now_eat

logger = logging.getLogger(__name__)

_ACTION_RANK: dict[str, int] = {
    "auto_approve": 0,
    "human_review": 1,
    "block": 2,
}


def _resolve_action(
    gate_failed: bool,
    risk_score_dict: dict | None,
    llm_recommendation: str | None,
) -> tuple[Literal["auto_approve", "human_review", "block"], str]:
    """Apply business-rule thresholds and return (action, reason).

    The LLM recommendation can only be upgraded (block > human_review > auto_approve),
    never downgraded. Business rules always take precedence.
    """
    # Gate failure is an unconditional block.
    if gate_failed:
        return "block", "Invoice blocked by fraud detection gate"

    score = risk_score_dict.get("score", 0) if risk_score_dict else 0

    # Determine threshold-based action.
    if score >= 90:
        threshold_action: Literal["auto_approve", "human_review", "block"] = "block"
        threshold_reason = f"Risk score {score} >= 90 — automatic block"
    elif score >= 50:
        threshold_action = "human_review"
        threshold_reason = f"Risk score {score} >= 50 — requires human review"
    else:
        threshold_action = "auto_approve"
        threshold_reason = f"Risk score {score} < 50 — auto-approved"

    # Apply LLM recommendation — only upgrade, never downgrade.
    if llm_recommendation and llm_recommendation in _ACTION_RANK:
        threshold_rank = _ACTION_RANK[threshold_action]
        llm_rank = _ACTION_RANK[llm_recommendation]
        if llm_rank > threshold_rank:
            return llm_recommendation, (  # type: ignore[return-value]
                f"LLM recommended '{llm_recommendation}' (upgraded from '{threshold_action}')"
            )

    return threshold_action, threshold_reason


async def route_invoice(state: AgentState) -> AgentState:
    """Apply business-rule thresholds and dispatch the invoice to its destination.

    Args:
        state: Agent state with risk_score and gate_results populated.

    Returns:
        Updated state with routing_decision set and all persistence side-effects
        completed (Supabase write, Slack post).
    """
    # Guard: if parse_invoice (or any earlier node) set an error, bail out immediately.
    # Proceeding would write garbage rows to invoice_history from a None parsed_invoice.
    if state.get("error"):
        return state

    invoice_id = state.get("invoice_id", "")
    gate_failed = state.get("gate_failed", False)
    risk_score_dict = state.get("risk_score")
    gate_results = state.get("gate_results") or []
    parsed = state.get("parsed_invoice") or {}

    llm_recommendation = (risk_score_dict or {}).get("recommendation")
    action, reason = _resolve_action(gate_failed, risk_score_dict, llm_recommendation)

    state["routing_decision"] = action

    # --- Persist invoice record ---
    vendor_name = parsed.get("vendor_name", "")
    vendor_email = parsed.get("vendor_email", "")
    vendor_bank_account = parsed.get("vendor_bank_account")
    total = float(parsed.get("total", 0))
    currency = parsed.get("currency", "USD")
    invoice_number = parsed.get("invoice_number", "")

    # Upsert vendor — update last_seen and store bank fingerprint for future BEC checks.
    vendor_id: str | None = None
    try:
        existing_vendor = get_vendor_by_name(vendor_name)
        vendor_upsert_data: dict = {
            "name": vendor_name,
            "email": vendor_email,
            "last_seen": now_eat(),
        }
        # Only store the bank fingerprint when the invoice was NOT blocked.
        # A blocked invoice may carry a fraudulent (BEC-swapped) bank account —
        # writing that back to vendor_ledger would corrupt the reference fingerprint
        # and cause all subsequent legitimate invoices from this vendor to fail
        # the Stripe BEC check. Only approved/reviewed invoices carry a trusted fingerprint.
        if vendor_bank_account and action != "block":
            vendor_upsert_data["stripe_fingerprint"] = vendor_bank_account
        if action == "block":
            vendor_upsert_data["trust_level"] = "flagged"
        elif action == "auto_approve" and existing_vendor:
            vendor_upsert_data["trust_level"] = "trusted"

        upserted = upsert_vendor(vendor_upsert_data)
        vendor_id = upserted.get("vendor_id")
    except Exception as exc:
        logger.error("route_invoice: vendor upsert failed: %s", exc)

    # Create the invoice history record.
    invoice_record: dict = {
        "invoice_id": invoice_id,
        "vendor_id": vendor_id,
        "invoice_number": invoice_number,
        "amount": total,
        "currency": currency,
        "gate_results": gate_results,
        "risk_score": (risk_score_dict or {}).get("score"),
        "risk_flags": (risk_score_dict or {}).get("flags", []),
        "routing_decision": action,
        "status": "processing",
        "gmail_message_id": state.get("gmail_message_id"),
    }
    try:
        create_invoice_record(invoice_record)
    except Exception as exc:
        logger.error("route_invoice: invoice_history insert failed: %s", exc)

    # --- Dispatch ---
    slack = SlackClient()

    if action == "auto_approve":
        try:
            update_invoice_status(invoice_id, "approved", {"resolved_by": "system", "resolved_at": now_eat()})
        except Exception as exc:
            logger.error("route_invoice: status update to approved failed: %s", exc)

        try:
            write_audit_log(
                AuditRecord(
                    invoice_id=invoice_id,
                    event_type="route.auto_approve",
                    actor="system",
                    details={"reason": reason, "risk_score": (risk_score_dict or {}).get("score", 0)},
                    created_at=now_eat(),
                )
            )
        except Exception as exc:
            logger.error("route_invoice: audit log write failed: %s", exc)

    elif action == "human_review":
        risk_score_value = (risk_score_dict or {}).get("score", 0)
        ts: str | None = None
        slack_failed = False
        try:
            ts = slack.send_review_request(
                invoice_id=invoice_id,
                risk_score=risk_score_value,
                reasoning=(risk_score_dict or {}).get("reasoning", reason),
            )
            state["slack_message_ts"] = ts
        except Exception as exc:
            logger.error("route_invoice: Slack review card failed: %s", exc)
            slack_failed = True

        if slack_failed:
            # Slack failed — fall back to alert channel so invoice doesn't silently stall
            try:
                slack.send_alert(settings.slack_alert_channel_id,
                    f"REVIEW CARD FAILED for invoice {invoice_id} — manual review required. Risk score: {risk_score_value}")
            except Exception:
                pass
            update_invoice_status(invoice_id, "error", {"routing_decision": "human_review"})
        else:
            try:
                update_invoice_status(
                    invoice_id,
                    "processing",
                    {"slack_message_ts": ts},
                )
            except Exception as exc:
                logger.error("route_invoice: status update for human_review failed: %s", exc)

        try:
            write_audit_log(
                AuditRecord(
                    invoice_id=invoice_id,
                    event_type="route.human_review",
                    actor="system",
                    details={"reason": reason, "risk_score": (risk_score_dict or {}).get("score", 0)},
                    created_at=now_eat(),
                )
            )
        except Exception as exc:
            logger.error("route_invoice: audit log write failed: %s", exc)

    elif action == "block":
        alert_text = (
            f":rotating_light: *Invoice BLOCKED* — ID: `{invoice_id}`\n"
            f"Vendor: {vendor_name}\n"
            f"Amount: {currency} {total:,.2f}\n"
            f"Reason: {reason}\n"
            f"Gate failure: {state.get('gate_failure_reason', 'N/A')}"
        )
        try:
            slack.send_alert(settings.slack_alert_channel_id, alert_text)
        except Exception as exc:
            logger.error("route_invoice: Slack alert failed: %s", exc)

        try:
            update_invoice_status(invoice_id, "blocked", {"resolved_by": "system", "resolved_at": now_eat()})
        except Exception as exc:
            logger.error("route_invoice: status update to blocked failed: %s", exc)

        try:
            write_audit_log(
                AuditRecord(
                    invoice_id=invoice_id,
                    event_type="route.block",
                    actor="system",
                    details={
                        "reason": reason,
                        "gate_failure_reason": state.get("gate_failure_reason"),
                        "risk_score": (risk_score_dict or {}).get("score", 0),
                    },
                    created_at=now_eat(),
                )
            )
        except Exception as exc:
            logger.error("route_invoice: audit log write failed: %s", exc)

    return state
