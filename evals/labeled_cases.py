"""Labeled evaluation cases for the invoice risk agent.

12 cases across 3 categories:
- Clean (5): legitimate invoices that should auto-approve or pass cleanly.
- Fraudulent (4): invoices with clear fraud signals targeting specific gates.
- Edge (3): ambiguous cases that test threshold behaviour and human routing.

Each case is a dict with:
- id: Unique case identifier matching the fixture PDF filename.
- description: What this case is testing.
- fraud_type: The fraud pattern being simulated (None for clean cases).
- expected_gate_fail: Which gate should catch this case (None if all gates pass).
- expected_score_range: Tuple (min, max) for the expected LLM risk score.
- expected_routing: One of 'auto_approve', 'human_review', 'block'.
"""

from __future__ import annotations

LABELED_CASES: list[dict] = [
    # ------------------------------------------------------------------
    # Clean cases — all gates should pass, score should be low
    # ------------------------------------------------------------------
    {
        "id": "clean_001",
        "description": "Repeat trusted vendor, correct math, known bank account, clear OFAC.",
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (0, 25),
        "expected_routing": "auto_approve",
    },
    {
        "id": "clean_002",
        "description": "New vendor, first invoice, all fields complete, PO reference present.",
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (10, 40),
        "expected_routing": "auto_approve",
    },
    {
        "id": "clean_003",
        "description": "High-value invoice (>$50k) from a trusted vendor with a long history.",
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (15, 45),
        "expected_routing": "auto_approve",
    },
    {
        "id": "clean_004",
        "description": "Invoice with multiple line items, correct totals, international vendor (Kenya).",
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (5, 35),
        "expected_routing": "auto_approve",
    },
    {
        "id": "clean_005",
        "description": "Invoice with no PO reference but otherwise complete — PO ref is optional.",
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (5, 30),
        "expected_routing": "auto_approve",
    },
    # ------------------------------------------------------------------
    # Fraudulent cases — should be caught by a specific gate and blocked
    # ------------------------------------------------------------------
    {
        "id": "fraud_ofac_001",
        "description": "Vendor name matches an entity on the OFAC SDN list.",
        "fraud_type": "ofac_hit",
        "expected_gate_fail": "ofac",
        "expected_score_range": (85, 100),
        "expected_routing": "block",
    },
    {
        "id": "fraud_math_001",
        "description": (
            "Line item total does not match quantity × unit_price — "
            "classic invoice manipulation to overcharge."
        ),
        "fraud_type": "math_manipulation",
        "expected_gate_fail": "math",
        "expected_score_range": (70, 100),
        "expected_routing": "block",
    },
    {
        "id": "fraud_duplicate_001",
        "description": "Invoice number and amount exactly match a previously approved invoice.",
        "fraud_type": "duplicate_submission",
        "expected_gate_fail": "duplicate",
        "expected_score_range": (80, 100),
        "expected_routing": "block",
    },
    {
        "id": "fraud_bec_001",
        "description": (
            "Known vendor but bank account fingerprint changed — "
            "Business Email Compromise account-swap attack."
        ),
        "fraud_type": "bec_account_swap",
        "expected_gate_fail": "stripe",
        "expected_score_range": (85, 100),
        "expected_routing": "block",
    },
    # ------------------------------------------------------------------
    # Edge cases — ambiguous signals; human review expected
    # ------------------------------------------------------------------
    {
        "id": "edge_001",
        "description": (
            "Vendor name is a partial match to an OFAC entity (score below hard block threshold) "
            "but above the soft-flag threshold — should escalate to human review."
        ),
        "fraud_type": "ofac_partial_match",
        "expected_gate_fail": None,
        "expected_score_range": (50, 80),
        "expected_routing": "human_review",
    },
    {
        "id": "edge_002",
        "description": (
            "New vendor with a very high invoice amount ($200k+), no PO reference, "
            "and a Stripe Radar score of 65 — below auto-block but above auto-approve."
        ),
        "fraud_type": None,
        "expected_gate_fail": None,
        "expected_score_range": (50, 75),
        "expected_routing": "human_review",
    },
    {
        "id": "edge_003",
        "description": (
            "Invoice date is 89 days in the past (late submission), "
            "total is unusually high vs. vendor average, no prior flagging history."
        ),
        "fraud_type": "stale_invoice",
        "expected_gate_fail": None,
        "expected_score_range": (45, 70),
        "expected_routing": "human_review",
    },
]
