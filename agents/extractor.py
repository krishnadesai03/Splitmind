"""
agents/extractor.py — Agent 1: Item Extractor

Two extraction paths, both using Claude tool use for guaranteed structured output:
  - Vision path  : claude-sonnet-4-6 + image/PDF bytes  (for file attachments)
  - Text path    : claude-sonnet-4-6 + plain text        (for typed/pasted bills)

Both prompts use chain-of-thought: identify receipt type → list every item →
find subtotal / tax / tip / total.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Output types ──────────────────────────────────────────────────────────────

@dataclass
class BillItem:
    name:     str
    price:    float
    quantity: int = 1


@dataclass
class ExtractedBill:
    items:             list[BillItem]
    subtotal:          float
    tax:               float
    tip:               float
    total:             float
    validation_passed: bool
    validation_note:   str | None = None


# ── Shared tool definition ────────────────────────────────────────────────────

_PARSE_TOOL = {
    "name": "parse_bill",
    "description": (
        "Extract all line items, prices, tax, tip, and total from a bill or receipt. "
        "Do NOT include tax or tip as line items."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Every purchased line item (exclude tax and tip rows)",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":     {"type": "string",  "description": "Item name as written on the bill"},
                        "price":    {"type": "number",  "description": "Total price for this line (unit price × quantity)"},
                        "quantity": {"type": "integer", "description": "Quantity ordered, default 1"},
                    },
                    "required": ["name", "price", "quantity"],
                },
            },
            "subtotal": {"type": "number", "description": "Sum of all item prices before tax/tip"},
            "tax":      {"type": "number", "description": "Tax amount — 0 if not present"},
            "tip":      {"type": "number", "description": "Tip or gratuity amount — 0 if not present"},
            "total":    {"type": "number", "description": "Final total as shown on the bill"},
        },
        "required": ["items", "subtotal", "tax", "tip", "total"],
    },
}

_COT_SUFFIX = (
    "\n\nThink step by step before calling the tool:\n"
    "1. What type of bill/receipt is this?\n"
    "2. List every line item with its name, price, and quantity.\n"
    "3. Identify the subtotal, tax, tip, and final total separately.\n"
    "Do NOT include tax or tip as items in the items array."
)


# ── Vision path ───────────────────────────────────────────────────────────────

def _extract_from_image(file_bytes: bytes, file_type: str, correction: str | None = None) -> ExtractedBill:
    client     = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    image_data = base64.standard_b64encode(file_bytes).decode()

    base_text = "Parse this receipt and extract all items, prices, tax, tip, and total." + _COT_SUFFIX
    if correction:
        base_text += f"\n\nCorrection needed: {correction}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[_PARSE_TOOL],
        tool_choice={"type": "tool", "name": "parse_bill"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": file_type, "data": image_data},
                },
                {"type": "text", "text": base_text},
            ],
        }],
    )
    return _build_result(response)


# ── Text path ─────────────────────────────────────────────────────────────────

def _extract_from_text(text: str, correction: str | None = None) -> ExtractedBill:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    correction_block = f"\n\nCorrection from previous attempt: {correction}" if correction else ""

    prompt = (
        "Extract all items and financial totals from the bill description below.\n\n"
        "Fill in the parse_bill tool with:\n"
        "- items: every purchased item (food, drinks, products, services). "
        "Do NOT include tax or tip here.\n"
        "- subtotal: sum of all item prices\n"
        "- tax: tax amount, 0 if not mentioned\n"
        "- tip: tip or gratuity, 0 if not mentioned\n"
        "- total: final amount (calculate as subtotal + tax + tip if not stated)\n"
        "- Default quantity to 1 unless explicitly stated otherwise\n"
        f"{correction_block}\n\n"
        f"Bill:\n{text}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[_PARSE_TOOL],
        tool_choice={"type": "tool", "name": "parse_bill"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _build_result(response)


# ── Shared result builder ─────────────────────────────────────────────────────

def _build_result(response: anthropic.types.Message) -> ExtractedBill:
    tool_block = next(b for b in response.content if b.type == "tool_use")
    data       = tool_block.input

    items    = [BillItem(**item) for item in data.get("items", [])]
    subtotal = round(float(data.get("subtotal", 0)), 2)
    tax      = round(float(data.get("tax",      0)), 2)
    tip      = round(float(data.get("tip",      0)), 2)
    total    = round(float(data.get("total", subtotal + tax + tip)), 2)

    calculated        = round(subtotal + tax + tip, 2)
    validation_passed = abs(calculated - total) <= 0.10
    validation_note   = (
        f"Mismatch: items + tax + tip = ${calculated:.2f}, stated total = ${total:.2f}"
        if not validation_passed else None
    )

    return ExtractedBill(
        items=items,
        subtotal=subtotal,
        tax=tax,
        tip=tip,
        total=total,
        validation_passed=validation_passed,
        validation_note=validation_note,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def extract(
    route:      str,
    text:       str   | None = None,
    file_bytes: bytes | None = None,
    file_type:  str   | None = None,
    correction: str   | None = None,
) -> ExtractedBill:
    """
    Run the correct extraction path based on Agent 0's routing decision.

    Args:
        route:      Route name from the router ("vision_pipeline" or "text_pipeline").
        text:       Typed/pasted bill text (text_pipeline).
        file_bytes: Raw file bytes (vision_pipeline).
        file_type:  MIME type of the file (vision_pipeline).
    """
    if route == "vision_pipeline":
        if not file_bytes or not file_type:
            raise ValueError("vision_pipeline requires file_bytes and file_type")
        return _extract_from_image(file_bytes, file_type, correction=correction)

    if route in ("text_pipeline", "whisper_then_text_pipeline"):
        if not text:
            raise ValueError(f"{route} requires text input")
        return _extract_from_text(text, correction=correction)

    raise ValueError(f"Unknown route: {route!r}")
