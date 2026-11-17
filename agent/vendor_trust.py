"""Vendor trust policy — when Kagua changes vendor_ledger.trust_level.

Why this exists (2026-11-17): route_invoice used to set trust_level='flagged'
on the vendor NAMED on any blocked invoice. Two failures followed, both seen
live on Sava Supply Chain Ltd:

  1. Impersonation poisoned the real vendor. A lookalike-domain invoice in
     Sava's name was (correctly) blocked by the quality gate — and Sava itself
     was flagged. One spoofed email could degrade any supplier.
  2. Flagged never recovered. Only auto_approve restored 'trusted', but a
     flagged vendor's invoices are scored into human_review, so it could never
     auto-approve again. The state locked itself.

Policy:
  - Flag only when the block is evidence against the VENDOR, not the invoice:
      stripe — bank account differs from the stored fingerprint (BEC: the
               vendor's mailbox or identity may be compromised, so scrutinise
               all its invoices until a human confirms);
      ofac   — the vendor is a sanctions hit.
    quality (incl. lookalike sender), math and duplicate blocks condemn the
    invoice, which the block already stops. A score-only block (LLM >= 90)
    is a model opinion, not deterministic evidence, so it does not flag.
  - Only a human clears a flag: a review 'approve' on a flagged vendor's
    invoice restores 'trusted' (see api/routes/review_decision.py). An
    auto_approve never clears a flag.

Pure functions, no I/O: the callers own persistence and audit logging.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

TrustLevel = Literal["new", "trusted", "flagged"]

FLAGGED: TrustLevel = "flagged"
TRUSTED: TrustLevel = "trusted"

VENDOR_IMPLICATING_GATES: frozenset[str] = frozenset({"stripe", "ofac"})
"""Gates whose failure is evidence against the vendor itself, not just this invoice."""


def failed_gates(gate_results: Iterable[Mapping[str, object]]) -> list[str]:
    """Return the names of gates that failed, in run order.

    Args:
        gate_results: AgentState.gate_results — GateResult dicts.

    Returns:
        gate_name of every result with passed=False.
    """
    return [str(result.get("gate_name")) for result in gate_results if result.get("passed") is False]


def trust_after_routing(
    action: str,
    gate_results: Iterable[Mapping[str, object]],
    current_trust: str | None,
) -> TrustLevel | None:
    """Decide the vendor's trust level after Kagua routes one invoice.

    Args:
        action: The final routing decision (auto_approve / human_review / block).
        gate_results: The invoice's gate results.
        current_trust: The vendor's trust_level before this invoice, or None
            when the vendor is not in vendor_ledger yet.

    Returns:
        The trust level to write, or None to leave trust_level unchanged.
    """
    if action == "block":
        if VENDOR_IMPLICATING_GATES.intersection(failed_gates(gate_results)):
            return FLAGGED
        return None
    # An existing, unflagged vendor earns trust by auto-approving; a flag is
    # never cleared automatically (only by a human approve).
    if action == "auto_approve" and current_trust is not None and current_trust != FLAGGED:
        return TRUSTED
    return None


def trust_after_human_decision(decision: str, current_trust: str | None) -> TrustLevel | None:
    """Decide the vendor's trust level after a human review decision.

    Args:
        decision: 'approve' or 'reject' from the Review Handler.
        current_trust: The vendor's trust_level now, or None if unknown.

    Returns:
        TRUSTED when a human approves an invoice from a flagged vendor
        (the reviewer has verified it), otherwise None (no change).
    """
    if decision == "approve" and current_trust == FLAGGED:
        return TRUSTED
    return None
