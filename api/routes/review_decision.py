"""Review decision route — Kagua API contract v1, decision D13.

POST /invoices/{invoice_id}/review-decision   application/json:
    schemas.contract.ReviewDecisionRequest

Called by the UiPath Review Handler after Brian approves or rejects a flagged
invoice in Action Center (and after the PDF was moved in the bucket). It
closes the loop in Kagua so vendor history reflects human judgement.

Rules:
    - The (invoice_id, idempotency_key) pair must match the ledger: the key
      proves the caller is the bot that scored this invoice.
    - Only invoices Kagua routed to human_review can be decided.
    - Idempotent: the same decision again → 200 replayed=true (the Handler
      retries 3 times on failure); a DIFFERENT decision → 409.

Write order: invoice_history status → audit_log → vendor trust restore
(approve on a flagged vendor only, agent/vendor_trust.py, own audit event)
→ ledger review columns. The ledger write is last, so a crash part-way
leaves the decision unrecorded and the retry redoes the (idempotent)
status update and trust restore.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from api.errors import ContractError
from db import processing_requests as request_store
from agent.vendor_trust import trust_after_human_decision
from db.queries import get_vendor_for_invoice, set_vendor_trust, update_invoice_status, write_audit_log
from schemas.audit import AuditRecord
from schemas.contract import ReviewDecisionRequest, ReviewDecisionResponse
from utils import EAT, now_eat

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUS_FOR_DECISION = {"approve": "approved", "reject": "rejected"}


@router.post("/{invoice_id}/review-decision", response_model=ReviewDecisionResponse)
async def review_decision(invoice_id: str, body: ReviewDecisionRequest) -> ReviewDecisionResponse:
    """Record a human review decision for an invoice Kagua sent to review."""
    key = body.idempotency_key
    new_status = _STATUS_FOR_DECISION[body.decision]

    record = await run_in_threadpool(request_store.get_processing_record, key)
    if record is None or record.status != "completed" or record.invoice_id != invoice_id:
        logger.info("review_decision key=%s invoice_id=%s rejected=not_found", key, invoice_id)
        raise ContractError(404, "invoice_not_found", "No scored invoice matches this invoice_id and idempotency_key")

    routed_to = (record.response or {}).get("routing_decision")
    if routed_to != "human_review":
        raise ContractError(
            409, "decision_conflict", f"Invoice was routed to {routed_to!r}, not human_review; nothing to decide"
        )

    if record.review_decision is not None:
        if record.review_decision == body.decision:
            logger.info("review_decision key=%s invoice_id=%s replayed decision=%s", key, invoice_id, body.decision)
            return ReviewDecisionResponse(
                invoice_id=invoice_id, decision=body.decision, status=new_status, replayed=True
            )
        raise ContractError(
            409, "decision_conflict",
            f"A different decision ({record.review_decision!r}) is already recorded for this invoice",
        )

    decided_at = body.decided_at.astimezone(EAT).isoformat()
    await run_in_threadpool(
        update_invoice_status,
        invoice_id,
        new_status,
        {"resolved_by": body.reviewer, "resolved_at": decided_at},
    )
    await run_in_threadpool(
        write_audit_log,
        AuditRecord(
            invoice_id=invoice_id,
            event_type=f"human.{body.decision}",
            actor=body.reviewer,
            details={
                "decision": body.decision,
                # Stored in the audit trail (Kagua's DB), never written to logs.
                "comment": body.comment,
                "source": "uipath_action_center",
                "idempotency_key": key,
                "decided_at": decided_at,
            },
            created_at=now_eat(),
        ),
    )
    await _apply_vendor_trust(invoice_id, body.decision, body.reviewer, key)
    await run_in_threadpool(request_store.record_review_decision, key, body.decision, body.reviewer, decided_at)

    logger.info("review_decision key=%s invoice_id=%s decision=%s", key, invoice_id, body.decision)
    return ReviewDecisionResponse(invoice_id=invoice_id, decision=body.decision, status=new_status, replayed=False)


async def _apply_vendor_trust(invoice_id: str, decision: str, reviewer: str, key: str) -> None:
    """Restore a flagged vendor's trust when a human approves its invoice.

    Why: only a human can clear a vendor flag (agent/vendor_trust.py). The
    change gets its own audit event so the trail shows who restored trust and
    on which invoice. Errors propagate: the Review Handler retries, and every
    step before the ledger write is idempotent.
    """
    vendor = await run_in_threadpool(get_vendor_for_invoice, invoice_id)
    if vendor is None:
        return
    new_trust = trust_after_human_decision(decision, vendor.get("trust_level"))
    if new_trust is None:
        return
    await run_in_threadpool(set_vendor_trust, vendor["vendor_id"], new_trust)
    await run_in_threadpool(
        write_audit_log,
        AuditRecord(
            invoice_id=invoice_id,
            event_type="vendor.trust_restored",
            actor=reviewer,
            details={
                "vendor_id": vendor["vendor_id"],
                "from": vendor.get("trust_level"),
                "to": new_trust,
                "idempotency_key": key,
            },
            created_at=now_eat(),
        ),
    )
    logger.info("review_decision key=%s vendor_id=%s trust %s -> %s",
                key, vendor["vendor_id"], vendor.get("trust_level"), new_trust)
