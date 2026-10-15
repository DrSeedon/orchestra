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


def split_pause_segments(text: str) -> list[tuple[str, str | float]]:
    segments: list[tuple[str, str | float]] = []
    cursor = 0
    for match in re.finditer(r"\[(\d+(?:\.\d+)?)\]|[,;:]|\.{1,3}|[!?…—–]", text):
        before = text[cursor:match.start()]
        if match.group(1) is not None:
            if before.strip():
                segments.append(("text", before.strip()))
            duration = float(match.group(1))
            if not 0.05 <= duration <= 10:
                raise ValueError(f"pause duration must be between 0.05 and 10 seconds: [{duration:g}]")
            segments.append(("pause", duration))
        else:
            spoken = (before + match.group()).strip()
            if spoken:
                segments.append(("text", spoken))
            if text[match.end():].strip():
                punctuation_pause = 0.33 if match.group() in {",", ";", ":", "—", "–"} else 0.63
                segments.append(("pause", punctuation_pause))
        cursor = match.end()
    if tail := text[cursor:].strip():
        segments.append(("text", tail))
    return segments or [("text", text.strip())]


def add_silence(samples, seconds: float, sample_rate: int = 44_100):
    import numpy as np

    zeros = np.zeros((round(seconds * sample_rate), *samples.shape[1:]), dtype=samples.dtype)
    return np.concatenate((samples, zeros), axis=0)


def compose_audio(pieces, sample_rate: int = 44_100):
    output = None
    for kind, value in pieces:
        if kind == "pause":
            if output is not None:
                if isinstance(output, bytes):
                    output += b"\0\0" * round(float(value) * sample_rate)
                else:
                    output = add_silence(output, float(value), sample_rate)
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
        pieces = []
        for segment_no, (kind, value) in enumerate(split_pause_segments(job["text"])):
            if kind == "pause":
                pieces.append((kind, value))
                continue
            samples = model.generate_speech(
                f"<ru>{value}</ru>", voice=job["voice"],
                duration_scale=1.0 / float(job["rate"]),
                seed=1234 + int(job["index"]) + segment_no,
            )
            pieces.append((kind, samples))
        waveform = compose_audio(pieces)
        model.save_wav(temp, waveform)
        os.replace(temp, raw)
        return int(job["index"])

    with ThreadPoolExecutor(max_workers=min(2, len(jobs))) as pool:
        futures = [pool.submit(synthesize, job) for job in jobs]
        for future in as_completed(futures):
            print(json.dumps({"index": future.result()}), flush=True)


if __name__ == "__main__":
    main()
