"""Pinned local TeraTTS worker; one loaded CPU model serves concurrent phrase jobs."""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


REVISION = "f05ea799094571a3553904a555df3834fb0b963b"


def add_wordwise_russian_stress(text: str, accentizer) -> str:
    if accentizer is None:
        return text

    def accent(match):
        words = re.split(r"(\s+)", match.group(1))
        marked = "".join(
            word if word.isspace() or "+" in word else accentizer.process_all(word)
            for word in words
        )
        return f"<ru>{marked}</ru>"

    return re.sub(r"<ru>(.*?)</ru>", accent, text, flags=re.DOTALL)


SENTENCE_GAP = 0.42
SILENCE_LEVEL = 160 / 32768
ABBREVIATIONS = {"т", "д", "п", "др", "пр", "см", "рис", "г", "гг", "им", "руб", "ср", "напр", "проф", "доц"}
VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


def split_sentences(text: str) -> list[str]:
    """Cut after . ! ? … followed by whitespace; decimals and common abbreviations stay inside the sentence."""
    sentences: list[str] = []
    cursor = 0
    for match in re.finditer(r"[.!?…]+(?=\s|$)", text):
        before = text[cursor:match.start()]
        last_word = re.split(r"[\s.]+", before.strip())[-1].lower() if before.strip() else ""
        if match.group() == "." and (last_word in ABBREVIATIONS or (len(last_word) == 1 and last_word.isalpha())):
            continue
        sentences.append(text[cursor:match.end()].strip())
        cursor = match.end()
    if tail := text[cursor:].strip():
        sentences.append(tail)
    return [sentence for sentence in sentences if sentence]


def merge_short_sentences(sentences: list[str]) -> list[str]:
    """The duration predictor stretches a lone ≤3-vowel utterance 2–3×, so glue it to the next sentence."""
    merged: list[str] = []
    carry = ""
    for sentence in sentences:
        sentence = f"{carry} {sentence}".strip() if carry else sentence
        carry = sentence if sum(char in VOWELS for char in sentence) <= 3 else ""
        if not carry:
            merged.append(sentence)
    if carry:
        merged.append(carry)
    return merged


def split_pause_segments(text: str) -> list[tuple[str, str | float | None]]:
    """Cut only at [seconds] markers and sentence ends; commas, colons and dashes are left to the model.

    A ("gap", None) piece is the sentence pause, sized in compose_audio from the model's own tail silence.
    """
    segments: list[tuple[str, str | float | None]] = []
    parts = re.split(r"\[(\d+(?:\.\d+)?)\]", text)
    for index, part in enumerate(parts):
        if index % 2:
            duration = float(part)
            if not 0.05 <= duration <= 10:
                raise ValueError(f"pause duration must be between 0.05 and 10 seconds: [{duration:g}]")
            segments.append(("pause", duration))
            continue
        for number, sentence in enumerate(merge_short_sentences(split_sentences(part))):
            if number:
                segments.append(("gap", None))
            segments.append(("text", sentence))
    return segments or [("text", text.strip())]


def add_silence(samples, seconds: float, sample_rate: int = 44_100):
    import numpy as np

    zeros = np.zeros((round(seconds * sample_rate), *samples.shape[1:]), dtype=samples.dtype)
    return np.concatenate((samples, zeros), axis=0)


PEAK_CEILING = 10 ** (-3 / 20)
RMS_TARGET = 10 ** (-20 / 20)


def level_phrase(samples):
    """Model output exceeds ±1.0 and save_wav clips it hard. Bring phrases to one RMS level, never above the peak ceiling."""
    if isinstance(samples, bytes) or not len(samples):
        return samples
    peak = float(max(samples.max(), -samples.min()))
    rms = float((samples.astype("float64") ** 2).mean() ** 0.5)
    if peak == 0.0 or rms == 0.0:
        return samples
    return samples * min(RMS_TARGET / rms, PEAK_CEILING / peak)


