"""
services/elevenlabs.py — ElevenLabs TTS wrapper

Turns the voice agent's short confirmation/prompt lines into spoken audio
for the conversational assignment loop (Phase 7).
"""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

_TTS_URL   = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_VOICE_ID  = "EXAVITQu4vr4xnSDxMaL"  # ElevenLabs premade voice "Sarah"
_MODEL_ID  = "eleven_turbo_v2_5"


def speak(text: str) -> bytes:
    """
    Synthesize speech for the given text via ElevenLabs.

    Returns:
        Raw MP3 audio bytes.
    """
    if not text:
        raise ValueError("speak() received empty text")

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key or "your-" in api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured in .env")

    response = requests.post(
        _TTS_URL.format(voice_id=_VOICE_ID),
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": _MODEL_ID,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.content
