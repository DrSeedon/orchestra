"""V-695: a spawn cut off between create and initial delivery must still deliver exactly once."""
import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

DELIVERY_ID = "11111111-1111-4111-8111-111111111111"
SCOPE = "/scope-695"
TASK = "do the thing"


class FakeSession:
    def __init__(self, name, worktree, **kw):
        self.id = f"sid-{name}"
        self.name = name
        self.loaded = True
        self.task_id = ""
        self.status = "idle"
        self.total_turns = 0
        self.worktree = worktree
        self._spawn_repo_path = worktree
        self._spawn_git_common_dir = f"{worktree}/.git"
        self._spawn_warning = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "status": self.status,
                "total_turns": self.total_turns, "worktree_path": self.worktree,
                "branch": "task-695/w", "repo_path": self.worktree,
                "git_common_dir": f"{self.worktree}/.git"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import db, initial_deliveries, main
    from app.routes import sessions as routes
    import app.mcp_stdio as m

    db_path = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    sessions: dict[str, FakeSession] = {}
    wakes: list[str] = []
    api_calls: list[tuple[str, str]] = []

    async def create_session(**kw):
        if kw["name"] in sessions:
            raise ValueError(f"worker '{kw['name']}' already exists (idle, ctx:0%). Use send_message instead")
        s = FakeSession(kw["name"], str(repo))
        db.save_session({
            "id": s.id, "name": s.name, "scope": SCOPE, "cwd": str(repo), "model": "gpt-6-luna",
            "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
            "worktree_path": str(repo), "branch": "task-695/w", "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "parent_name": "orch",
        })
        sessions[s.name] = s
        return s

    monkeypatch.setattr(routes.manager, "create_session", create_session)
    monkeypatch.setattr(routes.manager, "get_by_name", lambda n, scope: sessions.get(n))
    monkeypatch.setattr(initial_deliveries, "ensure_delivery_runner", lambda d: wakes.append(d))
    monkeypatch.setattr("app.routes.system._is_safe_path", lambda p: True)
    monkeypatch.setattr(m, "SCOPE", SCOPE)

    ctx = SimpleNamespace(
        sessions=sessions, wakes=wakes, api_calls=api_calls, repo=repo,
        lose=set(), drop=set(), db=db,
    )
    with TestClient(main.app, raise_server_exceptions=False) as client:
        async def api(method, path, **kw):
            api_calls.append((method, path))
            # "lose": the server processes the request but the client never sees the answer
            key = (method, path.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
            if key in ctx.drop:  # the request never reaches the server
                raise m.ApiToolError(code="transport_timeout", message="ReadTimeout",
                                     outcome_unknown=True)
            resp = client.request(method, path, json=kw.get("json"), params=kw.get("params"))
            if key in ctx.lose:
                ctx.lose.discard(key)
                raise m.ApiToolError(code="transport_timeout", message="ReadTimeout",
                                     outcome_unknown=True)
            payload = resp.json()
            if resp.status_code >= 400:
                raise m._response_error(method, path, resp, payload, "rid")
            return payload

        monkeypatch.setattr(m, "_api", api)
        ctx.m = m
        ctx.client = client
        yield ctx


def _rows(ctx):
    with ctx.db._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM initial_deliveries").fetchall()]


async def _spawn(ctx, task=TASK, delivery_id=DELIVERY_ID, name="w"):
    return await ctx.m.spawn_worker(
        name=name, task=task, repo_path=str(ctx.repo), model="gpt-6-luna",
        delivery_id=delivery_id,
    )


@pytest.mark.asyncio
async def test_create_cut_off_but_made_by_server_still_delivers(env):
    env.lose.add(("POST", "sessions"))
    out = await _spawn(env)
    assert "w" in env.sessions
    rows = _rows(env)
    assert len(rows) == 1 and rows[0]["delivery_id"] == DELIVERY_ID
    assert DELIVERY_ID in out


@pytest.mark.asyncio
async def test_retry_after_lost_delivery_delivers_and_double_retry_is_one_delivery(env):
    env.drop.add(("POST", "initial-deliveries"))
    with pytest.raises(env.m.ApiToolError):
        await _spawn(env)
    assert _rows(env) == []  # the original hole: worker exists, no delivery row
    env.drop.clear()
    await _spawn(env)
    await _spawn(env)
    assert len(_rows(env)) == 1
    assert env.wakes == [DELIVERY_ID]


@pytest.mark.asyncio
async def test_name_taken_with_other_task_or_delivery_id_is_refused(env):
    await _spawn(env)
    with pytest.raises(env.m.ApiToolError) as other_task:
        await _spawn(env, task=TASK + " ")
    assert other_task.value.code == "SPAWN_TASK_MISMATCH"
    assert "original exact task text" in other_task.value.message
    with pytest.raises(env.m.ApiToolError) as other_id:
        await _spawn(env, delivery_id="22222222-2222-4222-8222-222222222222")
    assert other_id.value.code == "SPAWN_DELIVERY_ID_MISMATCH"
    assert "another delivery_id" in other_id.value.message
    assert len(_rows(env)) == 1


@pytest.mark.asyncio
async def test_worker_that_already_ran_is_not_given_the_task_again(env):
    env.drop.add(("POST", "initial-deliveries"))
    with pytest.raises(env.m.ApiToolError):
        await _spawn(env)
    env.drop.clear()
    env.sessions["w"].total_turns = 3
    with pytest.raises(env.m.ApiToolError) as caught:
        await _spawn(env)
    assert caught.value.code == "SPAWN_SESSION_NOT_FRESH"
    assert _rows(env) == []


@pytest.mark.asyncio
async def test_create_never_reached_server_reports_delivery_id_for_retry(env):
    orig = env.m._api

    # no session exists, so resume answers 404 while the create timed out
    async def timeout_create(method, path, **kw):
        if path == "/api/sessions":
            raise env.m.ApiToolError(code="transport_timeout", message="ReadTimeout",
                                     outcome_unknown=True)
        return await orig(method, path, **kw)
    env.m._api = timeout_create
    with pytest.raises(env.m.ApiToolError) as caught:
        await _spawn(env, delivery_id="")
    nxt = caught.value.details["next_action"]
    assert nxt["code"] == "RETRY_SPAWN_SAME_DELIVERY_ID" and nxt["delivery_id"]


@pytest.mark.asyncio
async def test_spawn_rejects_invalid_delivery_id_before_creating_worker(env):
    with pytest.raises(env.m.ApiToolError) as caught:
        await _spawn(env, delivery_id="spawn-research-step5-v807")

    assert caught.value.code == "invalid_argument"
    assert caught.value.message == "delivery_id must be a UUID"
    assert env.api_calls == []
    assert env.sessions == {}
    assert _rows(env) == []
    assert env.db.get_all_sessions(SCOPE) == []


def test_http_rejects_invalid_delivery_id_before_creating_worker(env, monkeypatch):
    from app.routes import sessions as routes

    calls = []

    async def forbidden_create(**kwargs):
        calls.append(kwargs)
        raise AssertionError("invalid delivery_id reached session creation")

    monkeypatch.setattr(routes.manager, "create_session", forbidden_create)
    response = env.client.post("/api/sessions", json={
        "name": "bad-id", "cwd": str(env.repo), "model": "gpt-6-luna",
        "use_worktree": True, "repo_path": str(env.repo), "task_id": "V-807",
        "planned_initial_turn": True, "initial_task_title": TASK,
        "initial_delivery_id": "spawn-research-step5-v807",
    })

    assert response.status_code == 422
    assert "initial_delivery_id must be a UUID" in response.text
    assert calls == []
    assert env.sessions == {}
    assert _rows(env) == []
    assert env.db.get_all_sessions(SCOPE) == []


def test_http_spawn_accepts_valid_delivery_id_and_records_intent(env):
    response = env.client.post("/api/sessions", json={
        "name": "good-id", "cwd": str(env.repo), "model": "gpt-6-luna",
        "use_worktree": True, "repo_path": str(env.repo),
        "planned_initial_turn": True, "initial_task_title": TASK,
        "initial_delivery_id": DELIVERY_ID,
    })

    assert response.status_code == 201
    assert response.json()["name"] == "good-id"
    assert json.loads(env.db.kv_get("spawn_intent:sid-good-id"))["delivery_id"] == DELIVERY_ID
