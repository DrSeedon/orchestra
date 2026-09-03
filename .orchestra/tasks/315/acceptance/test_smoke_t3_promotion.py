from pathlib import Path


def test_smoke_t3_promotion_missing_seam():
    assert Path("app/ia/knowledge.py").is_file(), (
        "smoke: evidence-backed promotion seam is missing"
    )
