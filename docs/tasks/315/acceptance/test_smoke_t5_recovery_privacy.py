from pathlib import Path


def test_smoke_t5_recovery_missing_seam():
    assert Path("scripts/ia_pack.py").is_file(), (
        "smoke: session commit/pack/privacy boundary is missing"
    )
