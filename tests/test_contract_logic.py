"""Unit tests for the pure pieces of the UiPath contract v1.

No I/O, no mocks: the idempotency policy, the state → response mapping and
the contract schemas. Each policy test is one row of the design doc's
"How Kagua decides" table.

Run with:
    pytest tests/test_contract_logic.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from api.contract_mapping import GATE_FAILURE_RISK_SCORE, build_process_invoice_response
from api.idempotency import STALE_RESERVATION_AFTER, ReplayAction, decide_replay_action
from schemas.contract import (
    EMAIL_BODY_MAX_CHARS,
    InvoiceMetadataV1,
    ProcessingRecord,
    ProcessInvoiceResponse,
    ReviewDecisionRequest,
)
from utils import EAT

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=EAT)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _record(status: str = "completed", pdf_sha256: str = HASH_A, age: timedelta = timedelta(0)) -> ProcessingRecord:
    return ProcessingRecord(
        idempotency_key="INV-abc123-1",
        pdf_sha256=pdf_sha256,
        status=status,
        created_at=NOW - age,
        updated_at=NOW - age,
    )


def _metadata(**overrides) -> dict:
    data = {
        "idempotency_key": "INV-9f2c1a7b-1",
        "source_message_id": "<CAF=abc@mail.gmail.com>",
        "sender_email": "billing@vendor.co.ke",
        "subject": "Invoice 4471 - October",
        "received_at": "2026-11-10T09:14:00+03:00",
        "pdf_filename": "INV-4471.pdf",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Idempotency policy — one test per row of the design table
# ---------------------------------------------------------------------------


def test_policy_first_time_is_fresh() -> None:
    assert decide_replay_action(None, HASH_A, NOW) is ReplayAction.FRESH


def test_policy_retry_after_timeout_replays() -> None:
    assert decide_replay_action(_record("completed"), HASH_A, NOW) is ReplayAction.REPLAY


def test_policy_key_reused_with_different_pdf_conflicts() -> None:
    assert decide_replay_action(_record("completed", HASH_B), HASH_A, NOW) is ReplayAction.CONFLICT


def test_policy_conflict_wins_even_while_processing() -> None:
    """A different PDF is a Dispatcher bug regardless of the original run's state."""
    assert decide_replay_action(_record("processing", HASH_B), HASH_A, NOW) is ReplayAction.CONFLICT


def test_policy_recent_processing_is_in_progress() -> None:
    record = _record("processing", age=timedelta(seconds=30))
    assert decide_replay_action(record, HASH_A, NOW) is ReplayAction.IN_PROGRESS


def test_policy_stale_processing_is_taken_over() -> None:
    record = _record("processing", age=STALE_RESERVATION_AFTER + timedelta(seconds=1))
    assert decide_replay_action(record, HASH_A, NOW) is ReplayAction.TAKE_OVER


# ---------------------------------------------------------------------------
# State → contract response mapping
# ---------------------------------------------------------------------------


def _scored_state(**overrides) -> dict:
    state = {
        "invoice_id": "11111111-2222-3333-4444-555555555555",
        "routing_decision": "human_review",
        "risk_score": {"score": 62, "flags": ["new_vendor", "no_po"], "reasoning": "New vendor, no PO."},
        "gate_failed": False,
        "gate_results": [],
        "parsed_invoice": {"invoice_number": "4471", "vendor_name": "Acme Ltd"},
    }
    state.update(overrides)
    return state


def test_mapping_flattens_llm_score() -> None:
    response = build_process_invoice_response(_scored_state())
    assert response.model_dump() == {
        "invoice_id": "11111111-2222-3333-4444-555555555555",
        "routing_decision": "human_review",
        "risk_score": 62,
        "risk_flags": ["new_vendor", "no_po"],
        "risk_reasoning": "New vendor, no PO.",
        "replayed": False,
        "invoice_number": "4471",
        "vendor_name": "Acme Ltd",
    }


def test_mapping_gate_failure_scores_100_with_gate_flags() -> None:
    state = _scored_state(
        routing_decision="block",
        risk_score=None,
        gate_failed=True,
        gate_failure_reason="Duplicate invoice number '4471'",
        gate_results=[
            {"gate_name": "quality", "passed": True},
            {"gate_name": "duplicate", "passed": False},
        ],
    )
    response = build_process_invoice_response(state)
    assert response.risk_score == GATE_FAILURE_RISK_SCORE
    assert response.risk_flags == ["gate_duplicate_failed"]
    assert response.risk_reasoning == "Duplicate invoice number '4471'"


def test_mapping_missing_extraction_gives_nulls() -> None:
    response = build_process_invoice_response(_scored_state(parsed_invoice=None))
    assert response.invoice_number is None
    assert response.vendor_name is None


def test_mapping_rejects_missing_routing_decision() -> None:
    with pytest.raises(ValueError):
        build_process_invoice_response(_scored_state(routing_decision=None))


def test_mapping_rejects_state_without_score_or_gate_failure() -> None:
    with pytest.raises(ValueError):
        build_process_invoice_response(_scored_state(risk_score=None, gate_failed=False))


# ---------------------------------------------------------------------------
# Contract schemas
# ---------------------------------------------------------------------------


def test_metadata_valid_and_body_defaults_to_empty() -> None:
    metadata = InvoiceMetadataV1.model_validate(_metadata())
    assert metadata.email_body == ""


def test_metadata_truncates_long_email_body() -> None:
    metadata = InvoiceMetadataV1.model_validate(_metadata(email_body="x" * (EMAIL_BODY_MAX_CHARS + 500)))
    assert len(metadata.email_body) == EMAIL_BODY_MAX_CHARS


@pytest.mark.parametrize("bad_key", ["INV-", "INV-abc", "abc-123-1", "INV-ab c-1", "INV-" + "a" * 130 + "-1"])
def test_metadata_rejects_malformed_key(bad_key: str) -> None:
    with pytest.raises(ValidationError):
        InvoiceMetadataV1.model_validate(_metadata(idempotency_key=bad_key))


def test_metadata_rejects_v0_gmail_field() -> None:
    """extra='forbid': the old gmail_message_id field must fail loudly, not be ignored."""
    with pytest.raises(ValidationError):
        InvoiceMetadataV1.model_validate(_metadata(gmail_message_id="18c2f"))


def test_response_rejects_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ProcessInvoiceResponse(
            invoice_id="x", routing_decision="block", risk_score=101,
            risk_reasoning="", replayed=False,
        )


def test_review_request_requires_comment() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            idempotency_key="INV-abc123-1", decision="approve", reviewer="brian",
            comment="", decided_at=NOW,
        )
