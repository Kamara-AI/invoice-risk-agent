"""Invoice processing route — Kagua API contract v1 (UiPath bot).

POST /invoices/process-invoice   multipart/form-data:
    invoice_metadata  JSON string, schemas.contract.InvoiceMetadataV1
    pdf_file          the PDF attachment

Flow (each step logs one line keyed by idempotency_key; the email body and
invoice contents are never logged):

    validate metadata + PDF ──422──▶ Business Rule Exception in the bot
    hash PDF, read ledger row
    decide_replay_action:
        REPLAY       → 200 stored response, replayed=true   (retry after timeout)
        CONFLICT     → 409 idempotency_conflict              (Dispatcher bug)
        IN_PROGRESS  → 503 processing_in_progress            (bot retries later)
        FRESH        → reserve key ─┐
        TAKE_OVER    → claim stale ─┴▶ run graph
    graph error with permanent error_code → release key, 422
    graph error otherwise                 → release key, 500 (bot retries)
    success → store response in ledger, 200 replayed=false

Status code → bot behaviour is fixed by the contract: 409/422 = Business Rule
Exception (no retry, alert); 5xx/timeout = System Exception (queue retries).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from agent.graph import build_graph
from api.contract_mapping import NON_RETRYABLE_ERROR_CODES, build_process_invoice_response
from api.errors import ContractError
from api.idempotency import STALE_RESERVATION_AFTER, ReplayAction, decide_replay_action
from db import processing_requests as request_store
from schemas.contract import InvoiceMetadataV1, ProcessInvoiceResponse
from utils import EAT, now_eat

logger = logging.getLogger(__name__)

router = APIRouter()

# Compiled graph is built once when the module loads — not per request.
# build_graph() compiles the StateGraph; the result is stateless and reusable.
_graph = build_graph()

# Every PDF starts with this signature; checking it rejects HTML error pages,
# images and empty files before any LLM money is spent.
_PDF_MAGIC = b"%PDF"

# How long the bot should wait before retrying a key that is mid-run.
_RETRY_AFTER_SECONDS = "60"


def _parse_metadata(raw: str) -> InvoiceMetadataV1:
    """Validate the invoice_metadata part. Any problem is a permanent 422."""
    try:
        return InvoiceMetadataV1.model_validate(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ContractError(422, "invalid_metadata", f"invoice_metadata is not valid JSON: {exc.msg}") from exc
    except ValidationError as exc:
        # Field names and error types only — never echo input values (could be PII).
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'body'}: {e['type']}" for e in exc.errors())
        raise ContractError(422, "invalid_metadata", f"invoice_metadata failed validation: {problems}") from exc


def _initial_state(invoice_id: str, pdf_bytes: bytes, metadata: InvoiceMetadataV1) -> dict:
    """Build the AgentState for one UiPath-originated run."""
    return {
        "invoice_id": invoice_id,
        "raw_pdf_bytes": pdf_bytes,
        # invoice_history.gmail_message_id is the cross-reference column the
        # graph already writes; on this path it holds the source Message-ID.
        "gmail_message_id": metadata.source_message_id,
        "idempotency_key": metadata.idempotency_key,
        "source_message_id": metadata.source_message_id,
        "email_body": metadata.email_body or None,
        # Validated by the contract but previously dropped here, so the documented
        # sender-vs-vendor check could never run (found 2026-11-16).
        "sender_email": str(metadata.sender_email),
        "policy_flags": [],
        # Review is in UiPath Action Center and alerts go by email — no Slack.
        "notify_slack": False,
        "error_code": None,
        "parsed_invoice": None,
        "gate_results": [],
        "current_gate": None,
        "gate_failed": False,
        "gate_failure_reason": None,
        "risk_score": None,
        "routing_decision": None,
        "slack_message_ts": None,
        "human_decision": None,
        "audit_record_id": None,
        "error": None,
        "created_at": now_eat(),
    }


async def _claim_key(action: ReplayAction, key: str, pdf_sha256: str, source_message_id: str) -> None:
    """Take ownership of the key for this run, or raise 503 if someone else holds it."""
    if action is ReplayAction.FRESH:
        owned = await run_in_threadpool(
            request_store.reserve_processing_record, key, pdf_sha256, source_message_id
        )
    else:  # TAKE_OVER
        cutoff = (datetime.now(EAT) - STALE_RESERVATION_AFTER).isoformat()
        owned = await run_in_threadpool(request_store.take_over_stale_record, key, cutoff)
    if not owned:
        # Lost a race with a concurrent request for the same key.
        raise ContractError(
            503, "processing_in_progress", "This idempotency_key is being processed; retry later.",
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        )


async def _release_key(key: str) -> None:
    """Best-effort release after a failed run; a failure here only delays the retry."""
    try:
        await run_in_threadpool(request_store.release_processing_record, key)
    except Exception:
        logger.exception("process_invoice key=%s release_failed (stale takeover will recover)", key)


@router.post("/process-invoice", response_model=ProcessInvoiceResponse)
async def process_invoice(
    invoice_metadata: str = Form(...),
    pdf_file: UploadFile = File(...),
) -> ProcessInvoiceResponse:
    """Score one invoice PDF idempotently. See the module docstring for the flow."""
    metadata = _parse_metadata(invoice_metadata)
    key = metadata.idempotency_key

    pdf_bytes = await pdf_file.read()
    if not pdf_bytes.startswith(_PDF_MAGIC):
        logger.info("process_invoice key=%s rejected=unreadable_pdf bytes=%d", key, len(pdf_bytes))
        raise ContractError(422, "unreadable_pdf", "pdf_file is empty or is not a PDF")
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    existing = await run_in_threadpool(request_store.get_processing_record, key)
    action = decide_replay_action(existing, pdf_sha256, datetime.now(EAT))
    logger.info("process_invoice key=%s action=%s", key, action.value)

    if action is ReplayAction.REPLAY:
        assert existing is not None and existing.response is not None
        stored = ProcessInvoiceResponse.model_validate(existing.response)
        return stored.model_copy(update={"replayed": True})

    if action is ReplayAction.CONFLICT:
        raise ContractError(
            409, "idempotency_conflict",
            "idempotency_key was already used for a different PDF (check the Dispatcher's key builder)",
        )

    if action is ReplayAction.IN_PROGRESS:
        raise ContractError(
            503, "processing_in_progress", "This idempotency_key is being processed; retry later.",
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        )

    await _claim_key(action, key, pdf_sha256, metadata.source_message_id)

    invoice_id = str(uuid.uuid4())
    try:
        result = await _graph.ainvoke(_initial_state(invoice_id, pdf_bytes, metadata))
    except Exception as exc:
        await _release_key(key)
        logger.exception("process_invoice key=%s graph_crashed", key)
        raise ContractError(500, "internal_error", "Kagua failed while scoring; safe to retry") from exc

    if result.get("error"):
        await _release_key(key)
        error_code = result.get("error_code")
        logger.warning("process_invoice key=%s graph_error code=%s", key, error_code or "transient")
        if error_code in NON_RETRYABLE_ERROR_CODES:
            raise ContractError(422, error_code, result["error"])
        raise ContractError(500, "internal_error", "Kagua failed while scoring; safe to retry")

    try:
        response = build_process_invoice_response(result, replayed=False)
    except ValueError as exc:
        await _release_key(key)
        logger.error("process_invoice key=%s inconsistent_state: %s", key, exc)
        raise ContractError(500, "internal_error", "Kagua produced an inconsistent result; safe to retry") from exc

    # The invoice is already persisted by the graph. If the ledger write fails we
    # still return 200: the bot has its answer and will not retry. Only if the
    # response is ALSO lost (timeout) could a retry re-score — logged loudly.
    try:
        await run_in_threadpool(
            request_store.complete_processing_record, key, invoice_id, response.model_dump(mode="json")
        )
    except Exception:
        logger.exception("process_invoice key=%s ledger_complete_failed invoice_id=%s", key, invoice_id)

    logger.info(
        "process_invoice key=%s invoice_id=%s routing=%s score=%d",
        key, invoice_id, response.routing_decision, response.risk_score,
    )
    return response
