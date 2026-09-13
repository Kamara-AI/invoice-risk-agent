"""Unit tests for all Pydantic schema models.

Validates that models accept valid data, reject invalid data, and that
defaults and constraints behave as documented.

Run with:
    pytest tests/test_schemas.py -v
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from schemas.audit import AuditRecord
from schemas.gates import GateResult
from schemas.invoice import InvoiceInput, LineItem, ParsedInvoice
from schemas.risk import RiskScore, RoutingDecision


# ---------------------------------------------------------------------------
# LineItem
# ---------------------------------------------------------------------------

def test_line_item_valid() -> None:
    """LineItem should instantiate successfully with valid fields."""
    item = LineItem(
        description="Widget A",
        quantity=10,
        unit_price=5.50,
        line_total=55.00,
    )
    assert item.description == "Widget A"
    assert item.quantity == 10
    assert item.unit_price == 5.50
    assert item.line_total == 55.00


def test_line_item_rejects_zero_quantity() -> None:
    """LineItem should raise ValidationError if quantity is 0 or negative."""
    with pytest.raises(ValidationError) as exc_info:
        LineItem(
            description="Widget A",
            quantity=0,
            unit_price=5.50,
            line_total=0.00,
        )
    assert "quantity" in str(exc_info.value)

    with pytest.raises(ValidationError):
        LineItem(
            description="Widget A",
            quantity=-3,
            unit_price=5.50,
            line_total=0.00,
        )


# ---------------------------------------------------------------------------
# InvoiceInput
# ---------------------------------------------------------------------------

def test_invoice_input_valid() -> None:
    """InvoiceInput should instantiate with a valid EmailStr sender."""
    inp = InvoiceInput(
        gmail_message_id="msg_abc123",
        sender_email="vendor@example.com",
        subject="Invoice #1234",
        received_at=datetime(2026, 1, 15, 10, 0, 0),
        pdf_filename="invoice_1234.pdf",
    )
    assert inp.sender_email == "vendor@example.com"
    assert inp.gmail_message_id == "msg_abc123"
    assert inp.pdf_filename == "invoice_1234.pdf"


def test_invoice_input_rejects_invalid_email() -> None:
    """InvoiceInput should raise ValidationError for a malformed sender_email."""
    with pytest.raises(ValidationError) as exc_info:
        InvoiceInput(
            gmail_message_id="msg_abc123",
            sender_email="not-an-email",
            subject="Invoice #1234",
            received_at=datetime(2026, 1, 15, 10, 0, 0),
            pdf_filename="invoice_1234.pdf",
        )
    assert "sender_email" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ParsedInvoice
# ---------------------------------------------------------------------------

def _make_parsed_invoice(**overrides) -> ParsedInvoice:
    """Helper to create a valid ParsedInvoice with sensible defaults."""
    defaults = {
        "invoice_number": "INV-001",
        "vendor_name": "Acme Corp",
        "vendor_email": "billing@acme.com",
        "line_items": [
            LineItem(
                description="Widget A",
                quantity=2,
                unit_price=50.00,
                line_total=100.00,
            )
        ],
        "subtotal": 100.00,
        "tax": 16.00,
        "total": 116.00,
        "invoice_date": date(2026, 1, 10),
        "due_date": date(2026, 2, 10),
    }
    defaults.update(overrides)
    return ParsedInvoice(**defaults)


def test_parsed_invoice_valid() -> None:
    """ParsedInvoice should instantiate with all required fields and default currency."""
    inv = _make_parsed_invoice()
    assert inv.invoice_number == "INV-001"
    assert inv.vendor_name == "Acme Corp"
    assert inv.currency == "USD"
    assert len(inv.line_items) == 1
    assert inv.total == 116.00


def test_parsed_invoice_default_currency() -> None:
    """ParsedInvoice.currency should default to 'USD' when not provided."""
    inv = _make_parsed_invoice()
    assert inv.currency == "USD"

    inv_kes = _make_parsed_invoice(currency="KES")
    assert inv_kes.currency == "KES"


def test_parsed_invoice_rejects_empty_line_items() -> None:
    """ParsedInvoice should raise ValidationError if line_items is an empty list."""
    with pytest.raises(ValidationError) as exc_info:
        _make_parsed_invoice(line_items=[])
    assert "line_items" in str(exc_info.value)


def test_parsed_invoice_model_dump_structure() -> None:
    """ParsedInvoice.model_dump should produce a dict with expected keys."""
    inv = _make_parsed_invoice()
    dumped = inv.model_dump()
    assert isinstance(dumped, dict)
    assert "invoice_number" in dumped
    assert "line_items" in dumped
    assert isinstance(dumped["line_items"], list)
    assert dumped["line_items"][0]["description"] == "Widget A"
    # Optional fields should be present with default/None values
    assert "vendor_bank_account" in dumped
    assert dumped["vendor_bank_account"] is None
    assert "purchase_order_ref" in dumped
    assert dumped["purchase_order_ref"] is None


def test_parsed_invoice_rejects_negative_total() -> None:
    """ParsedInvoice should reject negative total (ge=0 constraint)."""
    with pytest.raises(ValidationError):
        _make_parsed_invoice(total=-10.00)


# ---------------------------------------------------------------------------
# RiskScore
# ---------------------------------------------------------------------------

def test_risk_score_valid() -> None:
    """RiskScore should instantiate with a score in [0, 100] and valid recommendation."""
    rs = RiskScore(
        score=45,
        flags=["math_mismatch"],
        reasoning="Minor arithmetic discrepancy detected.",
        recommendation="human_review",
    )
    assert rs.score == 45
    assert rs.flags == ["math_mismatch"]
    assert rs.recommendation == "human_review"


def test_risk_score_boundary_values() -> None:
    """RiskScore should accept boundary values 0 and 100."""
    rs_low = RiskScore(
        score=0,
        reasoning="No risk detected.",
        recommendation="auto_approve",
    )
    assert rs_low.score == 0
    assert rs_low.flags == []

    rs_high = RiskScore(
        score=100,
        flags=["ofac_hit", "bec_detected"],
        reasoning="Confirmed sanctions match.",
        recommendation="block",
    )
    assert rs_high.score == 100


def test_risk_score_rejects_score_above_100() -> None:
    """RiskScore should raise ValidationError if score > 100."""
    with pytest.raises(ValidationError) as exc_info:
        RiskScore(
            score=101,
            reasoning="Over the limit.",
            recommendation="block",
        )
    assert "score" in str(exc_info.value)


def test_risk_score_rejects_score_below_0() -> None:
    """RiskScore should raise ValidationError if score < 0."""
    with pytest.raises(ValidationError):
        RiskScore(
            score=-1,
            reasoning="Negative score.",
            recommendation="auto_approve",
        )


def test_risk_score_rejects_invalid_recommendation() -> None:
    """RiskScore should raise ValidationError for an unrecognised recommendation value."""
    with pytest.raises(ValidationError) as exc_info:
        RiskScore(
            score=50,
            reasoning="Some reasoning.",
            recommendation="maybe_approve",
        )
    assert "recommendation" in str(exc_info.value)


def test_risk_score_default_flags() -> None:
    """RiskScore.flags should default to an empty list when not provided."""
    rs = RiskScore(
        score=20,
        reasoning="Low risk.",
        recommendation="auto_approve",
    )
    assert rs.flags == []


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------

def test_routing_decision_valid() -> None:
    """RoutingDecision should instantiate with a valid Literal action."""
    rd = RoutingDecision(
        action="auto_approve",
        reason="Score below threshold.",
        invoice_id="inv-uuid-001",
        risk_score=25,
    )
    assert rd.action == "auto_approve"
    assert rd.invoice_id == "inv-uuid-001"
    assert rd.risk_score == 25


def test_routing_decision_rejects_unknown_action() -> None:
    """RoutingDecision should raise ValidationError for an unrecognised action."""
    with pytest.raises(ValidationError) as exc_info:
        RoutingDecision(
            action="escalate",
            reason="Unknown action.",
            invoice_id="inv-uuid-002",
            risk_score=50,
        )
    assert "action" in str(exc_info.value)


def test_routing_decision_rejects_score_above_100() -> None:
    """RoutingDecision should reject risk_score above 100."""
    with pytest.raises(ValidationError):
        RoutingDecision(
            action="block",
            reason="Max risk.",
            invoice_id="inv-uuid-003",
            risk_score=150,
        )


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------

def test_gate_result_valid_pass() -> None:
    """GateResult should instantiate with passed=True and no details."""
    gr = GateResult(
        gate_name="quality",
        passed=True,
        reason="All fields present.",
        checked_at="2026-01-15T10:00:00+03:00",
    )
    assert gr.passed is True
    assert gr.details is None
    assert gr.gate_name == "quality"


def test_gate_result_valid_fail_with_details() -> None:
    """GateResult should accept a structured details dict when passed=False."""
    gr = GateResult(
        gate_name="ofac",
        passed=False,
        reason="OFAC SDN match detected.",
        details={"score": 95.0, "tier": "hard_block", "match_count": 2},
        checked_at="2026-01-15T10:05:00+03:00",
    )
    assert gr.passed is False
    assert gr.details["score"] == 95.0
    assert gr.details["tier"] == "hard_block"


def test_gate_result_model_dump() -> None:
    """GateResult.model_dump should produce a serialisable dict."""
    gr = GateResult(
        gate_name="math",
        passed=True,
        reason="Arithmetic OK.",
        details={"computed_total": 116.00},
        checked_at="2026-01-15T10:00:00+03:00",
    )
    dumped = gr.model_dump()
    assert isinstance(dumped, dict)
    assert dumped["gate_name"] == "math"
    assert dumped["passed"] is True
    assert dumped["details"]["computed_total"] == 116.00


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------

def test_audit_record_valid() -> None:
    """AuditRecord should instantiate with log_id=None before DB insert."""
    ar = AuditRecord(
        invoice_id="inv-uuid-001",
        event_type="gate.quality.pass",
        actor="system",
        details={"gate": "quality", "passed": True},
        created_at="2026-01-15T10:00:00+03:00",
    )
    assert ar.log_id is None
    assert ar.invoice_id == "inv-uuid-001"
    assert ar.event_type == "gate.quality.pass"
    assert ar.actor == "system"


def test_audit_record_default_details() -> None:
    """AuditRecord.details should default to an empty dict."""
    ar = AuditRecord(
        invoice_id="inv-uuid-002",
        event_type="route.block",
        actor="system",
        created_at="2026-01-15T10:30:00+03:00",
    )
    assert ar.details == {}


def test_audit_record_with_log_id() -> None:
    """AuditRecord should accept an explicit log_id (post-DB insert)."""
    ar = AuditRecord(
        log_id="uuid-from-db-001",
        invoice_id="inv-uuid-003",
        event_type="human.approve",
        actor="U12345",
        details={"decision": "approved"},
        created_at="2026-01-15T11:00:00+03:00",
    )
    assert ar.log_id == "uuid-from-db-001"


def test_audit_record_model_dump_excludes_none_log_id() -> None:
    """AuditRecord.model_dump should include log_id even when None."""
    ar = AuditRecord(
        invoice_id="inv-uuid-004",
        event_type="error.unhandled",
        actor="system",
        created_at="2026-01-15T12:00:00+03:00",
    )
    dumped = ar.model_dump()
    assert "log_id" in dumped
    assert dumped["log_id"] is None
