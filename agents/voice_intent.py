"""
agents/voice_intent.py — Conversational voice assignment: intent parsing

Each turn, the user speaks who an item should be split between (already
transcribed to text by services/whisper.py). This maps that free-form
transcript onto the canonical participant list for the current item.
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
                    "canonical participants (unrecognized name, unclear speech, "
                    "or no names mentioned at all)."
                ),
            },
        },
        "required": ["matched_participants", "needs_clarification"],
        "additionalProperties": False,
    },
}


@dataclass
class VoiceIntent:
    matched_participants: list[str]
    needs_clarification:  bool


def parse_assignment(
    transcript:   str,
    item_name:    str,
    participants: list[str],
) -> VoiceIntent:
    """
    Map a spoken response to a subset of the canonical participant list.

    Args:
        transcript:   Whisper transcript of the user's spoken response.
        item_name:    The item currently being assigned (for context).
        participants: Canonical list of participant names to match against.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = (
        f"The current bill item being assigned is: \"{item_name}\".\n"
        f"The participants in this bill split are: {', '.join(participants)}.\n\n"
        f"The user just said: \"{transcript}\"\n\n"
        "Map this response to the exact participant name(s) from the list above "
        "that should share this item. Names may be spoken informally (nicknames, "
        "\"me\", \"everyone\", \"all of us\", etc.) — use context to match them to "
        "the canonical list. \"Me\" refers to the bill owner, which is always the "
        f"first name in the list (\"{participants[0]}\") if present.\n"
        "If the response mentions a name that doesn't match anyone in the list, "
        "or is unclear/silent, set needs_clarification to true and return whatever "
        "matches you're confident about (possibly none)."
    )

    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=256,
        response_format={"type": "json_schema", "json_schema": _INTENT_SCHEMA},
        messages=[{"role": "user", "content": prompt}],
    )
    data = json.loads(response.choices[0].message.content)

    matched = [p for p in data.get("matched_participants", []) if p in participants]
    return VoiceIntent(
        matched_participants=matched,
        needs_clarification=bool(data.get("needs_clarification")) or not matched,
    )
