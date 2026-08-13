"""Shared Deepgram transcription for Telegram and dashboard voice input."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from app.db import voice_cost_add

logger = logging.getLogger("orchestra.transcription")

UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTION_CACHE_PATH = UPLOADS_DIR / ".transcription_cache.json"


def _load_transcription_cache() -> dict[str, str]:
    if TRANSCRIPTION_CACHE_PATH.exists():
        try:
            return json.loads(TRANSCRIPTION_CACHE_PATH.read_text())
        except Exception as e:
            logger.warning("transcription cache load failed: %s", e)
    return {}


def _save_transcription_cache(cache: dict[str, str]) -> None:
    TRANSCRIPTION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False))


_transcription_cache: dict[str, str] = _load_transcription_cache()


async def transcribe_audio(
    path: str,
    unique_id: str = "",
    *,
    session_name: str = "",
    scope: str = "",
    content_type: str = "audio/ogg",
) -> tuple[str, str | None]:
    if unique_id and unique_id in _transcription_cache:
        cached = _transcription_cache[unique_id]
        logger.info("Transcription cache hit: %s", unique_id)
        return cached, None
    api_key = os.getenv("DEEPGRAM_API_KEY", "")
    if not api_key:
        return "", "DEEPGRAM_API_KEY is not configured"
    file_size = Path(path).stat().st_size
    audio_data = Path(path).read_bytes()
    last_err = ""
    started = time.monotonic()
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120, verify=True) as client:
                response = await client.post(
                    "https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true&profanity_filter=false",
                    headers={
                        "Authorization": f"Token {api_key}",
                        "Content-Type": content_type,
                    },
                    content=audio_data,
                )
                output = response.content
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("Deepgram attempt %d/3 failed: %s", attempt + 1, last_err)
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    else:
        logger.error("Deepgram failed after 3 attempts: %s", last_err)
        return "", last_err

    transcribe_ms = (time.monotonic() - started) * 1000
    try:
        data = json.loads(output)
        if response.status_code >= 400:
            detail = data.get("err_msg") or data.get("error") or f"HTTP {response.status_code}"
            return "", str(detail)
        if "error" in data:
            return "", str(data["error"])
        text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        duration = float(data.get("metadata", {}).get("duration") or 0)
        logger.info(
            "Deepgram: audio=%.1fs size=%dKB transcribe=%.0fms",
            duration,
            file_size // 1024,
            transcribe_ms,
        )
        voice_cost_add(
            session_name=session_name,
            scope=scope,
            duration_sec=duration,
            cost_usd=duration / 60 * 0.0052,
            file_id=unique_id,
        )
        if unique_id and text:
            _transcription_cache[unique_id] = text
            _save_transcription_cache(_transcription_cache)
        return text, None
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        raw = output.decode(errors="replace")[:200]
        logger.error("Deepgram parse error: %s, raw: %s", e, raw)
        return "", f"{type(e).__name__}: {e}"
