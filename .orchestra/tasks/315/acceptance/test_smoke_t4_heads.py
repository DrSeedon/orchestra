from pathlib import Path


def test_smoke_t4_heads_missing_seam():
    assert Path("app/ia/projections.py").is_file(), (
        "smoke: canonical/projection/indexed heads are missing"
    )
