"""Tests for tools/bot_simulator/invoice_factory.py (offline, no DB, no LLM).

These pin the properties the live simulator and the UiPath demo rely on:
every run's invoices must be new to BOTH gate_duplicate checks (invoice number,
and total + vendor + date), must pass gate_math and gate_quality, and the
clean vendor must match its stored bank fingerprint (else gate_stripe flags BEC).

Run with:
    pytest tests/test_invoice_factory.py -v
"""

from __future__ import annotations

from datetime import date

import pytest

from tools.bot_simulator.invoice_factory import (
    CLEAN_VENDOR,
    fresh_clean_invoice,
    fresh_review_invoice,
    render_invoice_pdf,
)

TODAY = date(2026, 11, 16)
BUILDERS = [fresh_clean_invoice, fresh_review_invoice]


@pytest.mark.parametrize("build", BUILDERS)
def test_renders_a_pdf_containing_the_key_fields(build) -> None:
    spec = build("20261116232700a3f9", TODAY)
    pdf = render_invoice_pdf(spec)
    assert pdf.startswith(b"%PDF-1.4")
    for text in (spec.invoice_number, spec.vendor_name, spec.vendor_email, f"{spec.total:,.2f}"):
        assert text.encode("latin-1") in pdf


@pytest.mark.parametrize("build", BUILDERS)
def test_totals_are_internally_consistent(build) -> None:
    """gate_math recomputes qty x unit_price and the sums; they must agree."""
    spec = build("runA", TODAY)
    assert spec.subtotal == round(sum(line.quantity * line.unit_price for line in spec.lines), 2)
    assert spec.total == round(spec.subtotal + spec.tax, 2)


@pytest.mark.parametrize("build", BUILDERS)
def test_two_runs_differ_on_both_duplicate_checks(build) -> None:
    first, second = build("run1", TODAY), build("run2", TODAY)
    assert first.invoice_number != second.invoice_number
    assert first.total != second.total or first.vendor_name != second.vendor_name


@pytest.mark.parametrize("build", BUILDERS)
def test_same_tag_is_deterministic(build) -> None:
    assert build("same", TODAY) == build("same", TODAY)


@pytest.mark.parametrize("build", BUILDERS)
def test_dates_pass_the_quality_gate(build) -> None:
    spec = build("x", TODAY)
    assert spec.invoice_date <= TODAY
    assert spec.due_date >= spec.invoice_date


def test_clean_invoice_uses_the_trusted_vendor_fingerprint() -> None:
    spec = fresh_clean_invoice("x", TODAY)
    assert (spec.vendor_name, spec.vendor_email, spec.vendor_bank_account) == (
        CLEAN_VENDOR["name"], CLEAN_VENDOR["email"], CLEAN_VENDOR["bank_account"],
    )
    assert spec.invoice_date == TODAY and spec.purchase_order_ref


def test_review_invoice_stacks_soft_signals_on_a_new_vendor() -> None:
    spec = fresh_review_invoice("x", TODAY)
    assert spec.purchase_order_ref is None
    assert (TODAY - spec.invoice_date).days == 45
    assert spec.total > 50_000
    assert fresh_review_invoice("y", TODAY).vendor_name != spec.vendor_name
