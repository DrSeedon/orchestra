import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    rows = json.loads((ROOT / "tests/route_surface_snapshot.json").read_text(encoding="utf-8"))
    paths = [path for path, _methods in rows]
    for removed in (
        "/api/sessions/{name}/merge",
        "/api/proxy/list",
        "/api/proxy/check/{proxy_id}",
        "/api/proxy/set-env",
        "/api/tunnel/status",
        "/api/tm/payments",
        "/api/tm/payments/status",
        "/api/tm/payments/history",
        "/api/tm/sync/log",
        "/api/tm/sync/retry/{sync_id}",
    ):
        assert removed not in paths, f"removed route remains in snapshot: {removed}"
    assert paths.count("/api/models/refresh") == 1
    for retained in ("/api/tm/tasks", "/api/sessions/{name}/progress", "/api/merge-operations"):
        assert retained in paths, f"retained route disappeared: {retained}"


if __name__ == "__main__":
    main()
