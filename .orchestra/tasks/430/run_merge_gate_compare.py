#!/usr/bin/env python3
"""Run each merge-gate test file in its own pytest process and retain raw output."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def failure_nodes(output: str, test_file: str, returncode: int) -> list[str]:
    nodes: set[str] = set()
    for line in output.splitlines():
        if line.startswith("FAILED "):
            node = line.removeprefix("FAILED ").split(" - ", 1)[0].strip()
            if node.startswith("tests/"):
                nodes.add(node)
        elif line.startswith("ERROR "):
            node = line.removeprefix("ERROR ").split(" - ", 1)[0].strip()
            if node.startswith("tests/"):
                nodes.add(node)
    if returncode and not nodes:
        nodes.add(f"{test_file}::<pytest-exit-{returncode}>")
    return sorted(nodes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interpreter", type=Path, required=True)
    parser.add_argument("--files", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    output = args.output.resolve()
    interpreter = args.interpreter.absolute()
    output.mkdir(parents=True, exist_ok=True)
    files = [line.strip() for line in args.files.read_text().splitlines() if line.strip()]
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()

    failures: set[str] = set()
    shards = []
    for index, test_file in enumerate(files, start=1):
        command = [
            str(interpreter),
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            test_file,
        ]
        result = subprocess.run(command, cwd=repo, text=True, capture_output=True)
        raw = result.stdout + result.stderr
        stem = Path(test_file).stem
        (output / f"{index:02d}-{stem}.txt").write_text(raw, encoding="utf-8")
        (output / f"{index:02d}-{stem}.rc").write_text(
            f"{result.returncode}\n", encoding="utf-8"
        )
        nodes = failure_nodes(raw, test_file, result.returncode)
        failures.update(nodes)
        shards.append(
            {
                "file": test_file,
                "returncode": result.returncode,
                "failed_nodes": nodes,
            }
        )

    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    summary = {
        "schema_version": 1,
        "commit": commit,
        "command_template": f"{interpreter} -m pytest -q --tb=short <test-file>",
        "test_files": len(files),
        "failed_nodes": sorted(failures),
        "failed_node_count": len(failures),
        "status_before": before,
        "status_after": after,
        "shards": shards,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "failures.txt").write_text(
        "\n".join(sorted(failures)) + ("\n" if failures else ""), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
