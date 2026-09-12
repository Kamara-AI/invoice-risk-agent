# Invoice Risk Intelligence Agent

A production-grade LangGraph agent that validates, scores, and routes invoices through 5 fraud-detection gates with full observability.

---

## Architecture

```
Gmail Inbox
    |
    v
[FastAPI /invoices/process-invoice]
    |
    v
[parse_invoice node]  <-- PyPDF2 + LLM extraction
    |
    v
[gate_quality]  -- fail --> [route_invoice] --> BLOCK + Slack alert
    |
[gate_math]     -- fail --> [route_invoice] --> BLOCK + Slack alert
    |
[gate_duplicate]-- fail --> [route_invoice] --> BLOCK + Slack alert
    |
[gate_ofac]     -- fail --> [route_invoice] --> BLOCK + Slack alert (compliance)
    |
[gate_stripe]   -- fail --> [route_invoice] --> BLOCK + Slack alert
    |
    v
[llm_score]  <-- OpenAI + LangSmith trace
    |
    v
[route_invoice]
    |
    +-- auto_approve  --> Supabase (approved) + Gmail label
    |
    +-- human_review  --> Slack review card + Supabase (pending)
    |                         |
    |                   [/slack/action webhook]
    |                         |
    |                   Reviewer clicks Approve/Reject
    |                         |
    |                   Supabase update + audit log
    |
    +-- block         --> Supabase (blocked) + Slack alert
```

---

## Features

- **5-gate validation pipeline**: quality, math, duplicate, OFAC sanctions, Stripe fingerprint
- **LLM risk scoring**: OpenAI-powered composite score (0–100) with structured reasoning
- **Human-in-the-loop**: Slack interactive review cards for ambiguous cases
- **Full observability**: every agent run traced in LangSmith end-to-end
- **Append-only audit log**: every state transition persisted to Supabase
- **BEC detection**: Stripe payment fingerprint change detection for known vendors
- **OFAC sanctions screening**: real-time vendor name screening against SDN list
- **Eval suite**: 12 labeled cases (5 clean, 4 fraudulent, 3 edge) with metric reporting

---

## Stack

| Layer | Technology |
|---|---|
| Agentic orchestration | LangGraph 0.2+ |
| LLM | OpenAI GPT-4o via LangChain |
| Observability | LangSmith |
| API | FastAPI + Uvicorn |
| Schema validation | Pydantic v2 |
| Persistence | Supabase (PostgreSQL) |
| Email ingestion | Gmail API (OAuth2) |
| Human review | Slack SDK (Block Kit) |
| Payment signals | Stripe Radar |
| Sanctions screening | OFAC API v4 |
| PDF parsing | PyPDF2 |

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-org/invoice-risk-agent.git
cd invoice-risk-agent

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in all values

# 5. Run Supabase migrations (requires Supabase CLI or paste into SQL editor)
# supabase db push  OR  run each file in db/migrations/ in order (001 → 002 → 003)

# 6. Start the API server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check — returns `{"status": "ok"}` |
| POST | `/invoices/process-invoice` | Submit a PDF invoice for risk assessment |
| POST | `/slack/action` | Slack interactive action webhook (approve/reject) |
| GET | `/docs` | Swagger UI (development only) |

### POST /invoices/process-invoice

Accepts `multipart/form-data`:
- `invoice_metadata`: JSON string conforming to `InvoiceInput` schema
- `pdf_file`: PDF invoice attachment

Returns:
```json
{
  "invoice_id": "uuid",
  "routing_decision": "auto_approve | human_review | block",
  "risk_score": 42,
  "gate_results": [...]
}
```

---

## Eval Suite

Run the evaluation suite against all 12 labeled fixture cases:

```bash
python -m evals.run_evals
```

Metrics reported:
- **Routing accuracy**: % of cases where actual routing matched expected
- **Gate detection rate**: % of fraud cases caught by the correct gate
- **Score range compliance**: % of cases where LLM score fell in the expected range
- **Overall pass rate**: % of cases passing all three checks

Fixture PDFs go in `evals/fixtures/`. See `evals/fixtures/README.md` for naming conventions.
Never commit real invoice PDFs.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Built for

**Lemma x Arga Labs Hackathon — September 13, 2026**
