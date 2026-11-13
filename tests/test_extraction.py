
from io import BytesIO
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from reportlab.pdfgen import canvas

from src.schemas import InvoiceExtraction
from src.extractor import InvoiceDraft, read_pdf, extract_with_retry


def make_invoice():
    return {
        "invoice_number": "INV-1001",
        "vendor_name": "ABC Office Supplies",
        "invoice_date": "2026-10-15",
        "line_items": [
            {
                "description": "Keyboard",
                "quantity": 2,
                "unit_price": "50.00",
                "line_total": "100.00"
            },
            {
                "description": "Mouse",
                "quantity": 3,
                "unit_price": "20.00",
                "line_total": "60.00"
            }
        ],
        "subtotal": "160.00",
        "tax_amount": "0.00",
        "total_amount": "160.00",
        "currency": "USD"
    }


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.responses = self

    def parse(self, **kwargs):
        draft = InvoiceDraft.model_validate(self.data)
        return SimpleNamespace(output_parsed=draft)


def test_valid_pdf_extraction():
    # create a simple pdf
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)

    pdf.drawString(100, 750, "ABC Office Supplies")
    pdf.drawString(100, 730, "Invoice: INV-1001")
    pdf.drawString(100, 710, "Total: $160.00")
    pdf.save()

    # read the pdf
    raw_text = read_pdf(buffer.getvalue())

    assert "INV-1001" in raw_text

    # simulate a correct ai response
    client = FakeClient(make_invoice())

    result = extract_with_retry(raw_text, client=client)

    assert result.execution_status == "SUCCESS"
    assert result.attempts_used == 1
    assert len(result.error_log) == 0
    assert result.validated_data.total_amount == 160


def test_invalid_quantity():
    invoice = make_invoice()
    invoice["line_items"][0]["quantity"] = 0

    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(invoice)


def test_negative_total():
    invoice = make_invoice()
    invoice["total_amount"] = "-10.00"

    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(invoice)


def test_incorrect_invoice_total():
    invoice = make_invoice()
    invoice["total_amount"] = "200.00"

    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(invoice)
