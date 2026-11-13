
import json
from pathlib import Path
from types import SimpleNamespace

from src.extractor import InvoiceDraft, extract_with_retry


class FakeClient:
    def __init__(self, drafts):
        self.drafts = iter(drafts)
        self.responses = self

    def parse(self, **kwargs):
        draft = next(self.drafts)
        return SimpleNamespace(output_parsed=draft)


def make_invoice(total="160.00"):
    return InvoiceDraft(
        invoice_number="INV-1001",
        vendor_name="ABC Office Supplies",
        invoice_date="2026-10-15",
        line_items=[
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
        subtotal="160.00",
        tax_amount="0.00",
        total_amount=total,
        currency="USD"
    )


def test_reflection_success(monkeypatch):
    monkeypatch.setattr("src.extractor.time.sleep", lambda x: None)

    bad_invoice = make_invoice("200.00")
    good_invoice = make_invoice("160.00")

    client = FakeClient([bad_invoice, good_invoice])

    result = extract_with_retry(
        "Sample invoice",
        max_retries=3,
        client=client
    )

    assert result.execution_status == "REPAIRED_VIA_REFLECTION"
    assert result.attempts_used == 2
    assert result.validated_data.total_amount == 160
    assert len(result.corrective_prompts) == 1


def test_dlq_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.extractor.time.sleep", lambda x: None)

    bad_invoice = make_invoice("200.00")

    client = FakeClient([bad_invoice] * 3)

    result = extract_with_retry(
        "Sample invoice",
        max_retries=3,
        client=client
    )

    assert result.execution_status == "DLQ_FAILED"
    assert result.attempts_used == 3
    assert result.validated_data is None
    assert Path(result.dlq_file).exists()

    with open(result.dlq_file) as file:
        saved = json.load(file)

    assert saved["status"] == "DLQ_FAILED"
