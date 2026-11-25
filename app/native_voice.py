"""Helpers for native Gemini audio input (.ogg) without Deepgram transcription."""

from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

NATIVE_AUDIO_INLINE_MAX_BYTES = 20 * 1024 * 1024
_VOICE_PATH_RE = re.compile(r"\[(?:voice|video_note):[^\]\n]*?(?:/[^\s\]|]+\.ogg)\b[^\]\n]*?\]")
_ABS_OGG_RE = re.compile(r"(/[^\s\]|]+\.ogg)\b")


def format_native_voice_tag(
    path: str | Path,
    duration_seconds: float | int | None = None,
    *,
    source: str = "voice",
    companion_video: str | Path | None = None,
    filename: str = "",
) -> str:
    """Format the canonical prompt tag instructing Gemini to listen to audio directly."""
    dur_part = ""
    if duration_seconds is not None:
        try:
            dur = int(round(float(duration_seconds)))
            if dur > 0:
                dur_part = f" ({dur}s)"
        except (TypeError, ValueError):
            pass

    if source == "video_note":
        video_str = str(companion_video or path)
        return (
            f"[video_note: {video_str} | audio: {path}{dur_part} — звук кружочка (без Deepgram): "
            f"прослушай .ogg файл сам напрямую через read_file (если аудио не приложено inline), "
            f"а кадры видео при необходимости извлеки через ffmpeg (не открывай .mp4 в read_file)]"
        )
    if source == "audio":
        label = filename or Path(str(path)).name
        return f"[audio: {path} | {label}{dur_part} — прослушай аудиофайл сам напрямую через read_file]"
    if source == "dashboard":
        return (
            f"[voice: {path}{dur_part} — голосовое сообщение с микрофона (без Deepgram): "
            f"прослушай аудиофайл сам напрямую ушами (через read_file, если аудио не приложено inline) и ответь по сути]"
        )
    return (
        f"[voice: {path}{dur_part} — голосовое сообщение (без Deepgram): "
        f"прослушай аудиофайл сам напрямую ушами (через read_file, если аудио не приложено inline) и ответь по сути]"
    )


async def _run_ffmpeg_ogg(args: list[str], dst: Path) -> tuple[bool, str]:
    """Run one ffmpeg attempt producing a non-empty .ogg destination file."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", *args, str(dst),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise ValueError("audio conversion to .ogg timed out")
    ok = process.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
    detail = stderr.decode(errors="replace").strip()[:200] or str(process.returncode)
    return ok, detail


async def convert_to_ogg_opus(src_path: str | Path, dst_path: str | Path) -> Path:
    """Remux Opus streams instantly via -c:a copy; fall back to libopus only when needed."""
    src = Path(src_path)
    dst = Path(dst_path)
    if src.resolve() != dst.resolve():
        dst.unlink(missing_ok=True)
    ok, _ = await _run_ffmpeg_ogg(["-i", str(src), "-vn", "-c:a", "copy"], dst)
    if ok:
        return dst
    if src.resolve() != dst.resolve():
        dst.unlink(missing_ok=True)
    ok, detail = await _run_ffmpeg_ogg(["-i", str(src), "-vn", "-acodec", "libopus"], dst)
    if not ok:
        raise ValueError(f"ffmpeg .ogg conversion failed: {detail}")
    return dst


def extract_native_voice_paths(
    text: str,
    allowed_dir: Path,
    *,
    max_bytes: int = NATIVE_AUDIO_INLINE_MAX_BYTES,
) -> list[Path]:
    """Return validated .ogg file paths referenced in native voice tags inside allowed_dir."""
    if not text or "[voice:" not in text and "[video_note:" not in text:
        return []
    root = allowed_dir.resolve()
    seen: set[Path] = set()
    found: list[Path] = []
    for tag_match in _VOICE_PATH_RE.finditer(text):
        for path_match in _ABS_OGG_RE.finditer(tag_match.group(0)):
            candidate = Path(path_match.group(1)).resolve()
            if candidate in seen:
                continue
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.suffix.lower() != ".ogg" or not candidate.is_file():
                continue
            try:
                if candidate.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            seen.add(candidate)
            found.append(candidate)
    return found


def build_inline_audio_blocks(
    text: str,
    allowed_dir: Path,
    *,
    max_bytes: int = NATIVE_AUDIO_INLINE_MAX_BYTES,
) -> list[dict]:
    """Build ACP audio content blocks for small native .ogg uploads."""
    blocks = []
    for path in extract_native_voice_paths(text, allowed_dir, max_bytes=max_bytes):
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append({"type": "audio", "data": data, "mimeType": "audio/ogg"})
    return blocks
