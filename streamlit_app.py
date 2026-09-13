"""Streamlit UI for the Invoice Risk Intelligence Agent.

Provides a clean, demo-ready interface for judges to upload an invoice PDF
and observe the full LangGraph pipeline run — gate results, LLM risk score,
routing decision, and parsed invoice details.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import streamlit as st

# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Invoice Risk Agent",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EAT = timezone(timedelta(hours=3))

GATE_DESCRIPTIONS: dict[str, str] = {
    "quality": "Document quality and completeness check",
    "math": "Line-item arithmetic verification",
    "duplicate": "Duplicate invoice detection via Supabase",
    "ofac": "OFAC sanctions screening",
    "stripe": "Stripe payment fingerprinting / BEC detection",
}

ROUTING_CONFIG: dict[str, dict] = {
    "auto_approve": {
        "label": "AUTO APPROVED",
        "color": "success",
        "icon": "✅",
        "description": "Invoice cleared all gates. Risk score is within acceptable thresholds.",
    },
    "human_review": {
        "label": "HUMAN REVIEW REQUIRED",
        "color": "warning",
        "icon": "⚠️",
        "description": "Risk score or gate flags require a human reviewer before payment is released.",
    },
    "block": {
        "label": "BLOCKED",
        "color": "error",
        "icon": "🚫",
        "description": "Invoice failed critical validation. Payment has been blocked pending investigation.",
    },
}

# ---------------------------------------------------------------------------
# Integration connectivity check
# ---------------------------------------------------------------------------

def _check_integration_status() -> dict[str, bool]:
    """Check whether each external integration is configured in the environment.

    Uses presence of environment variables as a connectivity proxy —
    avoids making live API calls on every page load.
    """
    import os

    return {
        "OFAC": bool(os.getenv("OFAC_API_KEY")),
        "Stripe": bool(os.getenv("STRIPE_API_KEY")),
        "Supabase": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")),
        "Slack": bool(os.getenv("SLACK_BOT_TOKEN")),
    }


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_graph():
    """Build and cache the LangGraph pipeline once per Streamlit server process.

    Using st.cache_resource ensures build_graph() is called once and reused
    across all user sessions and requests — avoids recompiling the StateGraph
    on every upload click.
    """
    from agent.graph import build_graph
    return build_graph()


def run_pipeline(pdf_bytes: bytes, filename: str) -> dict:
    """Invoke the LangGraph pipeline synchronously from the Streamlit thread.

    Uses a ThreadPoolExecutor to run asyncio.run() in a dedicated thread,
    which is safe even when Streamlit itself is running inside an event loop
    (e.g. under newer Streamlit versions that use asyncio internally).

    Args:
        pdf_bytes: Raw bytes of the uploaded PDF invoice.
        filename: Original filename — stored for display purposes only.

    Returns:
        Final AgentState dict after the graph has run to completion.
    """
    import concurrent.futures

    graph = _get_graph()
    initial_state: dict = {
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
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result: dict = pool.submit(asyncio.run, graph.ainvoke(initial_state)).result()
    return result


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _render_sidebar(integration_status: dict[str, bool]) -> None:
    """Render the sidebar with integration status indicators.

    Args:
        integration_status: Mapping of integration name to connectivity bool.
    """
    st.sidebar.title("🔌 Integrations")
    st.sidebar.markdown("---")

    integration_icons: dict[str, str] = {
        "OFAC": "🛡️",
        "Stripe": "💳",
        "Supabase": "🗄️",
        "Slack": "💬",
    }
    integration_descriptions: dict[str, str] = {
        "OFAC": "Sanctions screening",
        "Stripe": "Payment fingerprinting",
        "Supabase": "Audit persistence",
        "Slack": "Human review alerts",
    }

    for name, connected in integration_status.items():
        dot = "🟢" if connected else "🔴"
        status_text = "Connected" if connected else "Not configured"
        st.sidebar.markdown(
            f"{dot} **{integration_icons[name]} {name}**  \n"
            f"<small>{integration_descriptions[name]} — {status_text}</small>",
            unsafe_allow_html=True,
        )
        st.sidebar.markdown("")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔀 Pipeline Gates")
    for gate, desc in GATE_DESCRIPTIONS.items():
        st.sidebar.markdown(f"**{gate.upper()}** — {desc}")

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<small>Built with LangGraph + GPT-4o  \n"
        "Hackathon demo — Invoice Risk Intelligence Agent</small>",
        unsafe_allow_html=True,
    )


def _render_routing_badge(routing: str) -> None:
    """Render a large colored routing decision badge.

    Args:
        routing: One of 'auto_approve' | 'human_review' | 'block'.
    """
    cfg = ROUTING_CONFIG.get(routing, {
        "label": routing.upper(),
        "color": "info",
        "icon": "ℹ️",
        "description": "Unknown routing outcome.",
    })

    if cfg["color"] == "success":
        st.success(f"{cfg['icon']} **{cfg['label']}** — {cfg['description']}")
    elif cfg["color"] == "warning":
        st.warning(f"{cfg['icon']} **{cfg['label']}** — {cfg['description']}")
    elif cfg["color"] == "error":
        st.error(f"{cfg['icon']} **{cfg['label']}** — {cfg['description']}")
    else:
        st.info(f"{cfg['icon']} **{cfg['label']}** — {cfg['description']}")


def _render_risk_score(risk_score: dict) -> None:
    """Render the risk score section with progress bar, reasoning, and flags.

    Args:
        risk_score: Serialised RiskScore dict from agent state.
    """
    score: int = risk_score.get("score", 0)
    reasoning: str = risk_score.get("reasoning", "")
    flags: list[str] = risk_score.get("flags", [])
    recommendation: str = risk_score.get("recommendation", "")

    st.markdown("### 📊 Risk Score")

    col_score, col_rec = st.columns([1, 2])
    with col_score:
        # Color the metric label based on score band
        if score >= 90:
            score_label = f"🔴 {score}/100"
        elif score >= 70:
            score_label = f"🟡 {score}/100"
        else:
            score_label = f"🟢 {score}/100"
        st.metric("Composite Risk Score", score_label)
        st.progress(score / 100)

    with col_rec:
        if recommendation:
            st.markdown(f"**LLM Recommendation:** `{recommendation}`")
        if flags:
            flag_badges = " ".join([f"`{f}`" for f in flags])
            st.markdown(f"**Risk Flags:** {flag_badges}")

    if reasoning:
        with st.expander("💬 LLM Reasoning", expanded=True):
            st.markdown(reasoning)


def _render_gate_results(gate_results: list[dict]) -> None:
    """Render the gate results as a styled dataframe.

    Args:
        gate_results: List of serialised GateResult dicts.
    """
    import pandas as pd

    st.markdown("### 🔐 Gate Results")

    rows = []
    for g in gate_results:
        passed = g.get("passed", False)
        rows.append({
            "Gate": g.get("gate_name", "unknown").upper(),
            "Status": "✅ Passed" if passed else "❌ Failed",
            "Reason": g.get("reason", ""),
            "Checked At": g.get("checked_at", ""),
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No gate results recorded.")


def _render_parsed_invoice(parsed_invoice: dict) -> None:
    """Render parsed invoice details in a collapsible expander.

    Args:
        parsed_invoice: Serialised ParsedInvoice dict from agent state.
    """
    with st.expander("📄 Parsed Invoice Details", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"**Invoice Number:** {parsed_invoice.get('invoice_number', 'N/A')}")
            st.markdown(f"**Vendor Name:** {parsed_invoice.get('vendor_name', 'N/A')}")
            st.markdown(f"**Vendor Email:** {parsed_invoice.get('vendor_email', 'N/A')}")
            st.markdown(f"**Invoice Date:** {parsed_invoice.get('invoice_date', 'N/A')}")

        with col2:
            currency = parsed_invoice.get("currency", "USD")
            total = parsed_invoice.get("total", 0)
            subtotal = parsed_invoice.get("subtotal", 0)
            tax = parsed_invoice.get("tax", 0)

            st.markdown(f"**Total:** {currency} {total:,.2f}")
            st.markdown(f"**Subtotal:** {currency} {subtotal:,.2f}")
            st.markdown(f"**Tax:** {currency} {tax:,.2f}")
            st.markdown(f"**Due Date:** {parsed_invoice.get('due_date', 'N/A')}")

        if parsed_invoice.get("purchase_order_ref"):
            st.markdown(f"**PO Reference:** {parsed_invoice['purchase_order_ref']}")

        line_items = parsed_invoice.get("line_items", [])
        if line_items:
            import pandas as pd

            st.markdown("**Line Items:**")
            li_rows = [
                {
                    "Description": li.get("description", ""),
                    "Qty": li.get("quantity", 0),
                    "Unit Price": f"{currency} {li.get('unit_price', 0):,.2f}",
                    "Line Total": f"{currency} {li.get('line_total', 0):,.2f}",
                }
                for li in line_items
            ]
            st.dataframe(pd.DataFrame(li_rows), use_container_width=True, hide_index=True)


def _render_demo_invoices() -> None:
    """Render download buttons for fixture PDFs so judges can test without their own invoices."""
    from pathlib import Path

    fixtures_dir = Path(__file__).parent / "evals" / "fixtures"

    DEMO_INVOICES = [
        {
            "id": "clean_001",
            "label": "✅ Clean — Trusted Repeat Vendor",
            "description": "Apex Office Supplies, $3,607. All gates pass. Expected: AUTO APPROVE.",
        },
        {
            "id": "edge_001",
            "label": "⚠️ Edge — New Vendor, Stale + High Value",
            "description": "Blue Ridge Capital, $77k, no PO, 52 days late. Expected: HUMAN REVIEW.",
        },
        {
            "id": "fraud_math_001",
            "label": "🚫 Fraud — Math Manipulation",
            "description": "Line item inflated: 12×$400 shown as $5,800. Expected: BLOCKED at math gate.",
        },
        {
            "id": "fraud_ofac_001",
            "label": "🚫 Fraud — OFAC Sanctions Hit",
            "description": "Vendor name matches OFAC SDN entity. Expected: BLOCKED at OFAC gate.",
        },
        {
            "id": "fraud_bec_001",
            "label": "🚫 Fraud — BEC Bank Account Swap",
            "description": "Known vendor (Meridian) with changed bank account. Expected: BLOCKED at Stripe gate.",
        },
        {
            "id": "stress_stacking_soft_001",
            "label": "⚠️ Stress — Stacking Soft Signals",
            "description": "New vendor, $92k, no PO, 35 days stale. Three soft signals stack. Expected: HUMAN REVIEW.",
        },
    ]

    st.markdown("### 🧪 Try a Demo Invoice")
    st.markdown(
        "Download any fixture below, then upload it above to see the pipeline in action. "
        "Each PDF is a synthetic invoice designed to trigger a specific outcome."
    )

    cols = st.columns(3)
    for i, demo in enumerate(DEMO_INVOICES):
        pdf_path = fixtures_dir / f"{demo['id']}.pdf"
        col = cols[i % 3]
        with col:
            if pdf_path.exists():
                pdf_bytes = pdf_path.read_bytes()
                col.download_button(
                    label=demo["label"],
                    data=pdf_bytes,
                    file_name=f"{demo['id']}.pdf",
                    mime="application/pdf",
                    help=demo["description"],
                    use_container_width=True,
                )
                col.caption(demo["description"])
            else:
                col.warning(f"Fixture not found: {demo['id']}.pdf")

    st.markdown("---")


def _render_demo_instructions() -> None:
    """Render collapsible pipeline overview for judges."""
    with st.expander("📋 How It Works", expanded=False):
        st.markdown("""