def trailing_silence(samples, sample_rate: int) -> float:
    import numpy as np

    loud = np.flatnonzero(np.abs(samples) > SILENCE_LEVEL)
    return (len(samples) - 1 - loud[-1]) / sample_rate if len(loud) else len(samples) / sample_rate


def compose_audio(pieces, sample_rate: int = 44_100, rate: float = 1.0):
    output = None
    for kind, value in pieces:
        if kind in {"pause", "gap"}:
            if output is None:
                continue
            seconds = float(value) if kind == "pause" else SENTENCE_GAP / rate
            if kind == "gap" and not isinstance(output, bytes):
                seconds = max(0.0, seconds - trailing_silence(output, sample_rate))
            if isinstance(output, bytes):
                output += b"\0\0" * round(seconds * sample_rate)
            else:
                output = add_silence(output, seconds, sample_rate)
        else:
            if isinstance(value, bytes):
                output = value if output is None else output + value
            else:
                import numpy as np

                samples = np.asarray(value)
                output = samples if output is None else np.concatenate((output, samples), axis=0)
    if output is not None:
        return output
    import numpy as np

    return np.zeros(0, dtype=np.float32)


def clean_pause_markers(text: str) -> str:
    return re.sub(r"\[\d+(?:\.\d+)?\]", "", text)


def patch_wordwise_stress(model) -> None:
    module = sys.modules[type(model).__module__]
    normalizer = getattr(module, "normalize_text", None)
    namespace = getattr(normalizer, "__globals__", module.__dict__)
    if "add_russian_stress" in namespace:
        namespace["add_russian_stress"] = add_wordwise_russian_stress


def render_phrase(model, job: dict):
    pieces = []
    for segment_no, (kind, value) in enumerate(split_pause_segments(job["text"])):
        if kind == "text":
            value = model.generate_speech(
                f"<ru>{value}</ru>", voice=job["voice"],
                duration_scale=1.0 / float(job["rate"]),
                seed=1234 + int(job["index"]) + segment_no,
            )
        pieces.append((kind, value))
    return level_phrase(compose_audio(pieces, rate=float(job["rate"])))


def main() -> None:
    request = json.load(sys.stdin)
    snapshot = Path(os.environ["ORCHESTRA_TERA_SNAPSHOT"])
    if not snapshot.is_dir() or snapshot.name != REVISION:
        raise SystemExit(f"expected pinned Tera snapshot {REVISION}: {snapshot}")
    module_cache = snapshot.parents[3] / "modules"
    module_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_MODULES_CACHE"] = str(module_cache)
    from transformers import AutoModel

    if isinstance(request, dict) and request.get("action") == "normalize":
        model = AutoModel.from_pretrained(
            str(snapshot), trust_remote_code=True, local_files_only=True,
            provider="CPUExecutionProvider", threads=6,
            diffusion_model="distilled", russian_stress=request["russian_stress"],
        )
        patch_wordwise_stress(model)
        print(json.dumps({"normalized": [model.normalize_text(f"<ru>{clean_pause_markers(text)}</ru>") if text.strip() else ""
                                         for text in request["texts"]]}, ensure_ascii=False))
        return

    jobs = request
    if not isinstance(jobs, list):
        raise SystemExit("expected a JSON list of TeraTTS phrase jobs")
    model = AutoModel.from_pretrained(
        str(snapshot), trust_remote_code=True, local_files_only=True,
        provider="CPUExecutionProvider", threads=6,
        diffusion_model="distilled",
        russian_stress=bool(jobs[0]["stress"]) if jobs else True,
    )
    patch_wordwise_stress(model)

    def synthesize(job: dict) -> int:
        raw = Path(job["out"])
        temp = raw.with_suffix(raw.suffix + ".part")
        model.save_wav(temp, render_phrase(model, job))
        os.replace(temp, raw)
        return int(job["index"])

    with ThreadPoolExecutor(max_workers=min(2, len(jobs))) as pool:
        futures = [pool.submit(synthesize, job) for job in jobs]
        for future in as_completed(futures):
            print(json.dumps({"index": future.result()}), flush=True)


if __name__ == "__main__":
    main()
