"""Unit tests for all five gate nodes.

Each test constructs a minimal AgentState, calls the gate node, and asserts
on the resulting gate_results entry and gate_failed flag.

Run with:
    pytest tests/test_gates.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock heavy dependencies BEFORE importing gate modules.
# config.py and db/client.py eagerly initialise Supabase and read env vars
# at import time. We inject mocks into sys.modules to prevent that.
# ---------------------------------------------------------------------------

# Mock config module
_mock_config = ModuleType("config")
_mock_settings = MagicMock()
_mock_config.settings = _mock_settings  # type: ignore[attr-defined]
sys.modules.setdefault("config", _mock_config)

# Mock db.client module (supabase singleton)
_mock_db = ModuleType("db")
sys.modules.setdefault("db", _mock_db)

_mock_db_client = ModuleType("db.client")
_mock_supabase = MagicMock()
_mock_db_client.supabase = _mock_supabase  # type: ignore[attr-defined]
sys.modules.setdefault("db.client", _mock_db_client)

# Mock db.queries module
_mock_db_queries = ModuleType("db.queries")
_mock_db_queries.get_vendor_by_name = MagicMock()  # type: ignore[attr-defined]
# route_invoice (imported for its pure _resolve_action) needs these names to exist.
for _name in ("create_invoice_record", "update_invoice_status", "upsert_vendor", "write_audit_log"):
    setattr(_mock_db_queries, _name, MagicMock())
sys.modules.setdefault("db.queries", _mock_db_queries)

# Mock integrations modules
_mock_integrations = ModuleType("integrations")
sys.modules.setdefault("integrations", _mock_integrations)

_mock_ofac_module = ModuleType("integrations.ofac")
_mock_ofac_client_cls = MagicMock()
_mock_ofac_module.OFACClient = _mock_ofac_client_cls  # type: ignore[attr-defined]
sys.modules.setdefault("integrations.ofac", _mock_ofac_module)

_mock_stripe_module = ModuleType("integrations.stripe_client")
_mock_stripe_client_cls = MagicMock()
_mock_stripe_module.StripeClient = _mock_stripe_client_cls  # type: ignore[attr-defined]
sys.modules.setdefault("integrations.stripe_client", _mock_stripe_module)

_mock_slack_module = ModuleType("integrations.slack")
_mock_slack_module.SlackClient = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("integrations.slack", _mock_slack_module)

# Now safe to import gate modules
import agent.nodes.gate_ofac as gate_ofac_module
from agent.nodes.gate_duplicate import gate_duplicate
from agent.nodes.gate_math import gate_math
from agent.nodes.gate_ofac import gate_ofac
from agent.nodes.gate_quality import gate_quality
from agent.nodes.gate_stripe import gate_stripe
from agent.nodes.route import _resolve_action
from agent.policy_flags import SANCTIONS_NOT_SCREENED, SANCTIONS_SCREENING_FAILED, SENDER_DOMAIN_MISMATCH


@pytest.fixture(autouse=True)
def _ofac_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """OFAC tests exercise the screening path; .env may have it switched off."""
    monkeypatch.setattr(gate_ofac_module.settings, "ofac_enabled", True, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(**overrides) -> dict:
    """Create a minimal AgentState dict with sensible defaults."""
    state = {
        "invoice_id": "test-uuid-001",
        "raw_pdf_bytes": None,
        "gmail_message_id": "msg_test",
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
        "created_at": "2026-01-15T10:00:00+03:00",
    }
    state.update(overrides)
    return state


def _valid_parsed_invoice(**overrides) -> dict:
    """Create a valid parsed invoice dict."""
    invoice = {
        "invoice_number": "INV-001",
        "vendor_name": "Acme Corp",
        "vendor_email": "billing@acme.com",
        "vendor_bank_account": "ACC-123456789",
        "line_items": [
            {
                "description": "Widget A",
                "quantity": 10,
                "unit_price": 5.00,
                "line_total": 50.00,
            },
            {
                "description": "Widget B",
                "quantity": 5,
                "unit_price": 20.00,
                "line_total": 100.00,
            },
        ],
        "subtotal": 150.00,
        "tax": 24.00,
        "total": 174.00,
        "currency": "USD",
        "invoice_date": date.today().isoformat(),
        "due_date": date(2026, 12, 31).isoformat(),
        "purchase_order_ref": "PO-5678",
    }
    invoice.update(overrides)
    return invoice


# ---------------------------------------------------------------------------
# gate_quality
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_quality_passes_valid_invoice() -> None:
    """gate_quality should pass a complete, valid ParsedInvoice."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is False
    assert len(result["gate_results"]) == 1
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "quality"
    assert gate["passed"] is True
    assert "checked_at" in gate