**Gate 1 — Quality:** Required fields present, valid dates (no future-dated invoices), recognised currency code.

**Gate 2 — Math:** Every line item re-calculated: `qty × unit_price = line_total`. Sum of lines = subtotal. `subtotal + tax = total`. Tolerance: ±$0.05.

**Gate 3 — Duplicate:** Supabase lookup by `(vendor_id, invoice_number)`. Also checks same amount + same vendor within a 7-day window.

**Gate 4 — OFAC:** Vendor name screened against OFAC Specially Designated Nationals list. Score ≥ 90 → hard block. Score 75–89 → soft flag injected into LLM context (+35 risk points).

**Gate 5 — Stripe:** Bank account fingerprint compared to stored vendor fingerprint. Mismatch on a known vendor = Business Email Compromise flag → hard block.

**LLM Risk Score (GPT-4o):** Only runs if all 5 gates pass. Returns score 0–100 with flags and reasoning.

**Routing thresholds:** 0–49 → AUTO APPROVE · 50–89 → HUMAN REVIEW (Slack card sent) · 90–100 → BLOCK
        """)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the Streamlit application.

    Renders the full UI: header, sidebar, upload widget, and results.
    All pipeline calls are gated behind a button click to avoid accidental
    re-runs on widget interaction.
    """
    # ---- Integration status (sidebar) ------------------------------------
    integration_status = _check_integration_status()
    _render_sidebar(integration_status)

    # ---- Header ----------------------------------------------------------
    st.title("🔍 Invoice Risk Intelligence Agent")
    st.markdown(
        "**Multi-gate fraud detection powered by LangGraph + GPT-4o**  \n"
        "Upload an invoice PDF to run it through 5 validation gates and an LLM risk scorer."
    )
    st.markdown("---")

    # ---- Demo fixture downloads ------------------------------------------
    _render_demo_invoices()

    # ---- Pipeline overview -----------------------------------------------
    _render_demo_instructions()

    # ---- Upload area -----------------------------------------------------
    st.markdown("### 📤 Upload Invoice")
    uploaded_file = st.file_uploader(
        "Select a PDF invoice to analyse",
        type=["pdf"],
        help="PDF invoices only. Maximum 10 MB.",
    )

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        analyse_clicked = st.button(
            "🚀 Analyse Invoice",
            type="primary",
            disabled=uploaded_file is None,
        )
    with col_info:
        if uploaded_file is None:
            st.info("Upload a PDF above, then click **Analyse Invoice**.")
        else:
            st.success(f"File ready: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

    # ---- Pipeline run ----------------------------------------------------
    if analyse_clicked and uploaded_file is not None:
        pdf_bytes = uploaded_file.read()

        with st.spinner("Running pipeline... this may take 15–30 seconds."):
            try:
                result = run_pipeline(pdf_bytes, uploaded_file.name)
            except Exception as exc:  # noqa: BLE001 — surface all errors to the UI
                st.error(f"Pipeline failed to start: {exc}")
                st.stop()

        st.markdown("---")
        st.markdown("## 📋 Analysis Results")

        # Show invoice ID for traceability
        invoice_id = result.get("invoice_id", "unknown")
        st.caption(f"Run ID: `{invoice_id}` — {result.get('created_at', '')}")

        # ---- Error state -------------------------------------------------
        if result.get("error"):
            st.error(f"**Pipeline error:** {result['error']}")
            st.markdown(
                "The pipeline encountered an unhandled error. "
                "Check your environment variables and integration credentials."
            )

        # ---- Routing decision --------------------------------------------
        routing = result.get("routing_decision")
        if routing:
            _render_routing_badge(routing)
        else:
            st.warning("No routing decision was produced. The pipeline may have exited early.")

        st.markdown("---")

        # ---- Risk score --------------------------------------------------
        risk_score = result.get("risk_score")
        if risk_score:
            _render_risk_score(risk_score)
            st.markdown("---")

        # ---- Gate results ------------------------------------------------
        gate_results = result.get("gate_results", [])
        if gate_results:
            _render_gate_results(gate_results)
            st.markdown("---")

        # ---- Gate failure detail -----------------------------------------
        if result.get("gate_failure_reason"):
            st.error(f"**Gate failure:** {result['gate_failure_reason']}")

        # ---- Parsed invoice details --------------------------------------
        parsed_invoice = result.get("parsed_invoice")
        if parsed_invoice:
            _render_parsed_invoice(parsed_invoice)

        # ---- Human review next step -------------------------------------
        if routing == "human_review":
            slack_ts = result.get("slack_message_ts")
            st.markdown("### 👤 Next Step — Human Review Required")
            if slack_ts:
                st.warning(
                    "An interactive review card has been posted to **#invoice-review** in Slack.  \n"
                    "The reviewer must click **Approve** or **Reject** in Slack to complete this invoice.  \n"
                    f"Slack thread: `{slack_ts}`"
                )
            else:
                st.warning(
                    "This invoice requires human review.  \n"
                    "Check **#invoice-review** in Slack — a review card should have been posted.  \n"
                    "If no card arrived, verify your `SLACK_BOT_TOKEN` and channel configuration."
                )

        # ---- Audit persistence confirmation ------------------------------
        audit_id = result.get("audit_record_id")
        if audit_id:
            st.markdown("### 📌 Audit Trail")
            st.success(f"Persisted to Supabase audit log. Record ID: `{audit_id}`")


if __name__ == "__main__":
    main()
