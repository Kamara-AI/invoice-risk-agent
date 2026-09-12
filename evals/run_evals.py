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
from pathlib import Path
from typing import Any

from evals.labeled_cases import LABELED_CASES

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
    pass


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
    pass


async def run_all_evals() -> None:
    """Run all 12 labeled cases and print a summary report.

    Metrics computed:
    - Routing accuracy: % of cases where actual_routing == expected_routing.
    - Gate detection rate: % of fraud cases where the correct gate fired.
    - Score range compliance: % of cases where actual_score is within expected_score_range.
    - Overall pass rate: % of cases that passed all three checks.
    """
    pass


def _compute_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate metrics from per-case results.

    Args:
        results: List of result dicts from run_single_case.

    Returns:
        Dict with keys: routing_accuracy, gate_detection_rate,
        score_range_compliance, overall_pass_rate. All values are floats 0.0–1.0.
    """
    pass


def _print_report(results: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    """Print a formatted per-case table and summary metrics to stdout.

    Args:
        results: List of result dicts from run_single_case.
        metrics: Aggregate metrics from _compute_metrics.
    """
    pass


if __name__ == "__main__":
    asyncio.run(run_all_evals())
