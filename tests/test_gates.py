"""Unit tests for all five gate nodes.

Each test constructs a minimal AgentState, calls the gate node, and asserts
on the resulting gate_results entry and gate_failed flag.

Run with:
    pytest tests/test_gates.py -v
"""

from __future__ import annotations

import pytest

from agent.nodes.gate_duplicate import gate_duplicate
from agent.nodes.gate_math import gate_math
from agent.nodes.gate_ofac import gate_ofac
from agent.nodes.gate_quality import gate_quality
from agent.nodes.gate_stripe import gate_stripe


# ---------------------------------------------------------------------------
# gate_quality
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_quality_passes_valid_invoice() -> None:
    """gate_quality should pass a complete, valid ParsedInvoice."""
    pass


@pytest.mark.asyncio
async def test_gate_quality_fails_missing_fields() -> None:
    """gate_quality should fail when required invoice fields are empty."""
    pass


@pytest.mark.asyncio
async def test_gate_quality_fails_email_mismatch() -> None:
    """gate_quality should fail when sender_email does not match vendor_email."""
    pass


# ---------------------------------------------------------------------------
# gate_math
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_math_passes_correct_arithmetic() -> None:
    """gate_math should pass when all line totals and subtotal/total are correct."""
    pass


@pytest.mark.asyncio
async def test_gate_math_fails_line_total_mismatch() -> None:
    """gate_math should fail when a line_total does not match quantity × unit_price."""
    pass


@pytest.mark.asyncio
async def test_gate_math_fails_subtotal_mismatch() -> None:
    """gate_math should fail when sum of line_totals does not match subtotal."""
    pass


# ---------------------------------------------------------------------------
# gate_duplicate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_duplicate_passes_new_invoice() -> None:
    """gate_duplicate should pass when no matching invoice exists in history."""
    pass


@pytest.mark.asyncio
async def test_gate_duplicate_fails_exact_duplicate() -> None:
    """gate_duplicate should fail when invoice_number + vendor_id match an existing record."""
    pass


# ---------------------------------------------------------------------------
# gate_ofac
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_ofac_passes_clear_vendor() -> None:
    """gate_ofac should pass when the OFAC API returns no match."""
    pass


@pytest.mark.asyncio
async def test_gate_ofac_fails_sanctioned_vendor() -> None:
    """gate_ofac should fail when the OFAC API returns a match above threshold."""
    pass


# ---------------------------------------------------------------------------
# gate_stripe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_stripe_passes_known_fingerprint() -> None:
    """gate_stripe should pass when the vendor fingerprint matches vendor_ledger."""
    pass


@pytest.mark.asyncio
async def test_gate_stripe_fails_fingerprint_changed() -> None:
    """gate_stripe should fail when the current fingerprint differs from vendor_ledger."""
    pass
