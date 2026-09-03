#!/usr/bin/env python3
"""Resume only trials 2/3 after the server restart interrupted the frozen runner."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from run_extractor_eval import ARTIFACT, CODEX, MODEL, ROOT, TASKS, tree_digest


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="orchestra-eval-454-resume-", dir="/mnt/data"))
    manifest: list[str] = []
    try:
        for task_id in TASKS:
            source_root = ROOT / ".orchestra" / "tasks" / task_id
            destination = scratch / "sources" / f"task-{task_id}"
            destination.mkdir(parents=True)
            for source in sorted(source_root.rglob("*.md")):
                relative = source.relative_to(source_root)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                manifest.append(target.relative_to(scratch).as_posix())
        prompt = (ARTIFACT / "extractor-prompt.md").read_text(encoding="utf-8")
        prompt += "\n\n## SOURCE MANIFEST\n\n" + "\n".join(
            f"- {path}" for path in manifest
        ) + "\n"
        source_digest = tree_digest(scratch)
        trials: list[dict] = []
        for trial in (2, 3):
            output = ARTIFACT / f"eval-run-{trial}.txt"
            trace = ARTIFACT / f"eval-run-{trial}.jsonl"
            stderr = ARTIFACT / f"eval-run-{trial}.stderr"
            started = time.monotonic()
            with trace.open("wb") as stdout_stream, stderr.open("wb") as stderr_stream:
                result = subprocess.run(
                    [
                        str(CODEX), "-m", MODEL,
                        "-s", "danger-full-access", "-a", "never",
                        "exec", "--skip-git-repo-check", "--json",
                        "-o", str(output), "-",
                    ],
                    cwd=scratch,
                    input=prompt.encode("utf-8"),
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    check=False,
                )
            after_digest = tree_digest(scratch)
            trials.append(
                {
                    "trial": trial,
                    "returncode": result.returncode,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "source_digest_before": source_digest,
                    "source_digest_after": after_digest,
                    "source_unchanged": after_digest == source_digest,
                    "output": output.name,
                    "trace": trace.name,
                    "stderr": stderr.name,
                }
            )
        (ARTIFACT / "eval-run-manifest-part23.json").write_text(
            json.dumps(
                {
                    "model": MODEL,
                    "source_files": len(manifest),
                    "source_tasks": list(TASKS),
                    "source_digest": source_digest,
                    "trials": trials,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(trials, ensure_ascii=False))
        if any(trial["returncode"] != 0 or not trial["source_unchanged"] for trial in trials):
            raise SystemExit(1)
    finally:
        shutil.rmtree(scratch)


if __name__ == "__main__":
    main()
