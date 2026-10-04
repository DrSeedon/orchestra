"""Isolated demo stand for README screenshots (V-686).

Runs the REAL dashboard (routers, templates, static JS/CSS from a `git archive` copy)
on a throwaway SQLite DB with fake agents. Never the production lifespan: no
load_dotenv, no auto_resume, no bootstrap orchestrator, no TG bridge, no CLI spawns.

Run from the copy's root (so `import app` resolves to the copy):
    env -i HOME=/srv/demo PATH=/usr/bin:/bin STAND=<dir> \
        /home/kesha/orchestra/.venv/bin/python <this file>
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

STAND = Path(os.environ["STAND"])
SCOPE = "/srv/demo/acme-shop"
os.environ.update({
    "ORCHESTRA_DB_PATH": str(STAND / "data/orchestra.db"),
    "ORCHESTRA_TASK_REPOSITORY": str(STAND / "tasks"),
    "ORCHESTRA_PROJECT_CATALOG": str(STAND / "catalog.yaml"),
    "ORCHESTRA_PROJECT_CATALOG_ROOT": str(STAND / "catalog-root"),
    "CURRENCY_SYMBOL": "$",
    "OWNER_MODE": "1",  # quota history and charts are owner-only views
})
for leak in [k for k in os.environ if k.startswith(("TG_", "TELEGRAM", "ANTHROPIC", "OPENAI", "DEEPGRAM"))]:
    del os.environ[leak]

sys.path.insert(0, os.getcwd())
import app as _app_pkg  # noqa: E402

assert Path(_app_pkg.__file__).resolve().is_relative_to(Path.cwd().resolve()), _app_pkg.__file__
assert not Path(".env").exists(), "stand copy must not carry a .env"
import shutil  # noqa: E402
assert not any(shutil.which(b) for b in ("claude", "codex", "grok")), "provider CLIs must be off the stand PATH"

(STAND / "catalog.yaml").write_text(
    "version: 1\nprojects:\n"
    "- tag: acme-shop\n  name: Acme Shop\n"
    f"  scope: {SCOPE}\n  write_namespace: acme-shop\n"
    "  namespaces:\n    acme-shop: ''\n"
)

from app import main  # noqa: E402
from app import db as database  # noqa: E402

database.DB_PATH = database._db_path_from_env()
assert str(database.DB_PATH).startswith(str(STAND)), database.DB_PATH


@asynccontextmanager
async def stand_lifespan(_app):
    from app.db import init_db, _conn
    from app.task_runtime import task_runtime_mode, production_runtime
    from app.tm import sync_catalog
    init_db()
    database.ensure_owner_activity_schema()
    with _conn() as connection:
        sync_catalog(connection)
    with task_runtime_mode(production_runtime()):
        import seed
        seed.run(SCOPE)
        refresher = asyncio.create_task(_fake_quota_loop())
        yield
        refresher.cancel()


def _fake_quota() -> None:
    """Provider quotas the stand cannot fetch (no credentials) — fed into the real caches."""
    from datetime import datetime, timedelta, timezone
    from app.routes import system
    now = datetime.now(timezone.utc)
    later = lambda **kw: (now + timedelta(**kw)).isoformat()  # noqa: E731
    t = time.time()
    system._usage_cache.update(ts=t, data={
        "five_hour": {"utilization": 34.0, "resets_at": later(hours=2, minutes=41)},
        "seven_day": {"utilization": 58.0, "resets_at": later(days=2, hours=9)},
    })
    system._codex_usage_cache.update(ts=t, data=system._normalize_codex_usage({"rateLimits": {
        "planType": "pro",
        "primary": {"usedPercent": 22, "windowDurationMins": 300, "resetsAt": int(t + 3 * 3600 + 900)},
        "secondary": {"usedPercent": 41, "windowDurationMins": 10080, "resetsAt": int(t + 4 * 86400)},
    }}))
    system._grok_usage_cache.update(ts=t, failed_at=0.0, data=system._normalize_grok_usage({"config": {
        "creditUsagePercent": 12,
        "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY",
                          "start": (now - timedelta(days=2)).isoformat(), "end": later(days=5)},
    }}))


async def _fake_quota_loop() -> None:
    while True:
        _fake_quota()
        await asyncio.sleep(30)


main.app.router.lifespan_context = stand_lifespan

# Cosmetics the stand needs because its agents are rows, not live CLIs:
# a live agent shows "event reader active", a detached row "runtime not loaded".
from app.deps import manager  # noqa: E402
from app import quota_gate  # noqa: E402

_list_sessions = manager.list_sessions


def _stand_list_sessions(scope=None):
    rows = _list_sessions(scope)
    for row in rows:
        row["runtime_connection"] = "listening" if row.get("status") in ("running", "waiting") else "hibernated"
    return rows


manager.list_sessions = _stand_list_sessions
# Keep the owner-only gate pill in the dashboard's Russian locale.
quota_gate.LANE_LABELS["claude"] = "Claude-воркеры"


@main.app.post("/stand/live")
async def _stand_live(slow: float = 1.0):
    import seed
    asyncio.create_task(seed.live(slow))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    sys.path.insert(0, str(Path(__file__).parent))
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8897")), log_level="warning")
