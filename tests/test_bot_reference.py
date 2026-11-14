"""Tests for tools/bot_simulator: reference components + the full scenario suite.

The GOLDEN vectors below are the acceptance test for Brian's VB versions of
BuildIdempotencyKey.xaml, CleanEmailBody.xaml and MaskEmail.xaml: feed the
same inputs to the XAML, compare to these outputs. They are hard-coded on
purpose — recomputing them with hashlib here would make the test circular.

The scenario suite runs against the real route code with the in-memory fakes
from test_contract_api.py, so every live scenario is exercised without a
database or LLM.

Run with:
    pytest tests/test_bot_reference.py -v
"""

from __future__ import annotations

import io

import pypdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from schemas.contract import InvoiceMetadataV1
from tests.test_contract_api import FakeGraph, FakeLedger, _scored_result
from tools.bot_simulator import simulate
from tools.bot_simulator.pdf_factory import NEWSLETTER_LINES, make_text_pdf
from tools.bot_simulator.reference import build_idempotency_key, classify_status, clean_email_body, mask_email

# ---------------------------------------------------------------------------
# GOLDEN: BuildIdempotencyKey
# ---------------------------------------------------------------------------

GOLDEN_KEYS = [
    ("<CAF=abc123@mail.gmail.com>", 1, "INV-1b907f8969aa-1"),
    ("CAF=abc123@mail.gmail.com", 1, "INV-1b907f8969aa-1"),     # brackets do not change the key
    ("<CAF=abc123@mail.gmail.com>", 2, "INV-1b907f8969aa-2"),   # second PDF in the same email
    ("<20261110.4471@vendor.co.ke>", 1, "INV-f311a169a806-1"),
    ("  <X@y>  ", 3, "INV-7916384f98fe-3"),                     # surrounding whitespace ignored
]


@pytest.mark.parametrize(("message_id", "index", "expected"), GOLDEN_KEYS)
def test_golden_idempotency_keys(message_id: str, index: int, expected: str) -> None:
    assert build_idempotency_key(message_id, index) == expected


def test_key_is_accepted_by_the_contract() -> None:
    key = build_idempotency_key("<CAF=abc123@mail.gmail.com>", 1)
    InvoiceMetadataV1.model_validate({
        "idempotency_key": key, "source_message_id": "x", "sender_email": "a@b.co",
        "subject": "", "received_at": "2026-11-14T18:00:00+03:00", "pdf_filename": "a.pdf",
    })


@pytest.mark.parametrize(("message_id", "index"), [("", 1), ("<>", 1), ("<a@b>", 0)])
def test_key_rejects_bad_input(message_id: str, index: int) -> None:
    with pytest.raises(ValueError):
        build_idempotency_key(message_id, index)


# ---------------------------------------------------------------------------
# GOLDEN: CleanEmailBody
# ---------------------------------------------------------------------------

GOLDEN_BODIES = [
    (
        "Hi,\r\n\r\nInvoice attached.\r\n\r\nRegards,\r\nJane\r\n-- \r\nJane Doe | Acme\r\n",
        "Hi,\n\nInvoice attached.\n\nRegards,\nJane",
    ),
    (
        "Please pay by Friday.\n\nOn Mon, 10 Nov 2026 at 09:00, Brian <b@x.com> wrote:\n> Send the invoice\n",
        "Please pay by Friday.",
    ),
    (
        "New bank details below.\n-----Original Message-----\nFrom: someone\nold text\n",
        "New bank details below.",
    ),
    (
        "See attached.\n> quoted line\n>> deeper quote\nThanks\n\n\n\n\nSent from my iPhone\n",
        "See attached.\nThanks",
    ),
    ("   \r\n  \r\n", ""),
]


@pytest.mark.parametrize(("raw", "expected"), GOLDEN_BODIES)
def test_golden_clean_email_body(raw: str, expected: str) -> None:
    assert clean_email_body(raw) == expected


