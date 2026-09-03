from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    html = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    for marker in (
        "ai-progress-label", "ai-progress", "session.progress_pct", "s.progress_pct",
        "mcp__orchestra__update_progress", "proxy-btn", "proxy-dropdown", "/api/proxy/",
        "payment_receive", "payment_status", "/api/tm/payments", "mcp__yougile__",
    ):
        assert marker not in js and marker not in html, f"dashboard surface remains: {marker}"
    assert "id=\"client-btn\"" in html, "runtime model/proxy client status modal was removed"


if __name__ == "__main__":
    main()
