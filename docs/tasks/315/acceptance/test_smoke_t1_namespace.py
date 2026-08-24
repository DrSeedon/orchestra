from pathlib import Path


def test_smoke_t1_namespace_missing_seam():
    assert Path("app/ia/namespace.py").is_file(), (
        "smoke: canonical typed namespace resolver is missing"
    )
