"""Generate all 12 synthetic invoice PDFs for the eval fixture suite.

Run from the repo root:
    python evals/fixtures/generate_fixtures.py

Output: 12 PDF files in evals/fixtures/
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF

OUTPUT_DIR = Path(__file__).parent
TODAY = date(2026, 9, 13)


# ---------------------------------------------------------------------------
# PDF builder helper
# ---------------------------------------------------------------------------

class InvoicePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, "SYNTHETIC TEST DOCUMENT - NOT A REAL INVOICE", align="C")


def make_invoice(
    filename: str,
    invoice_number: str,
    vendor_name: str,
    vendor_email: str,
    vendor_bank_account: str,
    line_items: list[dict],          # {desc, qty, unit_price, line_total}
    subtotal: float,
    tax: float,
    total: float,
    invoice_date: date,
    due_date: date,
    purchase_order_ref: str | None,
    currency: str = "USD",
    note: str | None = None,
) -> None:
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- vendor block ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, vendor_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, vendor_email, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Bank Account: {vendor_bank_account}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- invoice meta ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(50, 6, "Invoice Number:", border=0)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, invoice_number, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(50, 6, "Invoice Date:")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, str(invoice_date), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(50, 6, "Due Date:")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, str(due_date), new_x="LMARGIN", new_y="NEXT")

    if purchase_order_ref:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(50, 6, "PO Reference:")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, purchase_order_ref, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

    # --- line items table ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    col_w = [80, 20, 35, 35]
    headers = ["Description", "Qty", f"Unit Price ({currency})", f"Total ({currency})"]
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 10)
    for item in line_items:
        pdf.cell(col_w[0], 6, item["desc"][:45], border=1)
        pdf.cell(col_w[1], 6, str(item["qty"]), border=1, align="C")
        pdf.cell(col_w[2], 6, f"{item['unit_price']:,.2f}", border=1, align="R")
        pdf.cell(col_w[3], 6, f"{item['line_total']:,.2f}", border=1, align="R")
        pdf.ln()

    pdf.ln(3)

    # --- totals ---
    right_start = 130
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(right_start)
    pdf.cell(35, 6, "Subtotal:", align="R")
    pdf.cell(25, 6, f"{subtotal:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(right_start)
    pdf.cell(35, 6, "Tax:", align="R")
    pdf.cell(25, 6, f"{tax:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(right_start)
    pdf.cell(35, 6, f"TOTAL ({currency}):", align="R")
    pdf.cell(25, 6, f"{total:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    # --- optional note ---
    if note:
        pdf.ln(6)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(150, 0, 0)
        pdf.multi_cell(0, 5, f"Note: {note}")
        pdf.set_text_color(0, 0, 0)

    out = OUTPUT_DIR / filename
    pdf.output(str(out))
    print(f"  OK  {filename}")


# ---------------------------------------------------------------------------
# 12 fixtures
# ---------------------------------------------------------------------------

def main() -> None:
    print("Generating eval fixtures...")

    # ------------------------------------------------------------------ CLEAN

    # clean_001 — trusted repeat vendor, all valid
    make_invoice(
        filename="clean_001.pdf",
        invoice_number="APEX-2026-0881",
        vendor_name="Apex Office Supplies Ltd",
        vendor_email="billing@apexoffice.com",
        vendor_bank_account="ACH:021000021:112233445",
        line_items=[
            {"desc": "A4 Copy Paper (500 reams)", "qty": 500, "unit_price": 4.50, "line_total": 2250.00},
            {"desc": "Ballpoint Pens (box of 50)", "qty": 20, "unit_price": 12.00, "line_total": 240.00},
            {"desc": "Printer Toner Cartridge XL", "qty": 10, "unit_price": 85.00, "line_total": 850.00},
        ],
        subtotal=3340.00, tax=267.20, total=3607.20,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-4421",
    )

    # clean_002 — new vendor, first invoice, PO present
    make_invoice(
        filename="clean_002.pdf",
        invoice_number="NOVA-2026-001",
        vendor_name="Nova Tech Solutions Inc",
        vendor_email="accounts@novatech.io",
        vendor_bank_account="ACH:071000013:887766554",
        line_items=[
            {"desc": "Cloud Infrastructure Audit (8 hrs)", "qty": 8, "unit_price": 200.00, "line_total": 1600.00},
            {"desc": "Security Assessment Report", "qty": 1, "unit_price": 500.00, "line_total": 500.00},
        ],
        subtotal=2100.00, tax=168.00, total=2268.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-5100",
    )

    # clean_003 — high-value ($72k) trusted vendor with long history
    make_invoice(
        filename="clean_003.pdf",
        invoice_number="MERIDIAN-2026-0334",
        vendor_name="Meridian Consulting Group LLC",
        vendor_email="invoices@meridiancg.com",
        vendor_bank_account="ACH:026009593:556677889",
        line_items=[
            {"desc": "Strategic Advisory Services (Q3 2026)", "qty": 1, "unit_price": 60000.00, "line_total": 60000.00},
            {"desc": "Executive Workshop (2 days)", "qty": 2, "unit_price": 5000.00, "line_total": 10000.00},
            {"desc": "Travel & Expenses (reimbursable)", "qty": 1, "unit_price": 2000.00, "line_total": 2000.00},
        ],
        subtotal=72000.00, tax=5760.00, total=77760.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=45),
        purchase_order_ref="PO-2026-3800",
    )

    # clean_004 — multi-line Kenyan vendor (international)
    make_invoice(
        filename="clean_004.pdf",
        invoice_number="SAVASUPPLY-2026-192",
        vendor_name="Sava Supply Chain Ltd",
        vendor_email="finance@savasupply.co.ke",
        vendor_bank_account="SWIFT:KCBLKENX:1234567890",
        line_items=[
            {"desc": "Logistics Management Software (annual)", "qty": 1, "unit_price": 3500.00, "line_total": 3500.00},
            {"desc": "On-site Training (3 days, Nairobi)", "qty": 3, "unit_price": 800.00, "line_total": 2400.00},
            {"desc": "API Integration Support (10 hrs)", "qty": 10, "unit_price": 150.00, "line_total": 1500.00},
            {"desc": "Data Migration (one-time)", "qty": 1, "unit_price": 600.00, "line_total": 600.00},
        ],
        subtotal=8000.00, tax=1280.00, total=9280.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-7210",
        currency="USD",
    )

    # clean_005 — no PO ref, otherwise complete
    make_invoice(
        filename="clean_005.pdf",
        invoice_number="GREENLEAF-2026-055",
        vendor_name="Greenleaf Facilities Services",
        vendor_email="billing@greenleaffacilities.com",
        vendor_bank_account="ACH:111000025:334455667",
        line_items=[
            {"desc": "Office Cleaning Services (September)", "qty": 1, "unit_price": 1800.00, "line_total": 1800.00},
            {"desc": "Waste Disposal & Recycling", "qty": 1, "unit_price": 350.00, "line_total": 350.00},
        ],
        subtotal=2150.00, tax=172.00, total=2322.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref=None,
    )

    # --------------------------------------------------------------- FRAUDULENT

    # fraud_ofac_001 — vendor on OFAC SDN list
    make_invoice(
        filename="fraud_ofac_001.pdf",
        invoice_number="GLOBALSTAR-2026-0041",
        vendor_name="Global Stars General Trading LLC",   # OFAC SDN entity
        vendor_email="payments@globalstarstrading.com",
        vendor_bank_account="SWIFT:MASQOMRX:9988776655",
        line_items=[
            {"desc": "Consulting Services - Project Delta", "qty": 1, "unit_price": 15000.00, "line_total": 15000.00},
        ],
        subtotal=15000.00, tax=1200.00, total=16200.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=15),
        purchase_order_ref="PO-2026-9001",
        note="OFAC TEST: Vendor name matches SDN entity. Expected: block at gate_ofac.",
    )

    # fraud_math_001 — line total deliberately wrong
    make_invoice(
        filename="fraud_math_001.pdf",
        invoice_number="TECHPRO-2026-0213",
        vendor_name="TechPro IT Services",
        vendor_email="billing@techproservices.com",
        vendor_bank_account="ACH:021000089:443322110",
        line_items=[
            {"desc": "Server Rack Rental (12 months)", "qty": 12, "unit_price": 400.00, "line_total": 5800.00},  # should be 4800
            {"desc": "Network Switch (48-port)", "qty": 2, "unit_price": 650.00, "line_total": 1300.00},
        ],
        subtotal=7100.00, tax=568.00, total=7668.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-6632",
        note="MATH FRAUD TEST: Line 1 total=5800 but 12×400=4800. Expected: block at gate_math.",
    )

    # fraud_duplicate_001 — exact duplicate of clean_001 in disguise
    make_invoice(
        filename="fraud_duplicate_001.pdf",
        invoice_number="APEX-2026-0881",   # same number as clean_001
        vendor_name="Apex Office Supplies Ltd",
        vendor_email="billing@apexoffice.com",
        vendor_bank_account="ACH:021000021:112233445",
        line_items=[
            {"desc": "A4 Copy Paper (500 reams)", "qty": 500, "unit_price": 4.50, "line_total": 2250.00},
            {"desc": "Ballpoint Pens (box of 50)", "qty": 20, "unit_price": 12.00, "line_total": 240.00},
            {"desc": "Printer Toner Cartridge XL", "qty": 10, "unit_price": 85.00, "line_total": 850.00},
        ],
        subtotal=3340.00, tax=267.20, total=3607.20,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-4421",
        note="DUPLICATE TEST: Invoice APEX-2026-0881 for $3607.20 already approved. Expected: block at gate_duplicate.",
    )

    # fraud_bec_001 — known vendor, bank account changed (BEC)
    make_invoice(
        filename="fraud_bec_001.pdf",
        invoice_number="MERIDIAN-2026-0335",
        vendor_name="Meridian Consulting Group LLC",  # known vendor
        vendor_email="invoices@meridiancg.com",
        vendor_bank_account="ACH:999888777:111222333",  # NEW — different from vendor ledger
        line_items=[
            {"desc": "Strategic Advisory Services (Q4 2026)", "qty": 1, "unit_price": 60000.00, "line_total": 60000.00},
        ],
        subtotal=60000.00, tax=4800.00, total=64800.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=45),
        purchase_order_ref="PO-2026-3900",
        note="BEC TEST: Bank account changed from known fingerprint. Expected: block at gate_stripe.",
    )

    # ------------------------------------------------------------------- EDGE

    # edge_001 — new vendor, $72k, no PO, 52 days stale (deterministic escalation)
    stale_52 = TODAY - timedelta(days=52)
    make_invoice(
        filename="edge_001.pdf",
        invoice_number="BLUERIDGE-2026-0011",
        vendor_name="Blue Ridge Capital Advisors LLC",
        vendor_email="billing@blueridgecap.com",
        vendor_bank_account="ACH:021000021:876543210",
        line_items=[
            {"desc": "M&A Advisory Services - Project Horizon", "qty": 1, "unit_price": 65000.00, "line_total": 65000.00},
            {"desc": "Financial Due Diligence Report", "qty": 1, "unit_price": 7000.00, "line_total": 7000.00},
        ],
        subtotal=72000.00, tax=5760.00, total=77760.00,
        invoice_date=stale_52, due_date=stale_52 + timedelta(days=30),
        purchase_order_ref=None,
        note="EDGE STALE: New vendor, $77k, no PO, 52 days late. Expected: human_review.",
    )

    # edge_002 — new vendor, $210k, no PO, elevated Radar
    make_invoice(
        filename="edge_002.pdf",
        invoice_number="BLUEWAVE-2026-001",
        vendor_name="Bluewave Capital Partners",   # new vendor, no history
        vendor_email="billing@bluewavecap.com",
        vendor_bank_account="ACH:021000021:998877665",
        line_items=[
            {"desc": "Series A Due Diligence Support", "qty": 1, "unit_price": 180000.00, "line_total": 180000.00},
            {"desc": "Financial Modelling (specialist)", "qty": 1, "unit_price": 30000.00, "line_total": 30000.00},
        ],
        subtotal=210000.00, tax=16800.00, total=226800.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref=None,     # no PO
        note="EDGE HIGH VALUE: New vendor, $226k, no PO, Radar score ~65. Expected: human_review.",
    )

    # edge_003 — stale invoice (89 days old)
    stale_date = TODAY - timedelta(days=89)
    make_invoice(
        filename="edge_003.pdf",
        invoice_number="APEX-2026-0790",
        vendor_name="Apex Office Supplies Ltd",
        vendor_email="billing@apexoffice.com",
        vendor_bank_account="ACH:021000021:112233445",
        line_items=[
            {"desc": "Executive Furniture Package (6 units)", "qty": 6, "unit_price": 2200.00, "line_total": 13200.00},
            {"desc": "Installation & Assembly", "qty": 1, "unit_price": 800.00, "line_total": 800.00},
        ],
        subtotal=14000.00, tax=1120.00, total=15120.00,
        invoice_date=stale_date,
        due_date=stale_date + timedelta(days=30),
        purchase_order_ref="PO-2026-3011",
        note=f"EDGE STALE: Invoice date {stale_date} is 89 days ago. High vs vendor avg (~$3.6k). Expected: human_review.",
    )

    # --------------------------------------------------------------- STRESS

    # stress_future_date_001 — invoice dated 7 days in the future
    future_date = TODAY + timedelta(days=7)
    make_invoice(
        filename="stress_future_date_001.pdf",
        invoice_number="HARBOR-2026-0044",
        vendor_name="Harbor Crest Consulting Ltd",
        vendor_email="billing@harborcrest.com",
        vendor_bank_account="ACH:021000021:765432198",
        line_items=[
            {"desc": "IT Security Assessment (10 hrs)", "qty": 10, "unit_price": 850.00, "line_total": 8500.00},
        ],
        subtotal=8500.00, tax=680.00, total=9180.00,
        invoice_date=future_date, due_date=future_date + timedelta(days=30),
        purchase_order_ref=None,
        note="STRESS: Invoice date is 7 days in the future. Expected: block at gate_quality.",
    )

    # stress_stacking_soft_001 — new vendor, $92k, no PO, 35 days stale
    stale_35 = TODAY - timedelta(days=35)
    make_invoice(
        filename="stress_stacking_soft_001.pdf",
        invoice_number="HALCYON-2026-0001",
        vendor_name="Halcyon Business Consultants Ltd",
        vendor_email="invoices@halcyonbc.com",
        vendor_bank_account="ACH:071000013:543219876",
        line_items=[
            {"desc": "Strategic Communications Strategy", "qty": 1, "unit_price": 50000.00, "line_total": 50000.00},
            {"desc": "Market Analysis Report (3 regions)", "qty": 3, "unit_price": 12000.00, "line_total": 36000.00},
            {"desc": "Executive Briefing Sessions", "qty": 2, "unit_price": 3000.00, "line_total": 6000.00},
        ],
        subtotal=92000.00, tax=7360.00, total=99360.00,
        invoice_date=stale_35, due_date=stale_35 + timedelta(days=30),
        purchase_order_ref=None,
        note="STRESS STACKING: New vendor + $92k + no PO + 35 days stale. Expected: human_review.",
    )

    # stress_new_vendor_with_po_001 — new vendor, $85k, WITH PO reference
    make_invoice(
        filename="stress_new_vendor_with_po_001.pdf",
        invoice_number="SUMMIT-2026-0001",
        vendor_name="Summit Pacific Analytics Inc",
        vendor_email="billing@summitpacific.com",
        vendor_bank_account="ACH:026009593:321987654",
        line_items=[
            {"desc": "Enterprise Data Analytics Platform (annual)", "qty": 1, "unit_price": 70000.00, "line_total": 70000.00},
            {"desc": "Implementation & Configuration Services", "qty": 1, "unit_price": 10000.00, "line_total": 10000.00},
            {"desc": "Staff Training & Onboarding (5 users)", "qty": 5, "unit_price": 1000.00, "line_total": 5000.00},
        ],
        subtotal=85000.00, tax=6800.00, total=91800.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref="PO-2026-8801",
        note="STRESS: New vendor, $85k, WITH PO. Expected: auto_approve (PO covers high-value risk).",
    )

    # stress_trusted_high_value_001 — trusted Apex, $180k, with PO
    make_invoice(
        filename="stress_trusted_high_value_001.pdf",
        invoice_number="APEX-2026-0992",
        vendor_name="Apex Office Supplies Ltd",
        vendor_email="billing@apexoffice.com",
        vendor_bank_account="ACH:021000021:112233445",
        line_items=[
            {"desc": "Office Fit-Out Package - Open Plan (60 desks)", "qty": 60, "unit_price": 2000.00, "line_total": 120000.00},
            {"desc": "Executive Suite Furniture (10 units)", "qty": 10, "unit_price": 5000.00, "line_total": 50000.00},
            {"desc": "Installation, Delivery & Logistics", "qty": 1, "unit_price": 10000.00, "line_total": 10000.00},
        ],
        subtotal=180000.00, tax=14400.00, total=194400.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=45),
        purchase_order_ref="PO-2026-9500",
        note="STRESS HIGH VALUE: Trusted Apex, $180k + PO. Expected: auto_approve.",
    )

    # stress_zero_line_item_001 — $0 complimentary line + paid line, correct math
    make_invoice(
        filename="stress_zero_line_item_001.pdf",
        invoice_number="CLEARWATER-2026-0077",
        vendor_name="Clearwater Professional Services",
        vendor_email="accounts@clearwaterps.com",
        vendor_bank_account="ACH:111000025:678901234",
        line_items=[
            {"desc": "Custom Software Development (Sprint 4)", "qty": 1, "unit_price": 6500.00, "line_total": 6500.00},
            {"desc": "Complimentary Code Review Service", "qty": 1, "unit_price": 0.00, "line_total": 0.00},
        ],
        subtotal=6500.00, tax=520.00, total=7020.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref=None,
        note="STRESS ZERO LINE: $0 complimentary service included. Math is correct. Expected: auto_approve.",
    )

    # stress_round_numbers_001 — new vendor, exactly $25k round, no PO
    make_invoice(
        filename="stress_round_numbers_001.pdf",
        invoice_number="PINNACLE-2026-0001",
        vendor_name="Pinnacle Strategy Group Inc",
        vendor_email="finance@pinnaclesg.com",
        vendor_bank_account="ACH:021000089:234567890",
        line_items=[
            {"desc": "Annual Management Consulting Retainer", "qty": 1, "unit_price": 25000.00, "line_total": 25000.00},
        ],
        subtotal=25000.00, tax=2000.00, total=27000.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref=None,
        note="STRESS ROUND: New vendor, exactly $25k, no PO. Expected: auto_approve.",
    )

    # stress_missing_po_trusted_001 — trusted Meridian, no PO, $15k
    make_invoice(
        filename="stress_missing_po_trusted_001.pdf",
        invoice_number="MERIDIAN-2026-0336",
        vendor_name="Meridian Consulting Group LLC",
        vendor_email="invoices@meridiancg.com",
        vendor_bank_account="ACH:026009593:556677889",
        line_items=[
            {"desc": "Q4 Strategic Project Review Sessions", "qty": 3, "unit_price": 4000.00, "line_total": 12000.00},
            {"desc": "Written Summary Report", "qty": 1, "unit_price": 3000.00, "line_total": 3000.00},
        ],
        subtotal=15000.00, tax=1200.00, total=16200.00,
        invoice_date=TODAY, due_date=TODAY + timedelta(days=30),
        purchase_order_ref=None,
        note="STRESS TRUSTED NO PO: Trusted Meridian, $15k, no PO. Expected: auto_approve.",
    )

    print(f"\nDone. 19 PDFs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
