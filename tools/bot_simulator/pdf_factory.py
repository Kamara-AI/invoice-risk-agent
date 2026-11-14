"""Build tiny, valid, text-bearing PDFs without a third-party dependency.

Why not fpdf/reportlab: the simulator needs exactly one kind of document (a
readable non-invoice, to prove 422 not_an_invoice), and adding a PDF library
to Kagua's runtime requirements for that is not worth it. The PDF format for
one page of Helvetica text is ~30 lines.
"""

from __future__ import annotations


def _escape(text: str) -> str:
    """Escape the three characters that are special inside a PDF string literal."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_text_pdf(lines: list[str]) -> bytes:
    """Return a one-page PDF whose extractable text is `lines`, top to bottom.

    Args:
        lines: Plain ASCII lines of text.

    Returns:
        PDF bytes starting with "%PDF-1.4".
    """
    text_ops = ["BT", "/F1 12 Tf", "14 TL", "72 740 Td"]
    for line in lines:
        text_ops.append(f"({_escape(line)}) Tj T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(pdf)


# A readable document that is clearly NOT a request for payment.
NEWSLETTER_LINES = [
    "VENDOR MONTHLY NEWSLETTER - NOVEMBER",
    "Thank you for being a valued customer.",
    "Our offices will close early on Friday for the staff party.",
    "New product catalogue coming in December. No payment is requested.",
]
