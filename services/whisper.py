"""
services/whisper.py — OpenAI Whisper STT wrapper

Transcribes a recorded/uploaded audio clip into plain text so the rest of the
pipeline (Agent 1 Extractor → Agent 2 Validator) can treat a voice note exactly
like typed bill text.
"""
from __future__ import annotations

import io
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_MODEL = "whisper-1"


def transcribe(file_bytes: bytes, file_name: str | None = None) -> str:
    """
    Transcribe spoken audio to text using OpenAI Whisper.

    Args:
        file_bytes: Raw bytes of the audio clip (wav/mp3/m4a/webm…).
        file_name:  Original filename — used only so Whisper can infer the format
                    from the extension. Defaults to "voice-note.wav".

    Returns:
        The transcribed text (stripped). May be an empty string for silent clips.
    """
    if not file_bytes:
        raise ValueError("transcribe() received empty audio")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or "your-" in api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured in .env")

    client = OpenAI(api_key=api_key)

    # Whisper needs a named file-like object so it can detect the container format.
    buffer = io.BytesIO(file_bytes)
    buffer.name = file_name or "voice-note.wav"

    transcript = client.audio.transcriptions.create(
        model=_MODEL,
        file=buffer,
    )
    return (transcript.text or "").strip()
