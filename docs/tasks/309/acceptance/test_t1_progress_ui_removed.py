from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    for marker in (
        "ai-progress-label",
        "ai-progress",
        "session.progress_pct",
        "s.progress_pct",
        "mcp__orchestra__update_progress",
    ):
        assert marker not in js, f"progress UI marker remains: {marker}"
    assert "async def update_progress" in (ROOT / "app/mcp_stdio.py").read_text(encoding="utf-8")
    assert "/api/sessions/{name}/progress" in (ROOT / "app/routes/sessions.py").read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