def test_clean_email_body_truncates_to_4000() -> None:
    assert len(clean_email_body("a" * 5000)) == 4000


def test_simulator_raw_body_cleans_to_expected_text() -> None:
    assert clean_email_body(simulate.RAW_EMAIL_BODY) == (
        "Hi,\n\nPlease find attached our invoice for October.\n\nRegards,\nAccounts"
    )


# ---------------------------------------------------------------------------
# GOLDEN: MaskEmail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("billing@vendor.co.ke", "b***@vendor.co.ke"),
        ("  Brian.Otango@gmail.com ", "B***@gmail.com"),
        ("a@b.co", "a***@b.co"),
        ("@nolocal.com", "***"),
        ("not-an-email", "***"),
        ("", "***"),
    ],
)
def test_golden_mask_email(email: str, expected: str) -> None:
    assert mask_email(email) == expected


# ---------------------------------------------------------------------------
# Performer status rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "outcome"),
    [(200, "success"), (409, "business_rule_exception"), (422, "business_rule_exception"),
     (404, "business_rule_exception"), (500, "system_exception"), (503, "system_exception"),
     (None, "system_exception")],
)
def test_classify_status(status: int | None, outcome: str) -> None:
    assert classify_status(status) == outcome


# ---------------------------------------------------------------------------
# PDF factory
# ---------------------------------------------------------------------------


def test_text_pdf_is_readable_by_pypdf() -> None:
    pdf = make_text_pdf(NEWSLETTER_LINES + ["Tricky (parens) and \\ backslash"])
    text = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert pdf.startswith(b"%PDF-1.4")
    assert "VENDOR MONTHLY NEWSLETTER" in text
    assert "Tricky (parens) and \\ backslash" in text


# ---------------------------------------------------------------------------
# Full scenario suite against the real routes + fakes
# ---------------------------------------------------------------------------


@pytest.fixture()
def sim_client(monkeypatch: pytest.MonkeyPatch):
    import api.routes.invoice as invoice_route
    import api.routes.review_decision as review_route
    from api.errors import register_error_handlers
    from unittest.mock import MagicMock

    ledger, graph = FakeLedger(), FakeGraph()

    def outcome(state: dict) -> dict:
        # Behave like the real parser for the newsletter, score everything else for review.
        if b"NEWSLETTER" in state["raw_pdf_bytes"]:
            return {**state, "error": "parse_invoice: not an invoice: newsletter", "error_code": "not_an_invoice"}
        return _scored_result(state)

    graph.outcome = outcome
    monkeypatch.setattr(invoice_route, "request_store", ledger)
    monkeypatch.setattr(invoice_route, "_graph", graph)
    monkeypatch.setattr(review_route, "request_store", ledger)
    monkeypatch.setattr(review_route, "update_invoice_status", MagicMock())
    monkeypatch.setattr(review_route, "write_audit_log", MagicMock())

    app = FastAPI()
    app.include_router(invoice_route.router, prefix="/invoices")
    app.include_router(review_route.router, prefix="/invoices")
    from api.routes.health import router as health_router
    app.include_router(health_router)
    register_error_handlers(app)
    return TestClient(app)


def test_offline_suite_passes(sim_client: TestClient) -> None:
    report = simulate.run(sim_client, live=False)
    assert report["failed"] == 0, report["results"]
    assert report["passed"] == len(simulate.OFFLINE_SCENARIOS)


def test_live_suite_passes_against_fakes(sim_client: TestClient) -> None:
    report = simulate.run(sim_client, live=True)
    failures = [r for r in report["results"] if not r["passed"]]
    assert failures == []
    names = {r["scenario"] for r in report["results"]}
    assert {"fresh_score", "retry_replays_same_result", "same_key_different_pdf_conflicts",
            "rejects_not_an_invoice", "review_approve", "review_approve_again_replays",
            "review_conflicting_decision_409", "review_unknown_invoice_404"} <= names
