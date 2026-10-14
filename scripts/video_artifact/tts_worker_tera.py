"""Pinned local TeraTTS worker; one loaded CPU model serves concurrent phrase jobs."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


REVISION = "f05ea799094571a3553904a555df3834fb0b963b"


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
        print(json.dumps({"normalized": [model.normalize_text(f"<ru>{text}</ru>")
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

    def synthesize(job: dict) -> int:
        raw = Path(job["out"])
        temp = raw.with_suffix(raw.suffix + ".part")
        waveform = model.generate_speech(
            f"<ru>{job['text']}</ru>",
            voice=job["voice"],
            duration_scale=1.0 / float(job["rate"]),
            seed=1234 + int(job["index"]),
        )
        model.save_wav(temp, waveform)
        os.replace(temp, raw)
        return int(job["index"])

    with ThreadPoolExecutor(max_workers=min(2, len(jobs))) as pool:
        futures = [pool.submit(synthesize, job) for job in jobs]
        for future in as_completed(futures):
            print(json.dumps({"index": future.result()}), flush=True)


if __name__ == "__main__":
    main()
