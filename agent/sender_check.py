"""Sender-vs-vendor email comparison (pure, no I/O) — used by gate_quality.

Decision (Brian, 2026-11-16), tiered:
  match     → same address, or same company domain (incl. subdomains)    → pass
  lookalike → vendor's company domain with 1-2 characters changed        → BLOCK
              (classic BEC: apexoffice.com vs apex0ffice.com)
  mismatch  → anything else                                               → human review

Why not "any mismatch blocks": Kenyan SME vendors often send from a personal
Gmail while the invoice prints a company address, and accounting tools
(Xero, QuickBooks) send from their own domains. Blocking those would reject
legitimate invoices; forcing review keeps a human in the loop instead.

Free-mail domains (gmail.com, yahoo.com, ...) identify nobody: two different
Gmail users share the domain. When either side is free mail, only the exact
address counts as a match, and lookalike detection is skipped (gmial.com vs
gmail.com says nothing about which vendor sent it).
"""

from __future__ import annotations

from typing import Literal

SenderVerdict = Literal["match", "lookalike", "mismatch"]

LOOKALIKE_MAX_EDITS = 2
LOOKALIKE_MIN_LENGTH = 6  # very short domains are too close to everything to judge

FREE_MAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
    "aol.com", "proton.me", "protonmail.com", "zoho.com", "gmx.com", "mail.com",
})


def _normalise(address: str) -> str:
    return address.strip().strip("<>").lower()


def _domain(address: str) -> str:
    return address.rpartition("@")[2]


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insert/delete/substitute), small strings only."""
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def classify_sender(sender_email: str, vendor_email: str) -> SenderVerdict:
    """Compare the email envelope sender with the vendor email printed on the invoice.

    Args:
        sender_email: Envelope sender of the source email.
        vendor_email: Vendor contact email extracted from the invoice.

    Returns:
        "match", "lookalike" or "mismatch" (see module docstring for the policy).
    """
    sender, vendor = _normalise(sender_email), _normalise(vendor_email)
    if sender == vendor:
        return "match"

    sender_domain, vendor_domain = _domain(sender), _domain(vendor)
    if sender_domain in FREE_MAIL_DOMAINS or vendor_domain in FREE_MAIL_DOMAINS:
        return "mismatch"

    if sender_domain == vendor_domain or sender_domain.endswith("." + vendor_domain):
        return "match"

    if (
        min(len(sender_domain), len(vendor_domain)) >= LOOKALIKE_MIN_LENGTH
        and _edit_distance(sender_domain, vendor_domain) <= LOOKALIKE_MAX_EDITS
    ):
        return "lookalike"
    return "mismatch"
