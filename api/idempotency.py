"""Idempotency policy — decides what to do with a request given the ledger row.

Pure function, no I/O: the route fetches the row, this module decides, the
route acts. Keeping the decision pure makes every case in the design doc's
"How Kagua decides" table a one-line unit test.

    Case                                   Ledger row              Action
    -------------------------------------  ----------------------  -----------
    First time                             none                    FRESH
    Bot retry after timeout, same PDF      completed, same hash    REPLAY
    Key reused with a different PDF        any, different hash     CONFLICT
    Retry while first attempt still runs   processing, recent      IN_PROGRESS
    First attempt crashed mid-run          processing, stale       TAKE_OVER

A vendor resending the invoice in a NEW email gets a new key, so it is FRESH
here and the duplicate gate blocks it downstream — exactly as designed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from schemas.contract import ProcessingRecord

# A reservation older than this is assumed abandoned (process crash, server
# restart). Must comfortably exceed the slowest real graph run; the bot's own
# timeout is 120 s, so 10 minutes leaves a wide margin.
STALE_RESERVATION_AFTER = timedelta(minutes=10)


class ReplayAction(str, Enum):
    """What the route should do with an incoming process-invoice request."""

    FRESH = "fresh"
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_PROGRESS = "in_progress"
    TAKE_OVER = "take_over"


def decide_replay_action(
    existing: ProcessingRecord | None,
    pdf_sha256: str,
    now: datetime,
    stale_after: timedelta = STALE_RESERVATION_AFTER,
) -> ReplayAction:
    """Classify a request against the idempotency ledger.

    Args:
        existing: The ledger row for this key, or None if never seen.
        pdf_sha256: SHA-256 hex digest of the PDF in this request.
        now: Current time (timezone-aware). Injected so tests control the clock.
        stale_after: Age after which a 'processing' reservation is abandoned.

    Returns:
        The action the route must take.
    """
    if existing is None:
        return ReplayAction.FRESH

    # Hash check comes first: a different file under a reused key is a
    # Dispatcher bug, whatever state the original run is in.
    if existing.pdf_sha256 != pdf_sha256:
        return ReplayAction.CONFLICT

    if existing.status == "completed":
        return ReplayAction.REPLAY

    if now - existing.updated_at > stale_after:
        return ReplayAction.TAKE_OVER

    return ReplayAction.IN_PROGRESS
