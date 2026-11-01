"""Verify research scope, evidence links and secret shapes without Git or host data."""
import importlib.util
import json
from pathlib import Path
import re
import sys


TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
sys.path.insert(0, str(ROOT))

import hashlib
from app.publication_secrets import HUB_SECRET_SHAPES


def source_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in (".venv", ".pytest_cache", "__pycache__") for part in relative.parts):
            continue
        if relative.as_posix().startswith(".orchestra/tasks/V-1076/"):
            continue
        if relative.as_posix() == ".orchestra-outbox.jsonl":
            continue  # Broker transport, not a source/result file.
        yield relative.as_posix(), path


def main():
    baseline = json.loads((TASK / "source-baseline.json").read_text())
    current = {name: hashlib.sha256(path.read_bytes()).hexdigest()
               for name, path in source_files()}
    changed = sorted(name for name in baseline if current.get(name) != baseline[name])
    added = sorted(set(current) - set(baseline))
    print("baseline_files", len(baseline))
    print("changed_or_missing_outside_task", changed)
    print("added_outside_task", added)
    assert not changed and not added

    spec = importlib.util.spec_from_file_location("v1076_secret_scan", ROOT / "scripts/secret_scan.py")
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    findings = []
    checked = 0
    for path in sorted(TASK.rglob("*")):
        if not path.is_file() or any(part in ("tmp", "__pycache__") for part in path.relative_to(TASK).parts):
            continue
        value = path.read_text()
        checked += 1
        findings.extend(scanner.scan_text(value, str(path.relative_to(ROOT))))
        for name, pattern in HUB_SECRET_SHAPES:
            for match in pattern.finditer(value):
                line = value.count("\n", 0, match.start()) + 1
                findings.append(f"{path.name}:{line}: {name}")
    print("artifact_files_shape_scanned", checked)
    print("secret_shape_findings", findings)
    assert not findings

    report = (TASK / "report.md").read_text()
    broken = []
    checked_links = 0
    for target in re.findall(r"\]\(([^)]+)\)", report):
        if "://" in target:
            continue
        checked_links += 1
        file_name, _, fragment = target.partition("#")
        path = TASK / file_name
        if not path.is_file():
            broken.append(target)
        elif fragment.startswith("L") and not 1 <= int(fragment[1:]) <= len(path.read_text().splitlines()):
            broken.append(target)
    print("local_evidence_links_checked", checked_links)
    print("broken_links", broken)
    assert not broken

    records = []
    for line in (TASK / "probe.stdout.txt").read_text().splitlines():
        try:
            record = json.loads(line.lstrip("."))
        except ValueError:
            continue
        if "scenario" in record:
            records.append(record)
    print("recorded_scenarios", len(records))
    assert len(records) == 44
    assert "45 passed" in (TASK / "probe.stdout.txt").read_text()
    assert "9 passed, 99 deselected" in (TASK / "existing-tests.stdout.txt").read_text()
    print("git_metadata_present", (ROOT / ".git").exists())
    print("verification PASS")


if __name__ == "__main__":
    main()
