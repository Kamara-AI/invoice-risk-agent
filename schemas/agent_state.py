"""Agent state schema for the Invoice Risk Intelligence Agent.

AgentState is the single source of truth passed between every LangGraph node.
Each node receives the full state, mutates only its own fields, and returns
the updated state. This pattern keeps every step independently debuggable.
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict):
    """Full mutable state for one invoice processing run.

    Fields progress through the pipeline in order:
    ingest → parse → gates (×5) → llm_score → route → persist.
    A node must never clear a field set by a prior node unless it is
    explicitly correcting an error — all history must be preserved for audit.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    invoice_id: str
    """Unique run identifier (UUID4). Generated at ingest before any node runs."""

    # ------------------------------------------------------------------
    # Raw input
    # ------------------------------------------------------------------
    raw_pdf_bytes: bytes | None
    """Raw bytes of the attached PDF invoice. Cleared after parse_invoice
    to avoid carrying large payloads through the rest of the graph."""

    gmail_message_id: str | None
    """The Gmail message ID that carried this invoice. Used to apply
    labels ('processed', 'flagged') back to the source message."""

    # ------------------------------------------------------------------
    # Parsed invoice
    # ------------------------------------------------------------------
    parsed_invoice: dict | None
    """Serialised ParsedInvoice model (see schemas/invoice.py).
    Populated by the parse_invoice node; all downstream nodes read from here."""

    # ------------------------------------------------------------------
    # Gate tracking
    # ------------------------------------------------------------------
    gate_results: list[dict]
    """Ordered list of GateResult dicts, one per completed gate.
    Appended to (never replaced) so the full gate history is always available."""

    current_gate: str | None
    """Name of the gate currently executing. Cleared when the gate exits."""

    gate_failed: bool
    """Set to True by any gate node that fails validation.
    Signals the conditional edge to short-circuit to the routing node."""

    gate_failure_reason: str | None
    """Human-readable explanation of why the failing gate rejected this invoice.
    Populated alongside gate_failed=True."""

    # ------------------------------------------------------------------
    # LLM risk scoring
    # ------------------------------------------------------------------
    risk_score: dict | None
    """Serialised RiskScore model (see schemas/risk.py).
    Populated by the llm_score node after all gates have run."""

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    routing_decision: str | None
    """One of: 'auto_approve' | 'human_review' | 'block'.
    Set by the route node based on risk_score and gate results."""

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------
    slack_message_ts: str | None
    """Timestamp of the Slack message posted for human review.
    Used to update the message once a reviewer responds."""

    # ------------------------------------------------------------------
    # Human decision
    # ------------------------------------------------------------------
    human_decision: str | None
    """Decision recorded from the human reviewer via Slack interactive button.
    One of: 'approve' | 'reject'. Only populated for human_review cases."""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    audit_record_id: str | None
    """The log_id of the audit_log row written for this run.
    Confirms that the event was durably persisted to Supabase."""

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    error: str | None
    """Unhandled exception message from any node. The graph routes to a
    dead-letter path when this is non-None, triggering a Slack alert."""

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    created_at: str
    """ISO-8601 timestamp (EAT / UTC+3) at which this run was initialised."""
