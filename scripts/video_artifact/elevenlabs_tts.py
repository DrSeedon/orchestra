"""ElevenLabs Flash narration shared by video builds and the small text/file CLI.

No retries or provider/model fallback. A durable request marker prevents replay
after an uncertain submission; received MP3s survive decoder/render failures.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import wave

import httpx

MODEL = "eleven_flash_v2_5"
# Owner-selected saved voice: Sergey - Rich, Engaging and Captivating.
# Root verified Flash fine-tuning and sharing.rate=1.0 on 2026-10-25.
# Do not substitute another voice (including for English) on a refusal.
DEFAULT_VOICE = "XuEV9VY3VUASYgJVNBh0"
OUTPUT_FORMAT = "mp3_44100_128"  # Starter supports this; PCM 44.1 kHz requires Pro.
SR = 48_000
TIMEOUT = httpx.Timeout(120.0, connect=10.0, write=30.0, pool=10.0)


class TTSError(RuntimeError):
    """Safe, actionable error without headers, credentials or response bodies."""


@dataclass(frozen=True)
class Config:
    voice: str = DEFAULT_VOICE
    model: str = MODEL
    language: str = "ru"
    speed: float = 1.0
    stability: float = 0.5
    similarity: float = 0.75

    def __post_init__(self):
        if self.model != MODEL:
            raise TTSError(f"Only the approved economy model {MODEL} is supported; no paid fallback")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.voice):
            raise TTSError("Invalid ElevenLabs voice ID; use --voice or ELEVENLABS_VOICE_ID")
        if self.language not in {"ru", "en"}:
            raise TTSError("ElevenLabs narration language must be ru or en")
        for name, value, lower, upper in (
            ("speed", self.speed, 0.7, 1.2),
            ("stability", self.stability, 0, 1),
            ("similarity", self.similarity, 0, 1),
        ):
            if not math.isfinite(value) or not lower <= value <= upper:
                raise TTSError(f"ElevenLabs {name} must be between {lower} and {upper}")

    @property
    def settings(self):
        return {"stability": self.stability, "similarity_boost": self.similarity,
                "style": 0.0, "use_speaker_boost": True, "speed": self.speed}

    def payload(self, text: str):
        return {"text": text, "model_id": self.model, "language_code": self.language,
                "voice_settings": self.settings}


def load_environment() -> None:
    """Only the repository .env, never an ancestor/home search; exported env wins.

    Call lazily from an actual synthesis path, never import or preview/help.
    """
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def config_from_env(*, voice: str = "", language: str = "ru", speed: float = 1.0,
                    stability: float = 0.5, similarity: float = 0.75) -> Config:
    return Config(voice=voice or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE,
                  language=language, speed=speed, stability=stability, similarity=similarity)


def clean_text(text: str) -> str:
    # Remove legacy RU stress marks, keeping mathematical/technical + intact.
    text = re.sub(r"(?<=[А-Яа-яЁё])\+(?=[А-Яа-яЁё])", "", text)
    return re.sub(r"(?<=[А-Яа-яЁё])\u0301", "", text).strip()


def segments(text: str) -> list[tuple[str, str | float]]:
    result = []
    for i, part in enumerate(re.split(r"\[(\d+(?:\.\d+)?)\]", clean_text(text))):
        if i % 2:
            seconds = float(part)
            if not 0.05 <= seconds <= 10:
                raise TTSError("Explicit pauses [seconds] must be between 0.05 and 10 seconds")
            result.append(("pause", seconds))
        elif part.strip():
            if len(part.strip()) > 40_000:
                raise TTSError("Flash v2.5 accepts at most 40000 characters per speech segment")
            result.append(("text", part.strip()))
    return result


def cache_key(text: str, config: Config) -> str:
    encoded = json.dumps({"schema": "elevenlabs-mp3-wav48-trim-v1", "voice": config.voice,
                          "format": OUTPUT_FORMAT, **config.payload(text)},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    with part.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(part, path)
    # Intent and received audio must survive power/process failure, including the rename.
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def cache_lock(path: Path):
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def wav_frames(path: Path, *, allow_empty: bool = False) -> bytes:
    try:
        with wave.open(str(path), "rb") as stream:
            frames = stream.readframes(stream.getnframes())
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, SR, "NONE"):
                raise ValueError("wrong WAV format")
            if len(frames) != stream.getnframes() * 2 or (not frames and not allow_empty):
                raise ValueError("empty/truncated WAV")
            return frames
    except (OSError, EOFError, wave.Error, ValueError):
        raise TTSError(f"Invalid cached WAV: {path}; retain the cache and inspect it before regenerating") from None


def write_wav(path: Path, frames: bytes) -> None:
    part = path.with_name(path.name + ".part")
    with part.open("wb") as stream:
        with wave.open(stream, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SR)
            output.writeframes(frames)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(part, path)


def decode_mp3(source: Path, output: Path) -> None:
    """Decode bytes as MP3, rather than relabelling them as WAV or raw PCM."""
    part = output.with_name(output.name + ".part")
    edge = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03"
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "mp3", "-i", str(source),
             "-af", f"{edge},areverse,{edge},areverse", "-ar", str(SR), "-ac", "1",
             "-c:a", "pcm_s16le", "-f", "wav", str(part)],
            capture_output=True, timeout=120, check=False,
        )
        if result.returncode:
            raise TTSError("ElevenLabs returned malformed/undecodable MP3; cached response retained; no retry")
        wav_frames(part)
        with part.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(part, output)
    except (OSError, subprocess.TimeoutExpired):
        raise TTSError("ElevenLabs audio decode failed/timed out; cached MP3 retained; install/check ffmpeg; no API retry") from None
    finally:
        part.unlink(missing_ok=True)


def require_decoder() -> None:
    if not shutil.which("ffmpeg"):
        raise TTSError("ffmpeg is required to decode ElevenLabs MP3; install it before submitting paid speech")


def _request(text: str, config: Config, mp3: Path, marker: Path, client: httpx.Client) -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise TTSError("Missing ELEVENLABS_API_KEY; export it or configure the repository .env")
    require_decoder()
    # Persist intent BEFORE POST. Even process death cannot silently replay it.
    atomic_bytes(marker, b'{"state":"submission_uncertain","provider":"elevenlabs"}\n')
    try:
        response = client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config.voice}",
            params={"output_format": OUTPUT_FORMAT}, headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json=config.payload(text), timeout=TIMEOUT,
        )
    except httpx.TimeoutException:
        raise TTSError(f"ElevenLabs timeout; submission/billing uncertain; no retry. Inspect {marker}") from None
    except httpx.HTTPError:
        raise TTSError(f"ElevenLabs transport failure; submission/billing uncertain; no retry. Inspect {marker}") from None
    status = response.status_code
    if status != 200:
        try:
            detail = response.json().get("detail", {})
            error_code = detail.get("status") if isinstance(detail, dict) else None
        except (ValueError, AttributeError):
            error_code = None
        # Only explicit client refusals are safely repeatable after fixing input/key/quota.
        if status in {400, 401, 402, 403, 404, 422, 429}:
            marker.unlink(missing_ok=True)
        if error_code in {"quota_exceeded", "rate_limit_exceeded", "too_many_concurrent_requests"}:
            reason = "quota or rate limit exceeded; check subscription/credits/concurrency"
        elif status in {401, 403}:
            reason = "authentication/permissions error; check ELEVENLABS_API_KEY and voice access"
        elif status in {402, 429}:
            reason = "quota or rate limit exceeded; check subscription/credits/concurrency"
        elif status == 404:
            reason = "voice/model unavailable; configure an accessible voice; no fallback"
        else:
            reason = "request failed; no retry or fallback"
        raise TTSError(f"ElevenLabs HTTP {status}: {reason}")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"audio/mpeg", "audio/mp3", "application/octet-stream"} or not response.content:
        raise TTSError(f"ElevenLabs malformed/empty audio response; billing uncertain; no retry. Inspect {marker}")
    atomic_bytes(mp3, response.content)


def _speech(text: str, cache: Path, config: Config, client: httpx.Client) -> Path:
    key = cache_key(text, config)
    output, mp3, marker = (cache / f"{key}{suffix}" for suffix in (".wav", ".mp3", ".request.json"))
    with cache_lock(cache / f"{key}.lock"):
        if output.exists():
            wav_frames(output)
            return output
        if not mp3.exists():
            if marker.exists():
                raise TTSError(f"Earlier ElevenLabs submission is uncertain; refusing another charge. Inspect {marker}")
            _request(text, config, mp3, marker, client)
        decode_mp3(mp3, output)
        marker.unlink(missing_ok=True)
    return output


def synthesize(text: str, cache: Path, config: Config, *, client: httpx.Client | None = None) -> Path:
    """Cache speech segments separately; explicit pauses are local literal silence.

    Keys depend on model/voice/settings/language/text/format, never the API key.
    Passing a MockTransport client makes the complete path work offline.
    """
    pieces = segments(text)  # Validate the whole input before any paid submission.
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"{cache_key(clean_text(text), config)}.phrase.wav"
    with cache_lock(output.with_suffix(".lock")):
        if output.exists():
            wav_frames(output, allow_empty=not pieces)
            return output
        if client is None:
            with httpx.Client(follow_redirects=False, trust_env=False) as owned:
                return _compose(pieces, cache, config, owned, output)
        return _compose(pieces, cache, config, client, output)


def _compose(pieces, cache: Path, config: Config, client: httpx.Client, output: Path) -> Path:
    frames = []
    for kind, value in pieces:
        if kind == "pause":
            frames.append(b"\x00\x00" * round(float(value) * SR))
        else:
            frames.append(wav_frames(_speech(str(value), cache, config, client)))
    write_wav(output, b"".join(frames))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="ElevenLabs Flash RU/EN → cached 48 kHz mono WAV")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file", type=Path, help="UTF-8 text file")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="default: <out parent>/.tts-cache")
    parser.add_argument("--lang", choices=["ru", "en"], default="ru")
    parser.add_argument("--voice", default="", help="voice ID; default: Sergey or ELEVENLABS_VOICE_ID")
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--stability", type=float, default=0.5)
    parser.add_argument("--similarity", type=float, default=0.75)
    args = parser.parse_args()
    try:
        if args.out.suffix.lower() != ".wav":
            raise TTSError("Output is PCM WAV; use a .wav filename for --out")
        load_environment()
        config = config_from_env(voice=args.voice, language=args.lang, speed=args.rate,
                                 stability=args.stability, similarity=args.similarity)
        text = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
        if not segments(text):
            raise TTSError("No speech text provided")
        path = synthesize(text, args.cache or args.out.parent / ".tts-cache", config)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != args.out.resolve():
            atomic_bytes(args.out, path.read_bytes())
    except (TTSError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    except UnicodeError:
        parser.exit(1, "Input file must contain UTF-8 text\n")
    print(args.out)


if __name__ == "__main__":
    main()
