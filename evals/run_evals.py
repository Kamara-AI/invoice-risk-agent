"""Eval runner for the invoice risk agent.

Runs all 12 labeled cases through the compiled agent graph and computes
correctness metrics. Intended to be executed before any production deployment
and after any significant change to gate logic or LLM prompts.

Usage:
    python -m evals.run_evals

Output:
    Per-case pass/fail table printed to stdout.
    Summary metrics: routing accuracy, gate detection rate, score range compliance.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from db.client import supabase
from evals.labeled_cases import LABELED_CASES

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Vendors that should exist as 'trusted' in vendor_ledger before evals run.
# Simulates production state where these vendors have an established history.
_TRUSTED_VENDORS = [
    {
        "name": "Meridian Consulting Group LLC",
        "email": "invoices@meridiancg.com",
        "stripe_fingerprint": "ACH:026009593:556677889",
        "trust_level": "trusted",
        "ofac_status": "clear",
    },
    {
        "name": "Apex Office Supplies Ltd",
        "email": "billing@apexoffice.com",
        "stripe_fingerprint": "ACH:021000021:112233445",
        "trust_level": "trusted",
        "ofac_status": "clear",
    },
]


_EVAL_INVOICE_NUMBERS = [
    "APEX-2026-0881",      # clean_001 and fraud_duplicate_001
    "NOVA-2026-001",       # clean_002
    "MERIDIAN-2026-0334",  # clean_003
    "SAVASUPPLY-2026-192", # clean_004
    "GREENLEAF-2026-055",  # clean_005
    "GLOBALSTAR-2026-0041", # fraud_ofac_001
    "TECHPRO-2026-0213",   # fraud_math_001
    "MERIDIAN-2026-0335",  # fraud_bec_001
    "BLUERIDGE-2026-0011", # edge_001
    "BLUEWAVE-2026-001",   # edge_002
    "APEX-2026-0790",      # edge_003
    "HARBOR-2026-0044",    # stress_future_date_001
    "HALCYON-2026-0001",   # stress_stacking_soft_001
    "SUMMIT-2026-0001",    # stress_new_vendor_with_po_001
    "APEX-2026-0992",      # stress_trusted_high_value_001
    "CLEARWATER-2026-0077", # stress_zero_line_item_001
    "PINNACLE-2026-0001",  # stress_round_numbers_001
    "MERIDIAN-2026-0336",  # stress_missing_po_trusted_001
]


def _cleanup_invoice_history() -> None:
    """Delete all invoice_history records for eval fixture invoice numbers.

    Without this, re-runs of the eval suite cause the duplicate gate to fire on
    clean invoices that were correctly approved in a prior run — a false failure.
    """
    for inv_num in _EVAL_INVOICE_NUMBERS:
        try:
            supabase.table("invoice_history").delete().eq("invoice_number", inv_num).execute()
        except Exception:
            pass


def _seed_trusted_vendors() -> None:
    """Force-reset known trusted vendors to their canonical state in vendor_ledger.

    This must be a force-update, not insert-if-not-exists. The underlying bug in
    route_invoice (writing fraudulent BEC fingerprints back to vendor_ledger on blocked
    invoices) was fixed — route_invoice now only updates stripe_fingerprint when
    action != 'block'. This reset remains here as defence-in-depth for the eval suite.
    """
    for v in _TRUSTED_VENDORS:
        existing = supabase.table("vendor_ledger").select("vendor_id").ilike("name", v["name"]).execute()
        if existing.data:
            vendor_id = existing.data[0]["vendor_id"]
            supabase.table("vendor_ledger").update(v).eq("vendor_id", vendor_id).execute()
        else:
            supabase.table("vendor_ledger").insert(v).execute()

EAT = timezone(timedelta(hours=3))


async def load_fixture(case_id: str) -> bytes:
    """Load the PDF fixture file for a given case ID.

    Args:
        case_id: The case identifier (e.g. 'clean_001'). The corresponding
                 fixture file must be at evals/fixtures/{case_id}.pdf.

    Returns:
        Raw bytes of the PDF fixture file.

    Raises:
        FileNotFoundError: If the fixture PDF does not exist.
    """
    path = FIXTURES_DIR / f"{case_id}.pdf"
    return path.read_bytes()


async def run_single_case(case: dict) -> dict[str, Any]:
    """Run one labeled case through the agent graph and evaluate the result.

    Args:
        case: A labeled case dict from LABELED_CASES.

    Returns:
        A result dict with keys:
        - case_id: str
        - passed: bool — True if routing and gate outcome matched expectations.
        - actual_routing: str
        - expected_routing: str
        - actual_gate_fail: str | None
        - expected_gate_fail: str | None
        - actual_score: int
        - score_in_range: bool
        - error: str | None — set if the graph raised an unhandled exception.
    """
    from agent.graph import build_graph

    graph = build_graph()

    pdf_bytes = await load_fixture(case["id"])

    state = {
        "invoice_id": str(uuid.uuid4()),
        "raw_pdf_bytes": pdf_bytes,
        "gmail_message_id": None,
        "parsed_invoice": None,
        "gate_results": [],
        "current_gate": None,
        "gate_failed": False,
        "gate_failure_reason": None,
        "risk_score": None,
        "routing_decision": None,
        "slack_message_ts": None,
        "human_decision": None,
        "audit_record_id": None,
        "error": None,
        "created_at": datetime.now(EAT).isoformat(),
    }

    try:
        result = await graph.ainvoke(state)
    except Exception as e:
        return {
            "case_id": case["id"],
            "passed": False,
            "routing_correct": False,
            "gate_correct": False,
            "score_in_range": False,
            "actual_routing": None,
            "expected_routing": case["expected_routing"],
            "actual_gate_fail": None,
            "expected_gate_fail": case["expected_gate_fail"],
            "actual_score": None,
            "expected_score_range": case["expected_score_range"],
            "error": str(e),
            "description": case["description"],
            "fraud_type": case["fraud_type"],
        }

    actual_routing = result.get("routing_decision")
    actual_score = result["risk_score"]["score"] if result.get("risk_score") else None

    # Which gate failed (if any)?
    failed_gates = [g["gate_name"] for g in result.get("gate_results", []) if not g["passed"]]
    actual_gate_fail = failed_gates[0] if failed_gates else None

    # Score in expected range?
    # Gate-blocked cases never run llm_score so score is always None — skip check.
    score_min, score_max = case["expected_score_range"]
    gate_blocks_before_scoring = case["expected_gate_fail"] is not None
    if gate_blocks_before_scoring:
        score_in_range = True   # Score irrelevant when a gate hard-stops the pipeline
    else:
        score_in_range = actual_score is not None and score_min <= actual_score <= score_max

    # Overall pass: routing correct AND gate_fail correct AND score in range
    routing_correct = actual_routing == case["expected_routing"]
    gate_correct = actual_gate_fail == case["expected_gate_fail"]
    passed = routing_correct and gate_correct and score_in_range

    return {
        "case_id": case["id"],
        "passed": passed,
        "routing_correct": routing_correct,
        "gate_correct": gate_correct,
        "score_in_range": score_in_range,
        "actual_routing": actual_routing,
        "expected_routing": case["expected_routing"],
        "actual_gate_fail": actual_gate_fail,
        "expected_gate_fail": case["expected_gate_fail"],
        "actual_score": actual_score,
        "expected_score_range": case["expected_score_range"],
        "error": result.get("error"),
        "description": case["description"],
        "fraud_type": case["fraud_type"],
    }


async def run_all_evals() -> None:
    """Run all 12 labeled cases and print a summary report.

    Metrics computed:
    - Routing accuracy: % of cases where actual_routing == expected_routing.
    - Gate detection rate: % of fraud cases where the correct gate fired.
    - Score range compliance: % of cases where actual_score is within expected_score_range.
    - Overall pass rate: % of cases that passed all three checks.
    """
    # Clean up invoice_history for all fixture invoice numbers so duplicate gate
    # doesn't fire on re-runs of the eval suite.
    _cleanup_invoice_history()
    # Force-reset trusted vendors to their canonical state (fingerprint + trust_level)
    # so cases like fraud_bec_001 can't corrupt vendor records for later cases.
    _seed_trusted_vendors()
    print("Running Kagua eval suite — 19 cases...")
    print("=" * 70)
    results = []
    for case in LABELED_CASES:
        # Re-seed trusted vendors before each case so that processing a fraud case
        # (which calls route_invoice and may write a fraudulent fingerprint or
        # 'flagged' trust_level back to vendor_ledger) cannot corrupt subsequent cases.
        _seed_trusted_vendors()
        print(f"  Running {case['id']}...", end=" ", flush=True)
        result = await run_single_case(case)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(status)

    metrics = _compute_metrics(results)
    _print_report(results, metrics)


def _compute_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate metrics from per-case results.

    Args:
        results: List of result dicts from run_single_case.

    Returns:
        Dict with keys: routing_accuracy, gate_detection_rate,
        score_range_compliance, overall_pass_rate. All values are floats 0.0–1.0.
    """
    total = len(results)

    routing_correct = sum(1 for r in results if r.get("routing_correct", False))
    gate_correct = sum(1 for r in results if r.get("gate_correct", False))
    score_in_range = sum(1 for r in results if r.get("score_in_range", False))
    overall_pass = sum(1 for r in results if r.get("passed", False))

    # Silent failure rate: hard fraud cases that were NOT blocked (worst outcome)
    hard_fraud = [r for r in results if r.get("fraud_type") in (
        "ofac_hit", "math_manipulation", "duplicate_submission", "bec_account_swap"
    )]
    silent_failures = [r for r in hard_fraud if r.get("actual_routing") != "block"]

    return {
        "routing_accuracy": routing_correct / total,
        "gate_detection_rate": gate_correct / total,
        "score_range_compliance": score_in_range / total,
        "overall_pass_rate": overall_pass / total,
        "silent_failure_rate": len(silent_failures) / len(hard_fraud) if hard_fraud else 0.0,
        "total": total,
        "passed": overall_pass,
        "silent_failures": len(silent_failures),
        "hard_fraud_cases": len(hard_fraud),
    }


