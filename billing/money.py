"""
Monetary precision and rounding module for Subscript Billing.

Financial Rules:
1. Float is strictly forbidden across all calculations, services, and tests.
2. All money amounts are Decimal with max 12 digits and 2 decimal places.
3. quantize_money() rounds using ROUND_HALF_UP to 0.01.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Union

TWOPLACES = Decimal("0.01")


def quantize_money(amount: Union[Decimal, str, int]) -> Decimal:
    """
    Quantizes an amount to two decimal places using ROUND_HALF_UP.
    Raises TypeError if a float is passed.
    """
    if isinstance(amount, float):
        raise TypeError(
            f"Float value {amount!r} passed to quantize_money. "
            "Float arithmetic is strictly forbidden in Subscript. Use Decimal or str."
        )
    if isinstance(amount, (int, str)):
        amount = Decimal(str(amount))
    elif not isinstance(amount, Decimal):
        raise TypeError(
            f"Unsupported type {type(amount).__name__} for monetary calculation. "
            "Expected Decimal, int, or str."
        )

    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def calculate_line_subtotal(quantity: int, unit_price: Union[Decimal, str]) -> Decimal:
    """
    Computes line_subtotal = quantity x unit_price, quantized to 2 decimal places.
    """
    qty = Decimal(str(quantity))
    price = quantize_money(unit_price)
    return quantize_money(qty * price)


def calculate_line_tax(line_subtotal: Decimal, tax_rate: Union[Decimal, str]) -> Decimal:
    """
    Computes line_tax = line_subtotal x tax_rate / 100, quantized to 2 decimal places.
    """
    subtotal = quantize_money(line_subtotal)
    rate = quantize_money(tax_rate)
    return quantize_money(subtotal * (rate / Decimal("100.00")))


def calculate_line_total(line_subtotal: Decimal, line_tax: Decimal) -> Decimal:
    """
    Computes line_total = line_subtotal + line_tax, quantized to 2 decimal places.
    """
    return quantize_money(quantize_money(line_subtotal) + quantize_money(line_tax))
