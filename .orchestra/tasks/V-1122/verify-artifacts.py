"""Offline integrity checks for V-1122 research artifacts; no app/foreign imports."""

import ast
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(".orchestra/tasks/V-1122")
EVIDENCE = ROOT / "evidence"
CODE = EVIDENCE / "public-code"

LOCAL_SOURCES = (
    "app/backend_codex.py", "app/backend_hub.py", "app/backend_harness.py",
    "app/harness/loop.py", "app/harness/mcp.py", "app/harness/tools.py",
    "app/harness/sessions.py", "app/harness/llm.py", "app/hub_workspace.py",
    "app/hub_outbox.py", "app/mcp_stdio.py", "app/message_deliveries.py",
    "app/bg_jobs.py", "app/initial_delivery_events.py",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    report = (ROOT / "report.md").read_text()
    for path in ROOT.glob("*.py"):
        ast.parse(path.read_text(), filename=path.name)
    print("PASS: research Python scripts parse without importing or running foreign code")

    # Compare with the saved research snapshot; verification must never refresh it.
    source_records = json.loads((EVIDENCE / "orchestra-source-manifest.json").read_bytes())
    assert len(source_records) == len(LOCAL_SOURCES)
    assert {record["path"] for record in source_records} == set(LOCAL_SOURCES)
    mismatches = []
    for record in source_records:
        rel = record["path"]
        try:
            data = Path(rel).read_bytes()
        except OSError as exc:
            mismatches.append(f"{rel}: cannot read source ({type(exc).__name__})")
            continue
        actual_hash = digest(data)
        if actual_hash != record["sha256"] or len(data) != record["bytes"]:
            mismatches.append(
                f"{rel}: saved sha256={record['sha256']} bytes={record['bytes']}; "
                f"current sha256={actual_hash} bytes={len(data)}"
            )
    if mismatches:
        print("FAIL: sources differ from saved orchestra-source-manifest.json; manifest not changed")
        print("\n".join(mismatches))
        raise SystemExit(1)
    print(f"PASS: {len(source_records)} local source files match the saved manifest; no app imported")

    pins = {}
    for repo in ("sentinelx-cloud-core", "sentinelx-cloud-installer", "sentinelx-cloud-protocol"):
        commits = json.loads((EVIDENCE / f"{repo}.commits.json").read_text())
        metadata = json.loads((EVIDENCE / f"{repo}.metadata.json").read_text())
        assert metadata["license"]["spdx_id"] == "Apache-2.0"
        pins[repo] = commits[0]["sha"]
    references = re.findall(
        r"https://github\.com/pensados/([^/]+)/blob/([a-f0-9]{40})/([^\s)]+)", report
    )
    for repo, pin, path_anchor in references:
        assert pin == pins[repo], f"unmatched pin: {repo}"
        path, _, anchor = path_anchor.partition("#")
        snapshot = CODE / f"{repo}--{path.replace('/', '__')}.txt"
        assert snapshot.exists(), f"missing public source: {snapshot.name}"
        maximum = int(snapshot.read_text().splitlines()[-1].split()[0])
        for number in re.findall(r"L(\d+)", anchor):
            assert int(number) <= maximum, f"invalid source line: {snapshot.name}"
    print(f"PASS: {len(references)} pinned source links resolve to retained files and valid line bounds")

    secret_shapes = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"sk-(?:proj-)?[A-Za-z0-9_-]{30,}",
        r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}",
        r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b",
    )
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        private_path_pattern = r"/home/" + r"claude-|orchestra-" + r"ws/|hub-" + r"e[0-9a-f]{12}"
        assert not re.search(private_path_pattern, text), (
            f"private environment path in {path.name}"
        )
        for pattern in secret_shapes:
            assert not re.search(pattern, text), f"secret-shaped candidate in {path.name}"
    print("PASS: task artifacts contain no detected private environment paths or tested secret shapes")

    pages = json.loads((EVIDENCE / "public-pages.stdout.json").read_text())
    failures = [p for p in pages if "error" in p]
    assert len(pages) == 21
    print(f"Public-page collector: {len(pages) - len(failures)}/{len(pages)} HTTP success; "
          f"{len(failures)} access errors retained explicitly")
    for failure in failures:
        print(f"  {failure['error']} {failure.get('status', '')}: {failure['url']}")
    print("NOT RUN: live ChatGPT/SentinelX E2E, foreign tests, application pytest, model calls")
    print("Research artifact checks completed")


if __name__ == "__main__":
    main()
