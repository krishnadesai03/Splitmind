import anthropic
import base64
import os
from dotenv import load_dotenv
from ..models.schemas import ParsedReceipt, ReceiptItem

load_dotenv()

_PARSE_RECEIPT_TOOL = {
    "name": "parse_receipt",
    "description": "Extract all line items, prices, tax, tip, and total from a receipt image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "All line items on the receipt",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":     {"type": "string",  "description": "Item name as printed"},
                        "price":    {"type": "number",  "description": "Total price for this line (unit price × quantity)"},
                        "quantity": {"type": "integer", "description": "Quantity, default 1"},
                    },
                    "required": ["name", "price", "quantity"],
                },
            },
            "subtotal": {"type": "number", "description": "Sum of all item prices before tax/tip"},
            "tax":      {"type": "number", "description": "Tax amount, 0 if not shown"},
            "tip":      {"type": "number", "description": "Tip amount, 0 if not shown"},
            "total":    {"type": "number", "description": "Final total as printed on the receipt"},
        },
        "required": ["items", "subtotal", "tax", "tip", "total"],
    },
}


def parse_receipt_image(image_bytes: bytes, media_type: str = "image/jpeg") -> ParsedReceipt:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[_PARSE_RECEIPT_TOOL],
        tool_choice={"type": "tool", "name": "parse_receipt"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {
                    "type": "text",
                    "text": (
                        "Parse this receipt. Extract every line item, its price, and quantity. "
                        "Also extract subtotal, tax, tip, and total. Use 0 for tax/tip if not shown."
                    ),
                },
            ],
        }],
    )

    # Tool use guarantees structured data — no JSON parsing needed
    tool_block = next(b for b in message.content if b.type == "tool_use")
    data = tool_block.input

    items    = [ReceiptItem(**item) for item in data.get("items", [])]
    subtotal = round(float(data.get("subtotal", 0)), 2)
    tax      = round(float(data.get("tax", 0)), 2)
    tip      = round(float(data.get("tip", 0)), 2)
    total    = round(float(data.get("total", subtotal + tax + tip)), 2)

    calculated = round(subtotal + tax + tip, 2)
    validation_passed = abs(calculated - total) <= 0.10
    validation_note = (
        f"Mismatch: items+tax+tip=${calculated}, stated total=${total}"
        if not validation_passed else None
    )

    return ParsedReceipt(
        items=items,
        subtotal=subtotal,
        tax=tax,
        tip=tip,
        total=total,
        validation_passed=validation_passed,
        validation_note=validation_note,
    )
