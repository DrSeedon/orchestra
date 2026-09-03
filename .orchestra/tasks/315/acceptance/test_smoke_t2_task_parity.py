from pathlib import Path


def test_smoke_t2_task_facade_missing_seam():
    assert Path("app/ia/task_store.py").is_file(), (
        "smoke: stable task identity facade is missing"
    )
