"""Policy flags — deterministic findings that are not gate failures.

Why this exists (2026-11-16): gates could only pass or BLOCK. Some findings
deserve neither: a sender address that differs from the invoice's vendor
email is usually legitimate (personal Gmail, Xero/QuickBooks mailers) but
must not be auto-approved unseen; a sanctions screen that could not run is
not a sanctions hit, but approving without it is a silent failure.

A gate records such a finding with add_policy_flag(). Two effects:
  1. route_invoice upgrades auto_approve → human_review when any flag in
     FORCE_REVIEW_FLAGS is present (never downgrades a block).
  2. The contract response appends every policy flag to risk_flags, so the
     UiPath bot and the reviewer see exactly why.
"""

from __future__ import annotations

from collections.abc import MutableMapping

SENDER_DOMAIN_MISMATCH = "sender_domain_mismatch"
"""Sender's domain differs from the invoice's vendor email and is not a lookalike."""

SANCTIONS_NOT_SCREENED = "sanctions_not_screened"
"""OFAC screening is switched off (settings.ofac_enabled = False). Informational."""

SANCTIONS_SCREENING_FAILED = "sanctions_screening_failed"
"""OFAC screening is on but the provider call failed. Forces review (decision #8)."""

FORCE_REVIEW_FLAGS: frozenset[str] = frozenset({SENDER_DOMAIN_MISMATCH, SANCTIONS_SCREENING_FAILED})


def add_policy_flag(state: MutableMapping, flag: str) -> None:
    """Append a policy flag to the state once, preserving order.

    Args:
        state: The AgentState (dict-like) being processed.
        flag: One of the constants above.
    """
    flags = list(state.get("policy_flags") or [])
    if flag not in flags:
        flags.append(flag)
    state["policy_flags"] = flags


def requires_review(policy_flags: list[str] | None) -> list[str]:
    """Return the flags (in order) that force at least human_review."""
    return [flag for flag in (policy_flags or []) if flag in FORCE_REVIEW_FLAGS]