@pytest.mark.asyncio
async def test_gate_quality_fails_missing_fields() -> None:
    """gate_quality should fail when required invoice fields are empty."""
    parsed = _valid_parsed_invoice(vendor_name="")
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is True
    assert len(result["gate_results"]) == 1
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "quality"
    assert gate["passed"] is False
    assert "vendor_name" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_quality_fails_missing_invoice_number() -> None:
    """gate_quality should fail when invoice_number is None."""
    parsed = _valid_parsed_invoice(invoice_number=None)
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "invoice_number" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_quality_fails_future_invoice_date() -> None:
    """gate_quality should fail when invoice_date is in the future."""
    parsed = _valid_parsed_invoice(invoice_date="2099-12-31")
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "future" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_quality_fails_due_date_before_invoice_date() -> None:
    """gate_quality should fail when due_date is before invoice_date."""
    parsed = _valid_parsed_invoice(
        invoice_date="2026-06-15",
        due_date="2026-06-01",
    )
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "before" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_quality_fails_unrecognised_currency() -> None:
    """gate_quality should fail for an unrecognised currency code."""
    parsed = _valid_parsed_invoice(currency="XYZ")
    state = _base_state(parsed_invoice=parsed)

    result = await gate_quality(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "XYZ" in gate["reason"]


# --- gate_quality: sender vs vendor email (tiered, agent/sender_check.py) ---
# The fixture invoice's vendor_email is billing@acme.com.

@pytest.mark.asyncio
async def test_gate_quality_sender_same_domain_passes_without_flag() -> None:
    state = _base_state(parsed_invoice=_valid_parsed_invoice(), sender_email="accounts@acme.com")
    result = await gate_quality(state)
    assert result["gate_failed"] is False
    assert not result.get("policy_flags")
    assert "sender matches" in result["gate_results"][0]["reason"]


@pytest.mark.asyncio
async def test_gate_quality_sender_lookalike_blocks() -> None:
    state = _base_state(parsed_invoice=_valid_parsed_invoice(vendor_email="billing@apexoffice.com"),
                        sender_email="billing@apex0ffice.com")
    result = await gate_quality(state)
    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False and "lookalike" in gate["reason"]
    assert "billing@" not in gate["reason"], "reasons carry domains only, never full addresses"


@pytest.mark.asyncio
async def test_gate_quality_sender_other_domain_passes_with_review_flag() -> None:
    state = _base_state(parsed_invoice=_valid_parsed_invoice(), sender_email="acme.accounts@gmail.com")
    result = await gate_quality(state)
    assert result["gate_failed"] is False
    assert result["policy_flags"] == [SENDER_DOMAIN_MISMATCH]
    assert "human review required" in result["gate_results"][0]["reason"]


@pytest.mark.asyncio
async def test_gate_quality_without_sender_skips_the_check() -> None:
    """Streamlit/evals runs carry no envelope sender."""
    result = await gate_quality(_base_state(parsed_invoice=_valid_parsed_invoice()))
    assert result["gate_failed"] is False
    assert not result.get("policy_flags")


@pytest.mark.asyncio
async def test_gate_quality_reports_bad_fields_before_sender() -> None:
    state = _base_state(parsed_invoice=_valid_parsed_invoice(currency="XYZ"),
                        sender_email="billing@apex0ffice.com")
    result = await gate_quality(state)
    assert "XYZ" in result["gate_results"][0]["reason"]


# ---------------------------------------------------------------------------
# route: policy flags can only upgrade auto_approve → human_review
# ---------------------------------------------------------------------------

def test_route_policy_flag_upgrades_auto_approve_to_review() -> None:
    action, reason = _resolve_action(False, {"score": 10}, "auto_approve", [SENDER_DOMAIN_MISMATCH])
    assert action == "human_review"
    assert SENDER_DOMAIN_MISMATCH in reason


def test_route_screening_failure_forces_review() -> None:
    action, _ = _resolve_action(False, {"score": 5}, None, [SANCTIONS_SCREENING_FAILED])
    assert action == "human_review"


def test_route_informational_flag_does_not_force_review() -> None:
    action, _ = _resolve_action(False, {"score": 10}, "auto_approve", [SANCTIONS_NOT_SCREENED])
    assert action == "auto_approve"


def test_route_policy_flag_never_downgrades_a_block() -> None:
    assert _resolve_action(True, None, None, [SENDER_DOMAIN_MISMATCH])[0] == "block"
    assert _resolve_action(False, {"score": 95}, None, [SENDER_DOMAIN_MISMATCH])[0] == "block"


def test_route_without_flags_is_unchanged() -> None:
    assert _resolve_action(False, {"score": 10}, "auto_approve")[0] == "auto_approve"
    assert _resolve_action(False, {"score": 60}, None, [])[0] == "human_review"


# ---------------------------------------------------------------------------
# gate_math
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_math_passes_correct_arithmetic() -> None:
    """gate_math should pass when all line totals and subtotal/total are correct."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    result = await gate_math(state)

    assert result["gate_failed"] is False
    assert len(result["gate_results"]) == 1
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "math"
    assert gate["passed"] is True
    assert gate["details"]["computed_subtotal"] == 150.00
    assert gate["details"]["declared_subtotal"] == 150.00


@pytest.mark.asyncio
async def test_gate_math_fails_line_total_mismatch() -> None:
    """gate_math should fail when a line_total does not match quantity x unit_price."""
    parsed = _valid_parsed_invoice(
        line_items=[
            {
                "description": "Widget A",
                "quantity": 10,
                "unit_price": 5.00,
                "line_total": 999.99,  # Should be 50.00
            },
        ],
        subtotal=999.99,
        tax=0.00,
        total=999.99,
    )
    state = _base_state(parsed_invoice=parsed)

    result = await gate_math(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "math"
    assert gate["passed"] is False
    assert "math error" in gate["reason"]
    assert "Widget A" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_math_fails_subtotal_mismatch() -> None:
    """gate_math should fail when sum of line_totals does not match subtotal."""
    parsed = _valid_parsed_invoice(
        line_items=[
            {
                "description": "Widget A",
                "quantity": 10,
                "unit_price": 5.00,
                "line_total": 50.00,
            },
        ],
        subtotal=999.00,  # Should be 50.00
        tax=0.00,
        total=999.00,
    )
    state = _base_state(parsed_invoice=parsed)

    result = await gate_math(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "math"
    assert gate["passed"] is False
    assert "Subtotal mismatch" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_math_fails_total_mismatch() -> None:
    """gate_math should fail when subtotal + tax != total."""
    parsed = _valid_parsed_invoice(
        line_items=[
            {
                "description": "Widget A",
                "quantity": 10,
                "unit_price": 5.00,
                "line_total": 50.00,
            },
        ],
        subtotal=50.00,
        tax=8.00,
        total=999.00,  # Should be 58.00
    )
    state = _base_state(parsed_invoice=parsed)

    result = await gate_math(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "Total mismatch" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_math_passes_within_epsilon() -> None:
    """gate_math should pass when values differ by less than epsilon (0.01)."""
    parsed = _valid_parsed_invoice(
        line_items=[
            {
                "description": "Widget A",
                "quantity": 3,
                "unit_price": 33.33,
                "line_total": 99.99,  # 3 * 33.33 = 99.99 exactly
            },
        ],
        subtotal=99.99,
        tax=0.00,
        total=99.99,
    )
    state = _base_state(parsed_invoice=parsed)

    result = await gate_math(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True


# ---------------------------------------------------------------------------
# gate_duplicate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_duplicate_passes_new_invoice() -> None:
    """gate_duplicate should pass when no matching invoice exists in history."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    # Mock: vendor exists but no duplicate invoice found
    with patch("agent.nodes.gate_duplicate.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_duplicate.supabase") as mock_supa:

        mock_vendor.return_value = {"vendor_id": "v-001", "name": "Acme Corp"}

        # No matching invoice_number
        mock_number_query = MagicMock()
        mock_number_query.execute.return_value = MagicMock(data=[])

        # No matching amount in date window
        mock_amount_query = MagicMock()
        mock_amount_query.execute.return_value = MagicMock(data=[])

        # Chain: supabase.table().select().eq().eq().execute()
        mock_table = MagicMock()
        mock_supa.table.return_value = mock_table

        # First call chain (by invoice number)
        mock_select1 = MagicMock()
        mock_table.select.side_effect = [mock_select1, MagicMock()]

        mock_eq1a = MagicMock()
        mock_select1.eq.return_value = mock_eq1a
        mock_eq1b = MagicMock()
        mock_eq1a.eq.return_value = mock_eq1b
        mock_eq1b.execute.return_value = MagicMock(data=[])

        # Second call chain (by amount) - need to set up the full chain
        mock_select2 = MagicMock()
        mock_table.select.side_effect = [mock_select1, mock_select2]

        mock_eq2a = MagicMock()
        mock_select2.eq.return_value = mock_eq2a
        mock_eq2b = MagicMock()
        mock_eq2a.eq.return_value = mock_eq2b
        mock_gte = MagicMock()
        mock_eq2b.gte.return_value = mock_gte
        mock_lte = MagicMock()
        mock_gte.lte.return_value = mock_lte
        mock_lte.execute.return_value = MagicMock(data=[])

        result = await gate_duplicate(state)

    assert result["gate_failed"] is False
    assert len(result["gate_results"]) == 1
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "duplicate"
    assert gate["passed"] is True


@pytest.mark.asyncio
async def test_gate_duplicate_passes_new_vendor() -> None:
    """gate_duplicate should pass immediately for a vendor not in vendor_ledger."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_duplicate.get_vendor_by_name") as mock_vendor:
        mock_vendor.return_value = None  # New vendor

        result = await gate_duplicate(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True
    assert "New vendor" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_duplicate_fails_exact_duplicate() -> None:
    """gate_duplicate should fail when invoice_number + vendor_id match an existing record."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_duplicate.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_duplicate.supabase") as mock_supa:

        mock_vendor.return_value = {"vendor_id": "v-001", "name": "Acme Corp"}

        # Duplicate found by invoice number
        mock_table = MagicMock()
        mock_supa.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq1 = MagicMock()
        mock_select.eq.return_value = mock_eq1
        mock_eq2 = MagicMock()
        mock_eq1.eq.return_value = mock_eq2
        mock_eq2.execute.return_value = MagicMock(data=[
            {"invoice_id": "existing-001", "invoice_number": "INV-001", "status": "approved"}
        ])

        result = await gate_duplicate(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "duplicate"
    assert gate["passed"] is False
    assert "Duplicate" in gate["reason"]
    assert gate["details"]["existing_invoice_id"] == "existing-001"


# ---------------------------------------------------------------------------
# gate_ofac
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_ofac_passes_clear_vendor() -> None:
    """gate_ofac should pass when the OFAC API returns no match."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        mock_client = MagicMock()
        MockOFAC.return_value = mock_client
        mock_client.check_vendor.return_value = {
            "match": False,
            "score": 0.0,
            "matches": [],
        }

        result = await gate_ofac(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "ofac"
    assert gate["passed"] is True
    assert gate["details"]["tier"] == "clear"
    assert "cleared" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_ofac_passes_soft_flag() -> None:
    """gate_ofac should pass with soft flag when score is 75-89."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        mock_client = MagicMock()
        MockOFAC.return_value = mock_client
        mock_client.check_vendor.return_value = {
            "match": True,
            "score": 80.0,
            "matches": [
                {"sanction": {"name": "Similar Name Corp"}}
            ],
        }

        result = await gate_ofac(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True
    assert gate["details"]["tier"] == "soft_flag"
    assert gate["details"]["score"] == 80.0


@pytest.mark.asyncio
async def test_gate_ofac_fails_sanctioned_vendor() -> None:
    """gate_ofac should fail when the OFAC API returns a match above threshold."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        mock_client = MagicMock()
        MockOFAC.return_value = mock_client
        mock_client.check_vendor.return_value = {
            "match": True,
            "score": 95.0,
            "matches": [
                {"sanction": {"name": "Sanctioned Entity Ltd"}, "score": 95.0}
            ],
        }

        result = await gate_ofac(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "ofac"
    assert gate["passed"] is False
    assert gate["details"]["tier"] == "hard_block"
    assert gate["details"]["score"] == 95.0
    assert "confirmed match" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_ofac_passes_on_api_error() -> None:
    """gate_ofac should pass (not block) when the OFAC API is unavailable."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        mock_client = MagicMock()
        MockOFAC.return_value = mock_client
        mock_client.check_vendor.side_effect = ConnectionError("API timeout")

        result = await gate_ofac(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True
    assert "unavailable" in gate["reason"].lower()
    assert gate["details"]["api_error"] == "API timeout"
    # Decision #8: a failed screen is not a hit, but must not be approved unseen.
    assert result["policy_flags"] == [SANCTIONS_SCREENING_FAILED]


@pytest.mark.asyncio
async def test_gate_ofac_disabled_skips_api_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ofac_enabled=False the API is never called and the response says so."""
    monkeypatch.setattr(gate_ofac_module.settings, "ofac_enabled", False, raising=False)
    state = _base_state(parsed_invoice=_valid_parsed_invoice())

    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        result = await gate_ofac(state)

    MockOFAC.assert_not_called()
    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True and gate["details"]["tier"] == "disabled"
    assert "NOT screened" in gate["reason"]
    assert result["policy_flags"] == [SANCTIONS_NOT_SCREENED]


@pytest.mark.asyncio
async def test_gate_ofac_clear_vendor_adds_no_policy_flag() -> None:
    state = _base_state(parsed_invoice=_valid_parsed_invoice())
    with patch("agent.nodes.gate_ofac.OFACClient") as MockOFAC:
        MockOFAC.return_value.check_vendor.return_value = {"match": False, "score": 0.0, "matches": []}
        result = await gate_ofac(state)
    assert not result.get("policy_flags")


# ---------------------------------------------------------------------------
# gate_stripe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_stripe_passes_known_fingerprint() -> None:
    """gate_stripe should pass when the vendor fingerprint matches vendor_ledger."""
    parsed = _valid_parsed_invoice(vendor_bank_account="ACC-123456789")
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_stripe.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_stripe.StripeClient") as MockStripe:

        mock_vendor.return_value = {
            "vendor_id": "v-001",
            "name": "Acme Corp",
            "stripe_fingerprint": "ACC-123456789",  # Matches vendor_bank_account
        }

        mock_stripe_client = MagicMock()
        MockStripe.return_value = mock_stripe_client
        mock_stripe_client.get_radar_score.return_value = 10.0  # Low risk

        result = await gate_stripe(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "stripe"
    assert gate["passed"] is True
    assert gate["details"]["bec_check"] == "fingerprint match"
    assert gate["details"]["radar_score"] == 10.0


@pytest.mark.asyncio
async def test_gate_stripe_fails_fingerprint_changed() -> None:
    """gate_stripe should fail when the current fingerprint differs from vendor_ledger."""
    parsed = _valid_parsed_invoice(vendor_bank_account="ACC-NEWACCOUNT")
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_stripe.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_stripe.StripeClient") as MockStripe:

        mock_vendor.return_value = {
            "vendor_id": "v-001",
            "name": "Acme Corp",
            "stripe_fingerprint": "ACC-ORIGINAL99",  # Different from invoice
        }

        mock_stripe_client = MagicMock()
        MockStripe.return_value = mock_stripe_client
        mock_stripe_client.get_radar_score.return_value = 10.0  # Low radar, but BEC detected

        result = await gate_stripe(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["gate_name"] == "stripe"
    assert gate["passed"] is False
    assert "fingerprint mismatch" in gate["reason"]
    assert "BEC" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_stripe_fails_high_radar_score() -> None:
    """gate_stripe should fail when Radar score exceeds threshold (75)."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_stripe.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_stripe.StripeClient") as MockStripe:

        mock_vendor.return_value = {
            "vendor_id": "v-001",
            "name": "Acme Corp",
            "stripe_fingerprint": "ACC-123456789",  # Matches
        }

        mock_stripe_client = MagicMock()
        MockStripe.return_value = mock_stripe_client
        mock_stripe_client.get_radar_score.return_value = 85.0  # Above threshold

        result = await gate_stripe(state)

    assert result["gate_failed"] is True
    gate = result["gate_results"][0]
    assert gate["passed"] is False
    assert "Radar score" in gate["reason"]


@pytest.mark.asyncio
async def test_gate_stripe_passes_new_vendor() -> None:
    """gate_stripe should pass for a new vendor with no stored fingerprint."""
    parsed = _valid_parsed_invoice()
    state = _base_state(parsed_invoice=parsed)

    with patch("agent.nodes.gate_stripe.get_vendor_by_name") as mock_vendor, \
         patch("agent.nodes.gate_stripe.StripeClient") as MockStripe:

        mock_vendor.return_value = None  # New vendor

        mock_stripe_client = MagicMock()
        MockStripe.return_value = mock_stripe_client
        mock_stripe_client.get_radar_score.return_value = 5.0

        result = await gate_stripe(state)

    assert result["gate_failed"] is False
    gate = result["gate_results"][0]
    assert gate["passed"] is True
    assert gate["details"]["bec_check"] == "new vendor \u2014 no prior fingerprint to compare"
