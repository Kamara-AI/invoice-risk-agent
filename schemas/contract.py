"""Kagua API contract v1 — the schemas the UiPath bot depends on.

Source of truth: "TechByYou Invoice Bot — Technical Design v2", section
"Kagua API contract v1" (decisions D7, D12, D13).

Why a separate module from schemas/invoice.py:
    InvoiceInput/ParsedInvoice describe Kagua's *internal* pipeline and are also
    used by the Streamlit demo and the evals. The models here describe the
    *external* HTTP contract with the UiPath bot. Keeping them apart means the
    contract can stay frozen while internals evolve, and a contract change is a
    deliberate edit to this one file.

Design rules applied to every model:
    - extra="forbid" on requests: a typo in a field name from the Dispatcher
      fails loudly with 422 instead of being silently ignored.
    - Responses are flat (no nesting) so UiPath's Deserialize JSON gives the
      bot direct property access without nested lookups.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

RoutingDecisionValue = Literal["auto_approve", "human_review", "block"]
"""The only three routes the bot knows. The Performer's Switch has one case each."""

ReviewDecisionValue = Literal["approve", "reject"]

# Max length of the cleaned email body Kagua keeps (D12). The Dispatcher already
# trims to ~4,000 chars; Kagua truncates instead of rejecting, because a 422 here
# would be a Business Rule Exception (no retry) over a few extra characters.
EMAIL_BODY_MAX_CHARS = 4000

# Orchestrator queue item Reference is capped at 128 chars, and the key IS the
# Reference (D5), so the key can never be longer than that.
IDEMPOTENCY_KEY_MAX_CHARS = 128
IDEMPOTENCY_KEY_PATTERN = r"^INV-[A-Za-z0-9]+-\d+$"


# ---------------------------------------------------------------------------
# POST /invoices/process-invoice
# ---------------------------------------------------------------------------


class InvoiceMetadataV1(BaseModel):
    """The `invoice_metadata` multipart part sent by the Performer.

    idempotency_key format: "INV-" + short hash of the Gmail Message-ID + "-" +
    attachment index, e.g. "INV-9f2c1a7b-1". Built once per PDF by the
    Dispatcher, copied by Orchestrator onto every retry of the queue item, so
    Kagua can tell a retry apart from a genuine resend.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(
        ...,
        min_length=6,
        max_length=IDEMPOTENCY_KEY_MAX_CHARS,
        pattern=IDEMPOTENCY_KEY_PATTERN,
        description="Stable per-PDF key; also the Orchestrator queue item Reference.",
    )
    source_message_id: str = Field(
        ...,
        min_length=1,
        description="Message-ID header of the source email (not Gmail-specific, so the inbox can change).",
    )
    sender_email: EmailStr = Field(..., description="Envelope sender of the source email.")
    subject: str = Field(..., description="Subject line of the source email. May be empty.")
    received_at: datetime = Field(..., description="When the email arrived, ISO-8601 with offset (EAT).")
    pdf_filename: str = Field(..., min_length=1, description="Original attachment filename.")
    email_body: str = Field(
        default="",
        description=(
            "Cleaned email body (quotes/signatures removed), used as scoring context (D12). "
            "Untrusted input: never logged, only passed to the LLM inside delimiters."
        ),
    )

    @field_validator("email_body")
    @classmethod
    def _truncate_email_body(cls, value: str) -> str:
        """Truncate rather than reject an over-long body (see EMAIL_BODY_MAX_CHARS)."""
        return value[:EMAIL_BODY_MAX_CHARS]


class ProcessInvoiceResponse(BaseModel):
    """HTTP 200 body of POST /invoices/process-invoice. Flat on purpose.

    risk_score bands (Kagua owns them): 0–49 auto_approve, 50–89 human_review,
    90–100 block. The bot routes on routing_decision, never on the score, so a
    business-rule upgrade (e.g. the LLM recommends block at score 70) is safe.
    """

    invoice_id: str = Field(..., description="Kagua run id (UUID). Needed for the review-decision call.")
    routing_decision: RoutingDecisionValue
    risk_score: int = Field(..., ge=0, le=100)
    risk_flags: list[str] = Field(default_factory=list, description="Short machine-readable flags; may be empty.")
    risk_reasoning: str = Field(..., description="Human-readable explanation for the reviewer form.")
    replayed: bool = Field(
        ...,
        description="True when the key was seen before and the stored result is returned (a retry, not a duplicate).",
    )
    invoice_number: str | None = Field(default=None, description="Null when extraction failed.")
    vendor_name: str | None = Field(default=None, description="Null when extraction failed.")


# ---------------------------------------------------------------------------
# POST /invoices/{invoice_id}/review-decision   (D13)
# ---------------------------------------------------------------------------


class ReviewDecisionRequest(BaseModel):
    """Body sent by the Review Handler after Brian decides in Action Center."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(
        ...,
        max_length=IDEMPOTENCY_KEY_MAX_CHARS,
        pattern=IDEMPOTENCY_KEY_PATTERN,
        description="Must match the key the invoice was scored under — proves the caller owns this invoice.",
    )
    decision: ReviewDecisionValue
    reviewer: str = Field(..., min_length=1, max_length=320, description="Reviewer identity (email or username).")
    comment: str = Field(..., min_length=1, max_length=2000, description="Required reviewer comment.")
    decided_at: datetime = Field(..., description="When the reviewer decided, ISO-8601 with offset (EAT).")


class ReviewDecisionResponse(BaseModel):
    """HTTP 200 body of the review-decision endpoint."""

    invoice_id: str
    decision: ReviewDecisionValue
    status: Literal["approved", "rejected"]
    replayed: bool = Field(..., description="True when this exact decision was already recorded (a retry).")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ErrorCode = Literal[
    "invalid_request",          # 422 — request shape failed validation
    "invalid_metadata",         # 422 — invoice_metadata JSON/schema invalid
    "unreadable_pdf",           # 422 — not a PDF, empty, or no extractable text
    "not_an_invoice",           # 422 — readable PDF that is not an invoice (D12)
    "extraction_failed",        # 422 — looks like an invoice but fields could not be extracted
    "idempotency_conflict",     # 409 — key reused with a different PDF (Dispatcher bug)
    "processing_in_progress",   # 503 — same key is being scored right now; retry later
    "invoice_not_found",        # 404 — invoice_id/key pair unknown
    "decision_conflict",        # 409 — different decision already recorded, or invoice not in review
    "internal_error",           # 500 — Kagua failed; safe to retry
]


class ErrorResponse(BaseModel):
    """Flat error body for every non-200 response, so the bot can log error_code directly.

    The bot maps status codes, not error codes, to exception types:
    409/422 → Business Rule Exception (no retry); 5xx → System Exception (retry).
    """

    error_code: ErrorCode
    message: str


# ---------------------------------------------------------------------------
# Persistence model: one row in processing_requests (migration 004)
# ---------------------------------------------------------------------------


class ProcessingRecord(BaseModel):
    """Idempotency ledger row: one per idempotency_key.

    status lifecycle: (absent) → processing → completed.
    A 'processing' row is a reservation; it is released (deleted) if scoring
    fails, so the queue retry can score again.
    """

    idempotency_key: str
    pdf_sha256: str
    status: Literal["processing", "completed"]
    source_message_id: str | None = None
    invoice_id: str | None = None
    response: dict | None = None
    review_decision: ReviewDecisionValue | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
