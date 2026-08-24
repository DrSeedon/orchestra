from pathlib import Path


def test_smoke_t6_merge_receipt_missing_seam():
    assert Path("app/ia/evidence.py").is_file(), (
        "smoke: task-to-evidence merge receipt is missing"
    )
