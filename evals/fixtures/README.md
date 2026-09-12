# Eval Fixtures

Place PDF test invoices here. All filenames must match the IDs in `evals/labeled_cases.py`.

## Required fixtures

| Filename               | Category    | Description                                      |
|------------------------|-------------|--------------------------------------------------|
| `clean_001.pdf`        | Clean       | Trusted repeat vendor, all fields valid          |
| `clean_002.pdf`        | Clean       | New vendor, first invoice, PO reference present  |
| `clean_003.pdf`        | Clean       | High-value invoice from trusted vendor           |
| `clean_004.pdf`        | Clean       | Multi-line international invoice (Kenyan vendor) |
| `clean_005.pdf`        | Clean       | No PO reference, otherwise complete              |
| `fraud_ofac_001.pdf`   | Fraudulent  | Vendor name matches OFAC SDN list entity         |
| `fraud_math_001.pdf`   | Fraudulent  | Line total does not match quantity × unit_price  |
| `fraud_duplicate_001.pdf` | Fraudulent | Duplicate of a previously approved invoice    |
| `fraud_bec_001.pdf`    | Fraudulent  | Known vendor, bank account fingerprint changed   |
| `edge_001.pdf`         | Edge        | Partial OFAC name match (below hard threshold)   |
| `edge_002.pdf`         | Edge        | New vendor, very high amount, elevated Radar     |
| `edge_003.pdf`         | Edge        | Stale invoice (89 days old), high vs. average    |

## Rules

- **NEVER commit real invoice PDFs to git.** Real invoices contain PII and sensitive financial data.
- Use synthetically generated PDFs for all fixtures. Tools like `fpdf2` or `reportlab` can generate
  realistic-looking invoice PDFs with controlled content.
- Fixture PDFs are excluded from git by the root `.gitignore` (`*.pdf` rule).
- If you need to share fixtures with a team member, use an encrypted archive or a private cloud
  folder — not a public repository or email attachment.
