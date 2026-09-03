#!/usr/bin/env python3
"""Run three fresh Luna prompt trials outside the repository/AGENTS ancestry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / ".orchestra" / "tasks" / "454"
TASKS = ("416", "417", "419", "425", "426", "430")
CODEX = Path("/home/maxim/.local/bin/codex")
MODEL = "gpt-5.6-luna"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "sources").rglob("*.md")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    if not CODEX.is_file():
        raise SystemExit(f"codex binary missing: {CODEX}")
    scratch = Path(tempfile.mkdtemp(prefix="orchestra-eval-454-", dir="/mnt/data"))
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

        base_prompt = (ARTIFACT / "extractor-prompt.md").read_text(encoding="utf-8")
        prompt = base_prompt + "\n\n## SOURCE MANIFEST\n\n" + "\n".join(
            f"- {path}" for path in manifest
        ) + "\n"
        source_digest = tree_digest(scratch)
        trials: list[dict] = []
        for trial in range(1, 4):
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
        (ARTIFACT / "eval-run-manifest.json").write_text(
            json.dumps(
                {
                    "model": MODEL,
                    "scratch_outside_repo": str(scratch),
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

