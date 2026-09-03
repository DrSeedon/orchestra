from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    for rel in ("app/tm_yougile.py", "app/tm_import_yougile.py"):
        assert not (ROOT / rel).exists(), f"YouGile service file remains: {rel}"
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "tm_yougile" not in main_src
    route_src = (ROOT / "app/routes/tm.py").read_text(encoding="utf-8")
    for marker in ("tm_yougile", "yougile_sync_task", "/sync/log", "/sync/retry"):
        assert marker not in route_src, f"YouGile HTTP/service marker remains: {marker}"
    tm_src = (ROOT / "app/tm.py").read_text(encoding="utf-8")
    for marker in ("yougile", "on_task_synced", "_fire_sync"):
        assert marker not in tm_src, f"YouGile task hook remains: {marker}"
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    assert "mcp__yougile__" not in js


if __name__ == "__main__":
    main()
