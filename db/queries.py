"""Database query functions — vendor ledger, invoice history, and audit log.

All functions use the Supabase client singleton from db/client.py.
Each function has a single, clearly named responsibility — no multi-table
mutations in a single function. This keeps the query layer auditable and
each operation independently testable.

Error handling: callers (agent nodes) catch exceptions and set state.error.
These functions raise on DB errors rather than swallowing them.
"""

from __future__ import annotations

from db.client import supabase
from schemas.audit import AuditRecord


def get_vendor_by_name(vendor_name: str) -> dict | None:
    """Fetch a vendor record from vendor_ledger by exact name match.

    Used by gate_duplicate and llm_score to retrieve vendor history
    (trust_level, ofac_status, radar_score) before processing the invoice.

    Args:
        vendor_name: The vendor's legal name as extracted from the invoice.

    Returns:
        The vendor record dict if found, or None if this is a new vendor.

    Raises:
        Exception: On Supabase client errors.
    """
    pass


def upsert_vendor(vendor_data: dict) -> dict:
    """Insert or update a vendor record in vendor_ledger.

    Uses Supabase upsert on (name, email) to ensure idempotency.
    Called by the route node after each invoice is processed to update
    last_seen, trust_level, and any new fingerprint or OFAC status.

    Args:
        vendor_data: Dict matching the vendor_ledger schema. Must include 'name'.
                     Fields not provided are left unchanged on update.

    Returns:
        The upserted vendor record dict (with vendor_id populated).

    Raises:
        Exception: On Supabase client errors.
    """
    pass


def create_invoice_record(invoice_data: dict) -> dict:
    """Insert a new row into invoice_history.

    Called at the start of the run (before gates execute) to create the record
    with status='processing'. The record is updated via update_invoice_status
    as the pipeline progresses.

    Args:
        invoice_data: Dict matching the invoice_history schema. invoice_id must
                      be provided (pre-generated UUID from AgentState).

    Returns:
        The inserted invoice_history row dict.

    Raises:
        Exception: On Supabase client errors.
    """
    pass


def update_invoice_status(
    invoice_id: str,
    status: str,
    extra_fields: dict | None = None,
) -> dict:
    """Update the status and optional additional fields on an invoice_history row.

    Args:
        invoice_id: UUID of the invoice_history row to update.
        status: New status value. Must satisfy the DB CHECK constraint:
                one of 'processing', 'approved', 'rejected', 'blocked', 'error'.
        extra_fields: Optional additional columns to update in the same call
                      (e.g. routing_decision, resolved_by, resolved_at).

    Returns:
        The updated invoice_history row dict.

    Raises:
        Exception: On Supabase client errors.
    """
    pass


def write_audit_log(record: AuditRecord) -> AuditRecord:
    """Append an immutable audit event to the audit_log table.

    This function is the only place in the codebase that writes to audit_log.
    Centralising writes here ensures the no-update rule is enforced consistently.

    Args:
        record: AuditRecord instance to persist. log_id may be None — it will
                be populated from the DB response and returned.

    Returns:
        The AuditRecord with log_id populated from the Supabase insert response.

    Raises:
        Exception: On Supabase client errors.
    """
    pass
