from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
SCENE = TASK / "tera-demo.html"


def run_engine(engine: str) -> None:
    output = TASK / "bench" / ("tera-m1" if engine == "tera" else "vosk")
    output.mkdir(parents=True, exist_ok=True)
    command = [
        "/home/kesha/.local/bin/uv", "run", "--frozen", "--project", str(ROOT),
        "python", "scripts/video_artifact/make.py", str(SCENE), "--out", str(output),
        "--stills", "--no-check", "--jobs", "2",
    ]
    if engine == "vosk":
        command.extend(["--tts-engine", "vosk"])
    else:
        command.extend(["--voice", "m1"])
    started = time.monotonic()
    stage_one = speech_start = plan_ready = None
    timing = output / "timing.log"
    with timing.open("w") as log:
        process = subprocess.Popen(
            ["/usr/bin/time", "-f", "elapsed=%e maxrss_kb=%M cpu=%P", "-o", str(output / "time.txt"), *command],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            now = time.monotonic()
            log.write(f"{now:.3f}\t{line}")
            if line.startswith("stage 1/4:"):
                stage_one = now
            elif line.startswith("синтез "):
                speech_start = now
            elif line.startswith("stage 2/4:"):
                plan_ready = now
        code = process.wait()
    result = {
        "engine": engine,
        "returncode": code,
        "total_elapsed_s": round(time.monotonic() - started, 2),
        "pre_stage1_s": round(stage_one - started, 2) if stage_one else None,
        "stage_one_to_plan_s": round(plan_ready - stage_one, 2) if plan_ready and stage_one else None,
        "speech_to_plan_s": round(plan_ready - speech_start, 2) if plan_ready and speech_start else None,
    }
    (output / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    os.nice(15)
    selected_engines = sys.argv[1:] or ["tera", "vosk"]
    if any(engine not in {"tera", "vosk"} for engine in selected_engines):
        raise SystemExit("expected engine names: tera, vosk")
    for selected in selected_engines:
        run_engine(selected)
