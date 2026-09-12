"""Invoice input and parsed output schemas.

All models are Pydantic v2. Define these before writing any parsing logic —
the parser's job is to produce a valid ParsedInvoice or raise a validation error.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class LineItem(BaseModel):
    """A single line on the invoice.

    line_total must match quantity × unit_price within a small epsilon.
    Gate gate_math enforces this; the schema itself stores what was parsed.
    """

    description: str = Field(..., description="Text description of the good or service.")
    quantity: float = Field(..., gt=0, description="Number of units billed.")
    unit_price: float = Field(..., ge=0, description="Price per unit in invoice currency.")
    line_total: float = Field(..., ge=0, description="Declared total for this line item.")


class InvoiceInput(BaseModel):
    """Raw metadata extracted from the Gmail message before PDF parsing.

    This is the entry point into the agent. The parse_invoice node receives
    this alongside raw_pdf_bytes and produces a ParsedInvoice.
    """

    gmail_message_id: str = Field(..., description="Gmail message ID for traceability and labelling.")
    sender_email: EmailStr = Field(..., description="Envelope sender of the Gmail message.")
    subject: str = Field(..., description="Subject line of the Gmail message.")
    received_at: datetime = Field(..., description="When the message arrived in the inbox (UTC).")
    pdf_filename: str = Field(..., description="Filename of the PDF attachment being processed.")


class ParsedInvoice(BaseModel):
    """Structured invoice data extracted from the PDF attachment.

    Produced by the parse_invoice node. All downstream gate and scoring
    nodes consume this model — never the raw PDF bytes.
    """

    invoice_number: str = Field(..., description="Unique invoice identifier as printed on the document.")
    vendor_name: str = Field(..., description="Legal name of the invoicing vendor.")
    vendor_email: EmailStr = Field(..., description="Vendor contact email as printed on the invoice.")
    vendor_bank_account: str | None = Field(
        default=None,
        description="Bank account or routing details if present. Used by gate_stripe for BEC detection.",
    )
    line_items: list[LineItem] = Field(..., min_length=1, description="All line items on the invoice.")
    subtotal: float = Field(..., ge=0, description="Sum of all line totals before tax.")
    tax: float = Field(..., ge=0, description="Tax amount applied to the subtotal.")
    total: float = Field(..., ge=0, description="Final amount due (subtotal + tax).")
    currency: str = Field(default="USD", description="ISO 4217 currency code.")
    invoice_date: date = Field(..., description="Date the invoice was issued.")
    due_date: date = Field(..., description="Payment due date.")
    purchase_order_ref: str | None = Field(
        default=None,
        description="PO number cross-referencing the buyer's procurement system, if present.",
    )
