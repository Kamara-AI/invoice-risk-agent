"""Idempotency ledger queries — the processing_requests table (migration 004).

Each function does exactly one database operation so the HTTP layer reads as a
sequence of named steps, and each step can be mocked independently in tests.

Error handling: functions raise on database errors (the route turns that into
a 500, which the bot treats as a System Exception and retries). The one
expected failure — inserting a key that already exists — is returned as False
instead of raised, because it is a normal outcome under concurrent retries.
"""

from __future__ import annotations

from postgrest.exceptions import APIError

from db.client import supabase
from schemas.contract import ProcessingRecord
from utils import now_eat

_TABLE = "processing_requests"

# Postgres SQLSTATE for unique_violation — another request reserved the key first.
_UNIQUE_VIOLATION = "23505"


def get_processing_record(idempotency_key: str) -> ProcessingRecord | None:
    """Fetch the ledger row for a key.

    Args:
        idempotency_key: The key built by the UiPath Dispatcher.

    Returns:
        The validated row, or None if the key has never been seen.
    """
    response = supabase.table(_TABLE).select("*").eq("idempotency_key", idempotency_key).execute()
    return ProcessingRecord(**response.data[0]) if response.data else None


def reserve_processing_record(idempotency_key: str, pdf_sha256: str, source_message_id: str) -> bool:
    """Insert a 'processing' reservation before the graph runs.

    The primary key makes this the race arbiter: of two concurrent requests
    with the same key, exactly one insert succeeds.

    Returns:
        True if this request now owns the key; False if another request does.
    """
    now = now_eat()
    try:
        supabase.table(_TABLE).insert(
            {
                "idempotency_key": idempotency_key,
                "pdf_sha256": pdf_sha256,
                "status": "processing",
                "source_message_id": source_message_id,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
    except APIError as exc:
        if exc.code == _UNIQUE_VIOLATION:
            return False
        raise
    return True


def take_over_stale_record(idempotency_key: str, stale_before_iso: str) -> bool:
    """Claim a 'processing' reservation whose owner apparently died.

    Conditional update: only succeeds if the row is still 'processing' and was
    last touched before the cutoff, so two takeovers cannot both win.

    Returns:
        True if this request now owns the key.
    """
    response = (
        supabase.table(_TABLE)
        .update({"updated_at": now_eat()})
        .eq("idempotency_key", idempotency_key)
        .eq("status", "processing")
        .lt("updated_at", stale_before_iso)
        .execute()
    )
    return bool(response.data)


def complete_processing_record(idempotency_key: str, invoice_id: str, response_body: dict) -> None:
    """Mark the key completed and store the exact response for future replays."""
    supabase.table(_TABLE).update(
        {
            "status": "completed",
            "invoice_id": invoice_id,
            "response": response_body,
            "updated_at": now_eat(),
        }
    ).eq("idempotency_key", idempotency_key).execute()


def release_processing_record(idempotency_key: str) -> None:
    """Delete a 'processing' reservation after a failed run so a retry can score again.

    Never deletes a 'completed' row: a completed result must stay replayable.
    """
    (
        supabase.table(_TABLE)
        .delete()
        .eq("idempotency_key", idempotency_key)
        .eq("status", "processing")
        .execute()
    )


def record_review_decision(idempotency_key: str, decision: str, reviewer: str, reviewed_at_iso: str) -> None:
    """Store the human review outcome once (D13). Written last, so it doubles as the 'done' marker."""
    supabase.table(_TABLE).update(
        {
            "review_decision": decision,
            "reviewed_by": reviewer,
            "reviewed_at": reviewed_at_iso,
            "updated_at": now_eat(),
        }
    ).eq("idempotency_key", idempotency_key).execute()
