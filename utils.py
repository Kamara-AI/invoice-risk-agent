"""Shared utility functions used across agent nodes and integrations.

Kept small and import-free (stdlib only) so any module can import without
risk of circular dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# East Africa Time — UTC+3, no DST.
EAT = timezone(timedelta(hours=3))


def now_eat() -> str:
    """Return the current EAT timestamp as an ISO-8601 string.

    Used to stamp GateResult.checked_at and AuditRecord.created_at so all
    timestamps in the system are consistently in the same timezone regardless
    of server TZ configuration.

    Returns:
        Current datetime in EAT (UTC+3) formatted as ISO-8601 with timezone offset.
    """
    return datetime.now(EAT).isoformat()
