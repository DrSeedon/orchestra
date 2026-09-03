from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    src = (ROOT / "app/routes/sessions.py").read_text(encoding="utf-8")
    assert '@router.post("/api/sessions/{name}/merge")' not in src
    assert "async def merge_session(" not in src
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'method == "POST"' in main_src
    assert 'parts[1:3] == ["api", "sessions"]' in main_src
    assert 'parts[4] == "merge"' in main_src
    assert "MERGE_OPERATION_REQUIRED" in main_src
    assert "execute_merge_session" in src


if __name__ == "__main__":
    main()
