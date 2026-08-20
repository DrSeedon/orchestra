"""#197 review: negative cache in /api/usage.

Checks:
  1. A failing Grok provider is fetched at most ONCE per _USAGE_FAILURE_TTL on the
     ordinary (force_refresh=False) path.
  2. force_refresh=True / required_provider='grok' STILL performs a live fetch -> the
     quota gate cannot be poisoned by the negative cache. (control arm: must differ)
  3. required_provider='grok' still raises when the provider is down.
  4. Recovery: after failed_at expires, a repaired token is picked up.
  5. Snapshot dict replaced wholesale (session_turns.py) does not crash /api/usage.
"""
import asyncio, json, os, sys, time

sys.path.insert(0, "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/rev197-opus")
import tempfile, pathlib as _pl
_db = _pl.Path(tempfile.mkdtemp()) / "o.db"
os.environ["ORCHESTRA_DB_PATH"] = str(_db)
from app import db as _dbmod
_dbmod.DB_PATH = _db
_dbmod.init_db()
import app.routes.system as S

CALLS = {"n": 0}
R = {}


async def main():
    async def failing_fetch(token):
        CALLS["n"] += 1
        raise PermissionError("token expired")

    S._fetch_grok_usage = failing_fetch
    S._read_grok_token = lambda: "tok"
    # keep anthropic/codex out of the way
    S._usage_cache.update({"data": {"five_hour": {}}, "ts": time.time(), "token": "x"})
    S._codex_usage_cache.update({"data": {"primary": {}}, "ts": time.time()})
    S._grok_usage_cache.clear()
    S._grok_usage_cache.update({"data": None, "ts": 0.0, "failed_at": 0.0})

    # 1. ordinary path, 5 calls
    CALLS["n"] = 0
    for _ in range(5):
        await S._get_usage_data()
    R["ordinary_5_calls_fetches"] = CALLS["n"]

    # 2. control: force_refresh must reach the provider every time
    CALLS["n"] = 0
    for _ in range(3):
        try:
            await S._get_usage_data(force_refresh=True, required_provider="grok")
        except RuntimeError as e:
            R["required_raises"] = str(e)
    R["forced_3_calls_fetches"] = CALLS["n"]

    # 3. recovery after TTL
    async def ok_fetch(token):
        CALLS["n"] += 1
        return {"primary": {"utilization": 7}}

    S._fetch_grok_usage = ok_fetch
    CALLS["n"] = 0
    d = await S._get_usage_data()
    R["immediately_after_repair_fetches"] = CALLS["n"]
    R["immediately_after_repair_data"] = d.get("grok")
    S._grok_usage_cache["failed_at"] = time.time() - S._USAGE_FAILURE_TTL - 1
    CALLS["n"] = 0
    d2 = await S._get_usage_data()
    R["after_ttl_fetches"] = CALLS["n"]
    R["after_ttl_data"] = d2.get("grok")

    # 4. wholesale dict replacement, as session_turns.py does
    S._grok_usage_cache.clear()
    S._grok_usage_cache.update({"data": None, "ts": 0.0})  # NO failed_at key
    try:
        d3 = await S._get_usage_data()
        R["missing_failed_at_key"] = {"ok": True, "grok": d3.get("grok")}
    except Exception as e:
        R["missing_failed_at_key"] = {"ok": False, "err": f"{type(e).__name__}: {e}"}

    R["USAGE_FAILURE_TTL"] = S._USAGE_FAILURE_TTL
    print("JSONRESULT" + json.dumps(R, ensure_ascii=False, default=str))


asyncio.run(main())
