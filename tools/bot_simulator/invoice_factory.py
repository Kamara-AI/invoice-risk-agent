"""Fresh synthetic invoices for live simulator runs and the UiPath demo.

Why this exists (found 2026-11-16): the static eval fixtures were scored in
September, so their invoice numbers are already in invoice_history. Sending
clean_001.pdf again trips gate_duplicate before any other gate or the LLM
runs — the live test "passes" without exercising the scoring path, and the
demo's "approved" invoice gets blocked.

Each builder therefore takes a run tag and produces an invoice that is new to
the database on BOTH duplicate checks in gate_duplicate:
  1. invoice_number — contains the run tag;
  2. total + vendor + date within 7 days — one unit price varies with the tag,
     so two runs on the same day do not share a total.

Vendor choice is deliberate:
  - clean  → "Sava Supply Chain Ltd": trust_level 'trusted' in vendor_ledger,
    stored bank fingerprint SWIFT:KCBLKENX:1234567890 (must match, or
    gate_stripe flags a BEC swap). An auto_approve keeps it 'trusted'.
  - review → a vendor name unique to the run, so it is always a NEW vendor.
    Signals stack the way labeled case edge_001 does (new vendor, high value,
    no PO, stale date). Each live run adds one test vendor row to vendor_ledger.

LLM scoring is not deterministic: the review invoice is designed to land in
human_review (score 50-89), and the simulator reports the actual routing if
it does not, rather than assuming it.

PDFs are built with pdf_factory (no third-party PDF library in Kagua's runtime).
They carry no "synthetic" footer (see render_invoice_pdf); test rows are
identified by their sim-/demo- Message-IDs.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from pydantic import BaseModel, Field

from tools.bot_simulator.pdf_factory import make_text_pdf

TAX_RATE = 0.16  # Kenyan VAT; only used to make the totals look realistic

CLEAN_VENDOR = {
    "name": "Sava Supply Chain Ltd",
    "email": "finance@savasupply.co.ke",
    "bank_account": "SWIFT:KCBLKENX:1234567890",
}


class InvoiceLine(BaseModel):
    """One line item; line_total is always quantity x unit_price (math gate passes)."""

    description: str = Field(..., max_length=45)
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class InvoiceSpec(BaseModel):
    """Everything printed on a synthetic invoice."""

    invoice_number: str
    vendor_name: str
    vendor_email: str
    vendor_bank_account: str
    invoice_date: date
    due_date: date
    purchase_order_ref: str | None
    currency: str = "USD"
    lines: list[InvoiceLine] = Field(..., min_length=1)

    @property
    def subtotal(self) -> float:
        return round(sum(line.line_total for line in self.lines), 2)

    @property
    def tax(self) -> float:
        return round(self.subtotal * TAX_RATE, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax, 2)


def _tag_number(run_tag: str) -> int:
    """Stable 0-9999 number from any run tag (hex or not), for amount variation."""
    return int(hashlib.sha256(run_tag.encode("utf-8")).hexdigest()[:8], 16) % 10_000


def _short_tag(run_tag: str) -> str:
    """4 uppercase hex chars derived from the tag — readable in invoice numbers and names."""
    return hashlib.sha256(run_tag.encode("utf-8")).hexdigest()[:4].upper()


def fresh_clean_invoice(run_tag: str, today: date) -> InvoiceSpec:
    """A trusted-vendor invoice that should auto_approve.

    Args:
        run_tag: Unique per run (the simulator/dispatcher run_id).
        today: The scoring date in EAT; the invoice is dated today.

    Returns:
        The invoice spec; render it with render_invoice_pdf.
    """
    variation = _tag_number(run_tag)
    return InvoiceSpec(
        invoice_number=f"SAVA-{today:%Y%m%d}-{_short_tag(run_tag)}",
        vendor_name=CLEAN_VENDOR["name"],
        vendor_email=CLEAN_VENDOR["email"],
        vendor_bank_account=CLEAN_VENDOR["bank_account"],
        invoice_date=today,
        due_date=today + timedelta(days=30),
        purchase_order_ref=f"PO-{today:%Y}-7{variation % 1000:03d}",
        lines=[
            InvoiceLine(description="Logistics Management Software (monthly)", quantity=1, unit_price=350.00),
            # The tag moves this price by up to 99.99, so the total differs run to run.
            InvoiceLine(description="API Integration Support (hours)", quantity=6,
                        unit_price=round(150 + variation / 100, 2)),
            InvoiceLine(description="Warehouse Barcode Labels (rolls)", quantity=20, unit_price=12.50),
        ],
    )


def fresh_review_invoice(run_tag: str, today: date) -> InvoiceSpec:
    """A new-vendor invoice with stacked soft risk signals, aimed at human_review.

    Mirrors labeled case edge_001: first invoice from an unknown vendor,
    high value, no PO, dated 45 days ago. None of these alone fails a gate.

    Args:
        run_tag: Unique per run; becomes part of the vendor name so the vendor is always new.
        today: The scoring date in EAT.

    Returns:
        The invoice spec; render it with render_invoice_pdf.
    """
    tag = _short_tag(run_tag)
    invoice_date = today - timedelta(days=45)
    return InvoiceSpec(
        invoice_number=f"KP-{tag}-0001",
        vendor_name=f"Kestrel {tag} Procurement Ltd",
        vendor_email=f"accounts@kestrel{tag.lower()}.co.ke",
        vendor_bank_account=f"SWIFT:EQBLKENA:55{_tag_number(run_tag):04d}8812",
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=14),
        purchase_order_ref=None,
        lines=[
            InvoiceLine(description="Strategic Sourcing Advisory (Q4)", quantity=1, unit_price=48000.00),
            InvoiceLine(description="Supplier Onboarding Programme", quantity=1, unit_price=14500.00),
        ],
    )


def render_invoice_pdf(spec: InvoiceSpec) -> bytes:
    """Render the spec as a one-page text PDF that parse_invoice can extract.

    Args:
        spec: The invoice to print.

    Returns:
        PDF bytes starting with "%PDF-1.4".
    """
    lines = [
        "INVOICE",
        "",
        spec.vendor_name,
        spec.vendor_email,
        f"Bank Account: {spec.vendor_bank_account}",
        "",
        f"Invoice Number: {spec.invoice_number}",
        f"Invoice Date: {spec.invoice_date.isoformat()}",
        f"Due Date: {spec.due_date.isoformat()}",
    ]
    if spec.purchase_order_ref:
        lines.append(f"PO Reference: {spec.purchase_order_ref}")
    lines += ["", f"Description | Qty | Unit Price ({spec.currency}) | Total ({spec.currency})"]
    lines += [
        f"{line.description} | {line.quantity} | {line.unit_price:,.2f} | {line.line_total:,.2f}"
        for line in spec.lines
    ]
    lines += [
        "",
        f"Subtotal: {spec.subtotal:,.2f}",
        f"Tax (16% VAT): {spec.tax:,.2f}",
        f"TOTAL ({spec.currency}): {spec.total:,.2f}",
    ]
    # No "synthetic / not a real invoice" footer: the LLM reads every word, and
    # that line can trip the not_an_invoice classifier or inflate the risk score.
    # Test rows stay traceable through their sim-/demo- Message-IDs instead.
    return make_text_pdf(lines)
