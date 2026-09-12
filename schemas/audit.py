"""Audit log schema.

Every significant state transition in the agent writes an AuditRecord to
the audit_log table in Supabase. This creates a durable, ordered event log
for compliance, debugging, and post-incident analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuditRecord(BaseModel):
    """A single immutable audit event.

    Records are written by db/queries.py:write_audit_log and never updated.
    If a correction is needed, a new record with event_type='correction' is
    appended — the original record is preserved.
    """

    log_id: str | None = Field(
        default=None,
        description=(
            "UUID assigned by Supabase on insert (gen_random_uuid()). "
            "None before the record is persisted; populated on return."
        ),
    )
    invoice_id: str = Field(
        ...,
        description="The invoice run ID this event belongs to.",
    )
    event_type: str = Field(
        ...,
        description=(
            "Short, dot-namespaced event identifier. "
            "Examples: 'gate.ofac.fail', 'route.block', 'human.approve', 'error.unhandled'."
        ),
    )
    actor: str = Field(
        ...,
        description=(
            "Who or what triggered this event. "
            "One of: 'system', 'llm', or the Slack user ID of a human reviewer."
        ),
    )
    details: dict = Field(
        default_factory=dict,
        description="Arbitrary structured payload for this event (gate output, LLM response, etc.).",
    )
    created_at: str = Field(
        ...,
        description="ISO-8601 timestamp (EAT / UTC+3) at which this event occurred.",
    )
