
import json
import time
from io import BytesIO
from typing import Literal

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError
from pypdf import PdfReader

from src.schemas import InvoiceExtraction
from src.fallback import (
    build_reflection_prompt,
    repair_json_payload,
    save_to_dlq
)


load_dotenv()


def read_pdf(file_bytes):
    reader = PdfReader(BytesIO(file_bytes))
    text = ""

    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"

    return text


def read_html(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


class LineItemDraft(BaseModel):
    description: str
    quantity: int
    unit_price: str
    line_total: str


class InvoiceDraft(BaseModel):
    invoice_number: str
    vendor_name: str
    invoice_date: str
    line_items: list[LineItemDraft]
    subtotal: str
    tax_amount: str
    total_amount: str
    currency: str


class ExtractionResult(BaseModel):
    validated_data: InvoiceExtraction | None
    attempts_used: int
    error_log: list[str]
    corrective_prompts: list[str]
    execution_status: Literal[
        "SUCCESS",
        "REPAIRED_VIA_REFLECTION",
        "DLQ_FAILED"
    ]
    dlq_file: str | None = None


def extract_with_retry(raw_text, max_retries=3,
                       enable_reflection=True, client=None):

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    if client is None:
        client = OpenAI()

    error_log = []
    corrective_prompts = []
    last_json = ""

    attempts_limit = max_retries if enable_reflection else 1

    messages = [
        {
            "role": "system",
            "content": (
                "Extract invoice information from the document. "
                "Return dates in YYYY-MM-DD format. "
                "Return monetary values as numeric strings. "
                "Do not invent missing information. "
                "Use 0 for tax if no tax is listed."
            )
        },
        {
            "role": "user",
            "content": raw_text
        }
    ]

    for attempt in range(1, attempts_limit + 1):

        try:
            response = client.responses.parse(
                model="gpt-4o-mini",
                input=messages,
                text_format=InvoiceDraft
            )

            draft = response.output_parsed

            if draft is None:
                raise ValueError("No invoice data returned")

            last_json = draft.model_dump_json()

            invoice = InvoiceExtraction.model_validate(
                draft.model_dump()
            )

            if attempt == 1:
                status = "SUCCESS"
            else:
                status = "REPAIRED_VIA_REFLECTION"

            return ExtractionResult(
                validated_data=invoice,
                attempts_used=attempt,
                error_log=error_log,
                corrective_prompts=corrective_prompts,
                execution_status=status
            )

        except (ValidationError, ValueError, OpenAIError) as error:

            if isinstance(error, ValidationError):
                details = [
                    {
                        "field": ".".join(
                            str(part) for part in item["loc"]
                        ),
                        "message": item["msg"]
                    }
                    for item in error.errors()
                ]
                error_text = json.dumps(details, indent=2)
            else:
                error_text = str(error)

            error_log.append(
                f"Attempt {attempt}: {error_text}"
            )

            if attempt < attempts_limit:

                if isinstance(error, ValidationError):
                    prompt = build_reflection_prompt(
                        raw_text,
                        last_json,
                        error_text
                    )

                    corrective_prompts.append(prompt)

                    messages.append({
                        "role": "user",
                        "content": prompt
                    })

                time.sleep(min(2 ** (attempt - 1), 4))

    # try repairing json formatting after retries fail
    if last_json:
        repaired = repair_json_payload(last_json)

        if isinstance(repaired, dict):
            try:
                invoice = InvoiceExtraction.model_validate(
                    repaired
                )

                return ExtractionResult(
                    validated_data=invoice,
                    attempts_used=attempts_limit,
                    error_log=error_log,
                    corrective_prompts=corrective_prompts,
                    execution_status="REPAIRED_VIA_REFLECTION"
                )

            except ValidationError as error:
                error_log.append(
                    f"Fallback validation: {error}"
                )

    # save failures for manual review
    filename = save_to_dlq(
        raw_text,
        last_json,
        error_log
    )

    return ExtractionResult(
        validated_data=None,
        attempts_used=attempts_limit,
        error_log=error_log,
        corrective_prompts=corrective_prompts,
        execution_status="DLQ_FAILED",
        dlq_file=filename
    )


def extract_invoice(raw_text):
    result = extract_with_retry(raw_text)

    if result.validated_data is None:
        raise ValueError(
            f"Extraction failed. Saved to {result.dlq_file}"
        )

    return result.validated_data


if __name__ == "__main__":

    sample = """
    ABC Office Supplies
    Invoice: INV-1001
    Date: October 15, 2026
    Currency: USD

    Keyboard: 2 x $50.00 = $100.00
    Mouse: 3 x $20.00 = $60.00

    Subtotal: $160.00
    Tax: $0.00
    Total: $160.00
    """

    result = extract_with_retry(sample)

    print("Status:", result.execution_status)
    print("Attempts:", result.attempts_used)

    if result.validated_data is not None:
        print(result.validated_data.model_dump_json(indent=2))
    else:
        print("Failed extraction saved to:", result.dlq_file)
        print("Errors:", result.error_log)
