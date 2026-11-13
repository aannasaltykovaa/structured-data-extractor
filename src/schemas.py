
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    line_total: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def check_line_total(self):
        expected = self.quantity * self.unit_price

        if abs(expected - self.line_total) > Decimal("0.02"):
            raise ValueError("Line item total does not match")

        return self


class InvoiceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9/-]+$"
    )
    vendor_name: str = Field(min_length=1)
    invoice_date: date
    line_items: list[LineItem] = Field(min_length=1)
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    total_amount: Decimal = Field(ge=0)
    currency: Literal["USD", "EUR", "GBP"]

    @model_validator(mode="after")
    def check_invoice_totals(self):
        item_total = sum(
            (item.line_total for item in self.line_items),
            Decimal("0")
        )

        if abs(item_total - self.subtotal) > Decimal("0.02"):
            raise ValueError("Subtotal does not match line items")

        expected_total = self.subtotal + self.tax_amount

        if abs(expected_total - self.total_amount) > Decimal("0.02"):
            raise ValueError("Invoice total does not match")

        return self
