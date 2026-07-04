"""
agents/router.py — Agent 0: Router

Classifies every user submission into one of three routes:
  - vision_pipeline              (image or PDF file)
  - whisper_then_text_pipeline   (audio file)
  - text_pipeline                (typed text or URL)

File inputs are routed by MIME type (no LLM needed — deterministic).
Text inputs use a lightweight Haiku call to detect URLs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import anthropic
from dotenv import load_dotenv

load_dotenv()

InputType = Literal["image", "pdf", "audio", "text", "url"]
RouteName  = Literal["vision_pipeline", "whisper_then_text_pipeline", "text_pipeline"]


@dataclass
class RouteDecision:
    input_type:   InputType
    route:        RouteName
    status_label: str  # shown in the UI status indicator


# ── Tool definition for text classification ───────────────────────────────────
_CLASSIFY_TOOL = {
    "name": "classify_text_input",
    "description": "Classify a text input as either a URL (to fetch) or plain bill text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contains_url": {
                "type": "boolean",
                "description": "True if the text contains an http/https URL",
            },
            "url": {
                "type": "string",
                "description": "The URL if present, otherwise an empty string",
            },
        },
        "required": ["contains_url", "url"],
    },
}

# ── MIME type → route mapping ─────────────────────────────────────────────────
_MIME_ROUTES: dict[str, tuple[InputType, RouteName, str]] = {
    "image/jpeg":      ("image", "vision_pipeline", "📷 Receipt image → vision pipeline"),
    "image/png":       ("image", "vision_pipeline", "📷 Receipt image → vision pipeline"),
    "image/webp":      ("image", "vision_pipeline", "📷 Receipt image → vision pipeline"),
    "image/gif":       ("image", "vision_pipeline", "📷 Receipt image → vision pipeline"),
    "application/pdf": ("pdf",   "vision_pipeline", "📄 PDF receipt → vision pipeline"),
}


# ── Public API ─────────────────────────────────────────────────────────────────
def route(
    text:       str   | None = None,
    file_bytes: bytes | None = None,
    file_type:  str   | None = None,
) -> RouteDecision:
    """
    Classify the user's submission and return a RouteDecision.

    Args:
        text:       Typed/pasted text from the user (may be None if file attached).
        file_bytes: Raw bytes of an uploaded file (may be None if text input).
        file_type:  MIME type of the uploaded file (e.g. "image/jpeg").

    Returns:
        RouteDecision with input_type, route, and a UI status label.
    """
    # ── File inputs: deterministic MIME-type routing ──────────────────────────
    if file_bytes and file_type:
        if file_type in _MIME_ROUTES:
            input_type, route_name, label = _MIME_ROUTES[file_type]
            return RouteDecision(input_type, route_name, label)

        if file_type.startswith("audio/"):
            return RouteDecision(
                "audio",
                "whisper_then_text_pipeline",
                "🎤 Voice note → Whisper transcription → text pipeline",
            )

        # Unknown file type — fall through to text pipeline
        return RouteDecision("text", "text_pipeline", "📝 Unknown file type → text pipeline")

    # ── Text input: lightweight Claude call to detect URLs ────────────────────
    if text:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            tools=[_CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_text_input"},
            messages=[{
                "role": "user",
                "content": f"Classify this input:\n\n{text[:500]}",
            }],
        )

        data = next(b for b in response.content if b.type == "tool_use").input

        if data.get("contains_url"):
            return RouteDecision(
                "url",
                "text_pipeline",
                "🔗 URL detected → scrape page → text pipeline",
            )

        return RouteDecision("text", "text_pipeline", "📝 Bill text → text pipeline")

    raise ValueError("Router received no valid input (text and file_bytes are both empty)")
