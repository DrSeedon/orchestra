"""Task-local syntax, import provenance and publication-form checks; no secret inventory."""

import ast
import hashlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import app
from scripts.secret_scan import scan_text


FILES = (
    "app/bg_jobs.py", "app/db.py", "app/manager.py", "app/message_deliveries.py",
    "tests/test_bg_jobs.py", "tests/test_cron_drain_delivery_v1074.py",
    "tests/test_cron_drain_abort_v1074.py", "tests/test_instant_restart.py",
    "tests/test_tg_bridge.py", "CHANGELOG.md",
)


def main():
    print(f"app_import={Path(app.__file__).resolve()}")
    print(f"python={Path(sys.executable).absolute()}")
    artifacts = Path(__file__).resolve().parent
    paths = [ROOT / name for name in FILES]
    paths += sorted(path for path in artifacts.iterdir()
                    if path.is_file() and path.name != "verification.stdout.txt")
    findings = []
    for path in paths:
        body = path.read_text()
        if path.suffix == ".py":
            ast.parse(body, filename=str(path))
        findings.extend(scan_text(body, str(path.relative_to(ROOT))))
        if str(path.relative_to(ROOT)) in FILES:
            print(f"sha256 {path.relative_to(ROOT)} {hashlib.sha256(path.read_bytes()).hexdigest()}")
    if findings:
        raise AssertionError("\n".join(findings))
    print(f"PASS syntax and publication-form scan: {len(paths)} files")
    print("Literal inventory, Git diff and committed-branch checks require the host checkout.")


if __name__ == "__main__":
    main()
