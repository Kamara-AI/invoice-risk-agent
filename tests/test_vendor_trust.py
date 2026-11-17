"""Vendor trust policy (agent/vendor_trust.py) — pure-function tests.

Regression for 2026-11-17: an impostor (lookalike-sender) block flagged the real
vendor Sava Supply Chain Ltd, and nothing could ever un-flag it.
"""

from __future__ import annotations

import pytest

from agent.vendor_trust import failed_gates, trust_after_human_decision, trust_after_routing


def _gates(*failed: str) -> list[dict]:
    """All five gates in run order; the named ones failed."""
    names = ("quality", "math", "duplicate", "ofac", "stripe")
    return [{"gate_name": name, "passed": name not in failed} for name in names]


def test_failed_gates_lists_only_failures_in_order() -> None:
    assert failed_gates(_gates("math", "stripe")) == ["math", "stripe"]
    assert failed_gates([]) == []


@pytest.mark.parametrize("gate", ["stripe", "ofac"])
def test_vendor_implicating_block_flags(gate: str) -> None:
    assert trust_after_routing("block", _gates(gate), "trusted") == "flagged"
    assert trust_after_routing("block", _gates(gate), None) == "flagged"


@pytest.mark.parametrize("gate", ["quality", "math", "duplicate"])
def test_invoice_level_block_does_not_flag_vendor(gate: str) -> None:
    """A lookalike sender fails the quality gate: the impostor is blocked, the real vendor is untouched."""
    assert trust_after_routing("block", _gates(gate), "trusted") is None


def test_score_only_block_does_not_flag_vendor() -> None:
    assert trust_after_routing("block", _gates(), "trusted") is None


def test_auto_approve_trusts_known_unflagged_vendor() -> None:
    assert trust_after_routing("auto_approve", _gates(), "new") == "trusted"
    assert trust_after_routing("auto_approve", _gates(), "trusted") == "trusted"


def test_auto_approve_never_clears_a_flag() -> None:
    assert trust_after_routing("auto_approve", _gates(), "flagged") is None


def test_auto_approve_of_unknown_vendor_leaves_default() -> None:
    assert trust_after_routing("auto_approve", _gates(), None) is None


def test_human_review_changes_nothing() -> None:
    assert trust_after_routing("human_review", _gates(), "flagged") is None
    assert trust_after_routing("human_review", _gates(), "trusted") is None


def test_human_approve_restores_flagged_vendor() -> None:
    assert trust_after_human_decision("approve", "flagged") == "trusted"


@pytest.mark.parametrize(("decision", "current"), [("reject", "flagged"), ("approve", "trusted"),
                                                   ("approve", "new"), ("approve", None)])
def test_human_decision_otherwise_changes_nothing(decision: str, current: str | None) -> None:
    assert trust_after_human_decision(decision, current) is None