def _print_report(results: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    """Print a formatted per-case table and summary metrics to stdout.

    Args:
        results: List of result dicts from run_single_case.
        metrics: Aggregate metrics from _compute_metrics.
    """
    print()
    print("=" * 70)
    print("KAGUA EVAL REPORT")
    print("=" * 70)

    # Per-case table
    header = f"{'ID':<25} {'ROUTING':>12} {'EXPECTED':>12} {'SCORE':>6} {'GATE':>10} {'STATUS':>6}"
    print(header)
    print("-" * 70)
    for r in results:
        score_str = str(r["actual_score"]) if r["actual_score"] is not None else "N/A"
        gate_str = r["actual_gate_fail"] or "-"
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"{r['case_id']:<25} {str(r['actual_routing']):>12} {r['expected_routing']:>12} "
            f"{score_str:>6} {gate_str:>10} {status:>6}"
        )
        if r.get("error"):
            print(f"  ERROR: {r['error'][:80]}")

    print()
    print("=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)
    print(f"Overall pass rate:       {metrics['overall_pass_rate']*100:.1f}%  ({metrics['passed']}/{metrics['total']})")
    print(f"Routing accuracy:        {metrics['routing_accuracy']*100:.1f}%")
    print(f"Gate detection rate:     {metrics['gate_detection_rate']*100:.1f}%")
    print(f"Score range compliance:  {metrics['score_range_compliance']*100:.1f}%")
    print(
        f"Silent failure rate:     {metrics['silent_failure_rate']*100:.1f}%  "
        f"({metrics['silent_failures']} of {metrics['hard_fraud_cases']} hard fraud cases missed)"
    )
    print()
    if metrics["silent_failure_rate"] == 0.0:
        print("SILENT FAILURE RATE: 0% — all hard fraud cases blocked. This is the key metric.")
    else:
        print(f"WARNING: {metrics['silent_failures']} hard fraud case(s) passed through undetected.")


if __name__ == "__main__":
    asyncio.run(run_all_evals())
