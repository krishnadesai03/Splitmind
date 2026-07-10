"""
agents/voice_intent.py — Conversational voice assignment: intent parsing

Each turn, the user speaks who an item (or several items) should be split
between (already transcribed to text by services/whisper.py). This maps that
free-form transcript onto the canonical participant list, and onto one or
more of the still-unassigned bill items — supporting not just "the current
item" but references like "this and the next two", "the rest of the items",
or a specific item by name ("the tomatoes").
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_MODEL = "gpt-4o-mini"

_INTENT_SCHEMA = {
    "name": "parse_assignment_intent",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "item_indices": {
                "type": "array",
                "description": (
                    "The 'index' value(s) from the provided pending-items list that "
                    "this response assigns. Almost always just the current item's "
                    "index, but include more when the user references multiple items "
                    "(\"this and the next two\", \"the rest of the items\", a specific "
                    "item mentioned by name)."
                ),
                "items": {"type": "integer"},
            },
            "matched_participants": {
                "type": "array",
                "description": (
                    "Participant names from the canonical list that the user's "
                    "response refers to. Must be exact strings from the provided list."
                ),
                "items": {"type": "string"},
            },
            "needs_clarification": {
                "type": "boolean",
                "description": (
                    "True if the response didn't clearly map to one or more "
                    "canonical participants, or to at least one pending item "
                    "(unrecognized name, unclear speech, or nothing usable said)."
                ),
            },
        },
        "required": ["item_indices", "matched_participants", "needs_clarification"],
        "additionalProperties": False,
    },
}


@dataclass
class VoiceIntent:
    item_indices:          list[int]
    matched_participants:  list[str]
    needs_clarification:   bool


def parse_assignment(
    transcript:    str,
    pending_items: list[dict],
    participants:  list[str],
) -> VoiceIntent:
    """
    Map a spoken response to (a) one or more of the still-unassigned bill
    items and (b) a subset of the canonical participant list.

    Args:
        transcript:    Whisper transcript of the user's spoken response.
        pending_items: Unassigned items in prompting order, each
                        {"index": int, "name": str, "price": float}. The
                        first entry is the "current"/"this" item.
        participants:  Canonical list of participant names to match against.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    valid_indices = {it["index"] for it in pending_items}
    items_desc = "\n".join(
        f"- index {it['index']}: {it['name']} (${it['price']:.2f})"
        + ("  ← this is the current item, referred to as \"this\"/\"it\"" if i == 0 else "")
        for i, it in enumerate(pending_items)
    )

    prompt = (
        f"Items still waiting to be assigned, in the order they'd be asked about "
        f"(the first one is the current item):\n{items_desc}\n\n"
        f"The participants in this bill split are: {', '.join(participants)}.\n\n"
        f"The user just said: \"{transcript}\"\n\n"
        "Figure out which of the items above this response assigns, and to whom:\n"
        "- \"this\" / \"it\" / no item mentioned at all → just the current item.\n"
        "- \"this and the next N items\" / \"this and the following N\" → the current "
        "item plus the next N items listed above, in order.\n"
        "- \"the rest\" / \"everything else\" / \"all of it\" → every item listed above.\n"
        "- A specific item referenced by name (e.g. \"the tomatoes\") → match it "
        "(loosely/partially is fine) against the item names above. If the user says "
        "\"this and <item name>\", include both the current item and that one.\n"
        "Return the matching 'index' values from the list above.\n\n"
        "For participants: names may be spoken informally (nicknames, \"me\", "
        "\"everyone\", \"all of us\", etc.) — use context to match them to the "
        "canonical list. \"Me\" refers to the bill owner, which is always the first "
        f"name in the list (\"{participants[0]}\") if present.\n"
        "If you can't confidently determine the item(s) or the participant(s), set "
        "needs_clarification to true and return whatever you're confident about "
        "(possibly nothing)."
    )

    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=256,
        response_format={"type": "json_schema", "json_schema": _INTENT_SCHEMA},
        messages=[{"role": "user", "content": prompt}],
    )
    data = json.loads(response.choices[0].message.content)

    item_indices = [i for i in data.get("item_indices", []) if i in valid_indices]
    matched      = [p for p in data.get("matched_participants", []) if p in participants]

    return VoiceIntent(
        item_indices=item_indices,
        matched_participants=matched,
        needs_clarification=bool(data.get("needs_clarification")) or not matched or not item_indices,
    )
