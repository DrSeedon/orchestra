"""Check only this task's publication artifacts; never inventory secrets or env."""
from pathlib import Path
import re
import sys

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
sys.path.insert(0, str(ROOT))
from app.publication_secrets import archive_findings


def main():
    transcript = TASK / "06-model-and-scope.txt"
    text = transcript.read_text()
    text = re.sub(r"\b[\w.-]+@[\w.-]+(?=\(none\))", "[remote-user]@[remote-host].", text)
    text = re.sub(r"/remote/home/orchestra-ws/[^\s'\",)]+", "/remote/workspace", text)
    transcript.write_text(text)

    report = (TASK / "REPORT.md").read_text()
    rows = re.findall(r"^\| (\d{2}) ", report, re.M)
    assert rows == [f"{number:02d}" for number in range(1, 39)], rows
    print("map_surface_operation_rows=38; contiguous unique ids=PASS")
    for path, line in re.findall(r"(?<![\w/])((?:app|tests)/[\w./-]+\.(?:py|js)):(\d+)", report):
        source = ROOT / path
        assert source.is_file(), path
        assert 0 < int(line) <= len(source.read_text().splitlines()), (path, line)
    print("explicit app/tests file:line reference bounds=PASS")
    candidates = sorted(path for path in TASK.iterdir() if path.is_file())
    findings = []
    for path in candidates:
        payload = path.read_text()
        assert str(ROOT) not in payload, path.name
        assert str(Path.home()) not in payload, path.name
        assert Path.home().name not in payload, path.name
        findings.extend(archive_findings(payload, path.name, []))
    assert not findings, findings
    print(f"top_level_text_artifacts_checked={len(candidates)}")
    print("credential_shape_scan=PASS (shared archive_findings with empty literal inventory)")
    print("checkout/home/account path scan=PASS")
    print(f"report_bytes={len(report.encode())}; report_words={len(report.split())}")
    print("ARTIFACT AUDIT PASSED")


if __name__ == "__main__":
    main()
