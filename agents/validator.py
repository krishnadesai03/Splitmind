"""
agents/validator.py — Agent 2: Validator

Computes the subtotal from extracted item prices ourselves (not trusting
Claude's stated subtotal), then checks:

    sum(item.price × item.quantity) + tax + tip  ≈  stated total  (±$0.02)

If the check fails, retries Agent 1 with a targeted correction prompt that
tells the model exactly which numbers didn't add up. Max 2 retries.
"""
from __future__ import annotations

import dataclasses

from agents.extractor import ExtractedBill, extract

_TOLERANCE   = 0.02
_MAX_RETRIES = 2


def _items_subtotal(bill: ExtractedBill) -> float:
    # `price` is the line total (unit × qty) per the extractor's tool schema,
    # so we sum prices directly — multiplying by quantity again would double-count.
    return round(sum(i.price for i in bill.items), 2)


def validate(
    bill:       ExtractedBill,
    route:      str,
    text:       str   | None = None,
    file_bytes: bytes | None = None,
    file_type:  str   | None = None,
) -> tuple[ExtractedBill, list[str]]:
    """
    Validate by computing subtotal from item prices, not from Claude's
    extracted subtotal field.

    Returns (validated_bill, attempt_log).
    attempt_log entries are shown inside the st.status box in the UI.
    """
    attempt_log: list[str] = []

    for attempt in range(_MAX_RETRIES + 1):
        calc_subtotal = _items_subtotal(bill)
        calc_total    = round(calc_subtotal + bill.tax + bill.tip, 2)
        discrepancy   = round(abs(calc_total - bill.total), 2)

        if discrepancy <= _TOLERANCE:
            attempt_log.append(
                f"✓ Sum of items ${calc_subtotal:.2f} + "
                f"tax ${bill.tax:.2f} + tip ${bill.tip:.2f} = "
                f"${calc_total:.2f} ≈ stated total ${bill.total:.2f}"
            )
            return dataclasses.replace(bill, validation_passed=True, validation_note=None), attempt_log

        fail_note = (
            f"Attempt {attempt + 1}: sum of extracted items = ${calc_subtotal:.2f}, "
            f"+ tax ${bill.tax:.2f} + tip ${bill.tip:.2f} = ${calc_total:.2f} "
            f"≠ stated total ${bill.total:.2f} (off by ${discrepancy:.2f})"
        )
        attempt_log.append(fail_note)

        if attempt == _MAX_RETRIES:
            break

        correction = (
            f"The sum of the extracted item prices is ${calc_subtotal:.2f} "
            f"(receipt states subtotal ${bill.subtotal:.2f}). "
            f"Adding tax ${bill.tax:.2f} and tip ${bill.tip:.2f} gives ${calc_total:.2f}, "
            f"but the receipt's stated total is ${bill.total:.2f} "
            f"(discrepancy: ${discrepancy:.2f}). "
            "Re-examine each line item price carefully — "
            "one or more prices were likely misread from the receipt."
        )

        bill = extract(
            route=route,
            text=text,
            file_bytes=file_bytes,
            file_type=file_type,
            correction=correction,
        )

    calc_subtotal = _items_subtotal(bill)
    calc_total    = round(calc_subtotal + bill.tax + bill.tip, 2)
    return dataclasses.replace(
        bill,
        validation_passed=False,
        validation_note=(
            f"Could not reconcile after {_MAX_RETRIES} "
            f"retr{'y' if _MAX_RETRIES == 1 else 'ies'}: "
            f"item sum ${calc_subtotal:.2f} + tax ${bill.tax:.2f} = "
            f"${calc_total:.2f} vs stated total ${bill.total:.2f}. "
            "The image may be blurry — please check prices manually."
        ),
    ), attempt_log
