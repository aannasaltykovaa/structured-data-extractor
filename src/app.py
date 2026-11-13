import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
from types import SimpleNamespace

import streamlit as st

from src.extractor import (
    InvoiceDraft,
    extract_with_retry,
    read_pdf,
    read_html
)


st.set_page_config(
    page_title="Invoice Extractor",
    layout="wide"
)

st.title("Invoice Data Extractor")
st.write("Extract and validate invoice information using AI.")

# choose an input method
input_type = st.radio(
    "Choose input type:",
    ["Paste Text or HTML", "Upload PDF"]
)

uploaded_file = None
text_input = ""

if input_type == "Upload PDF":
    uploaded_file = st.file_uploader(
        "Choose a PDF invoice",
        type=["pdf"]
    )
else:
    text_input = st.text_area(
        "Paste invoice text or HTML:",
        height=200,
        placeholder="Paste your invoice here..."
    )

# enable or disable automatic correction
reflection = st.toggle(
    "Enable AI Self-Correction",
    value=True
)

# main extraction button
if st.button("Extract Invoice"):

    raw_text = ""

    if input_type == "Upload PDF":

        if uploaded_file is not None:
            try:
                raw_text = read_pdf(uploaded_file.getvalue())
            except Exception as error:
                st.error(f"Could not read PDF: {error}")

    else:
        if text_input.strip():
            if "<" in text_input and ">" in text_input:
                raw_text = read_html(text_input)
            else:
                raw_text = text_input

    if not raw_text.strip():
        st.warning("Please provide a readable invoice.")
    else:
        try:
            with st.spinner("Extracting invoice..."):
                result = extract_with_retry(
                    raw_text,
                    max_retries=3,
                    enable_reflection=reflection
                )

            st.session_state["result"] = result
            st.session_state["raw_text"] = raw_text

        except Exception as error:
            st.error(f"Extraction error: {error}")


# simulated incorrect ai responses
class SimulatedFailureClient:

    def __init__(self):
        self.responses = self

    def parse(self, **kwargs):

        bad_invoice = InvoiceDraft(
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
            total_amount="200.00",
            currency="USD"
        )

        return SimpleNamespace(output_parsed=bad_invoice)


st.divider()

st.subheader("Failure Simulation")

st.write(
    "This simulation returns an incorrect invoice total "
    "on every attempt to test the DLQ fallback."
)

if st.button("Simulate Edge Case Failure"):

    with st.spinner("Testing failure handling..."):
        result = extract_with_retry(
            "Simulated invoice with incorrect total",
            max_retries=3,
            client=SimulatedFailureClient()
        )

    st.session_state["result"] = result
    st.session_state["raw_text"] = (
        "Simulated invoice with incorrect total"
    )


# display results
if "result" in st.session_state:

    result = st.session_state["result"]
    raw_text = st.session_state["raw_text"]

    st.divider()
    st.header("Extraction Results")

    st.write("Status:", result.execution_status)
    st.write("Attempts used:", result.attempts_used)

    left, right = st.columns(2)

    with left:
        st.subheader("Original Document")
        st.text_area(
            "Document text",
            value=raw_text,
            height=350,
            disabled=True
        )

    with right:
        st.subheader("Validated JSON")

        if result.validated_data is not None:

            data = json.loads(
                result.validated_data.model_dump_json()
            )

            st.json(data)

            st.success(
                "Reconciliation Passed: "
                "Invoice totals match."
            )

        else:
            st.error("Extraction failed validation.")

            if result.dlq_file:
                st.write(
                    "Failed record saved to:",
                    result.dlq_file
                )

    st.subheader("Validation and Retry Log")

    if not result.error_log:
        st.success("No validation errors found.")

    for error in result.error_log:
        st.code(error, language="text")

    if result.corrective_prompts:
        with st.expander("View Corrective Prompts"):
            for prompt in result.corrective_prompts:
                st.code(prompt, language="text")
