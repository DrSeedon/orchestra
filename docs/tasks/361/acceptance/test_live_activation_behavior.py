"""Frozen behavior oracle for #361 live typed-knowledge activation.

This suite is hermetic: temporary SQLite/Git/state roots only, no app.main lifespan, TG, provider,
model, vector embedder, service restart, or production path.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


KNOWLEDGE_ANCHOR = (
    "Use the single `knowledge` tool for canonical knowledge and evidence operations."
)
REQUIRED_GATES = {
    "shadow_parity", "privacy", "rollback", "prompt_delivery", "live_cutover", "projection",
}


def _runtime_api(ticket: str):
    spec = importlib.util.find_spec("app.ia.runtime")
    assert spec is not None, f"#361 {ticket} missing production KnowledgeRuntime owner"
    module = importlib.import_module("app.ia.runtime")
    assert callable(getattr(module, "knowledge_runtime_mode", None)), (
        f"#361 {ticket} missing production KnowledgeRuntime owner"
    )
    assert callable(getattr(module, "production_runtime_config", None)), (
        f"#361 {ticket} missing production runtime configuration"
    )
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _repository(root: Path, *, marker: str = "scope-one-needle") -> tuple[Path, str, bytes]:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    source = root / "docs" / "kb" / "topic.md"
    source.parent.mkdir(parents=True)
    body = f"# topic\n\n{marker}\n".encode()
    source.write_bytes(body)
    (root / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-DO-NOT-IMPORT\n")
    _git(root, "add", "docs/kb/topic.md")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD"), body


def _legacy_db(tmp_path: Path, monkeypatch, repos: dict[str, Path]) -> tuple[Path, dict[str, str]]:
    from app import db, tm

    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(tm, "_conn", db._conn)
    db.init_db()
    sessions: dict[str, str] = {}
    with db._conn() as connection:
        for index, (scope, repo) in enumerate(repos.items(), start=1):
            project_id = "VPN-Service" if index == 1 else f"project-{index}"
            if index == 1:
                # Preserve the production-shaped pre-normalization ID. ensure_project intentionally
                # casefolds new IDs, which made the first frozen oracle fail in fixture setup before
                # it could exercise runtime behavior.
                connection.execute(
                    """INSERT INTO tm_projects(id,name,scope,created_at,prefix)
                       VALUES(?,?,?,?,?)""",
                    (
                        project_id,
                        project_id,
                        scope,
                        datetime.now(timezone.utc).isoformat(),
                        "VPN",
                    ),
                )
            else:
                project_id = tm.ensure_project(connection, project_id, scope=scope)["id"]
            session_id = f"session-{index}"
            native_id = f"native-context-{index}"
            sessions[session_id] = native_id
            connection.execute(
                """INSERT INTO sessions(
                       id,name,scope,cwd,model,status,session_id,is_orchestrator,role,
                       backend_type,created_at,system_prompt,prompt_overlay
                   ) VALUES(?,?,?,?,?,'idle',?,0,'worker','codex',?,?,?)""",
                (
                    session_id, f"worker-{index}", scope, str(repo), "test-model", native_id,
                    datetime.now(timezone.utc).isoformat(),
                    "<role>legacy worker</role>\n<memory-search>search_memory legacy</memory-search>",
                    None,
                ),
            )
            tm.create_task(connection, project_id, f"task-{index}")
    for index, session_id in enumerate(sessions, start=1):
        db.add_log(
            session_id,
            datetime.now(timezone.utc),
            "user_message",
            "scope-one-needle" if index == 1 else "scope-two-private-needle",
        )
    return db_path, sessions


def test_control_legacy_fixture_reaches_tasks_sessions_and_logs(tmp_path, monkeypatch):
    repo1, _, _ = _repository(tmp_path / "fixture-one")
    repo2, _, _ = _repository(tmp_path / "fixture-two", marker="scope-two-private-needle")
    db_path, sessions = _legacy_db(
        tmp_path,
        monkeypatch,
        {str(repo1): repo1, str(repo2): repo2},
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT count(*) FROM tm_tasks").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM logs").fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM tm_projects WHERE id='VPN-Service'"
        ).fetchone()[0] == 1
    assert sessions == {"session-1": "native-context-1", "session-2": "native-context-2"}


def _config(api, tmp_path: Path, db_path: Path, repos: dict[str, Path]):
    from app.pipeline import build_system_prompt

    return api.RuntimeConfig(
        state_root=tmp_path / "state",
        legacy_db_path=db_path,
        vector_db_path=tmp_path / "legacy-vector.db",
        scope_roots=repos,
        prompt_assembler=lambda _runtime, role: build_system_prompt("default", role),
    )


async def _post(payload: dict, *, session_id: str, proof: str) -> httpx.Response:
    from app.routes.knowledge import router

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://knowledge.test") as client:
        return await client.post(
            "/api/knowledge",
            json=payload,
            headers={
                "X-Orchestra-Session-Id": session_id,
                "X-Orchestra-Mcp-Proof": proof,
            },
        )


@pytest.mark.asyncio
async def test_t1_scoped_mcp_query_is_live_and_authorized(tmp_path, monkeypatch):
    api = _runtime_api("T1")
    repo1, _, _ = _repository(tmp_path / "repo-one")
    repo2, _, _ = _repository(tmp_path / "repo-two", marker="scope-two-private-needle")
    repos = {str(repo1): repo1, str(repo2): repo2}
    db_path, sessions = _legacy_db(tmp_path, monkeypatch, repos)
    from app.mcp_proof import issue_mcp_proof

    proof = issue_mcp_proof("session-1")
    with api.knowledge_runtime_mode(_config(api, tmp_path, db_path, repos)) as owner:
        assert owner.state["active_owner"] == "legacy"
        assert owner.state["generation"] == 2
        response = await _post(
            {"operation": "query", "detail": "summary", "payload": {"query": "scope-one-needle"}},
            session_id="session-1",
            proof=proof,
        )
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["project_id"] == owner.scope_registry[str(repo1)]["canonical_project_id"]
        assert value["count"] >= 1
        assert all(item["project_id"] == value["project_id"] for item in value["items"])

        cross = await _post(
            {"operation": "query", "payload": {"query": "scope-two-private-needle"}},
            session_id="session-1",
            proof=proof,
        )
        assert cross.status_code == 200 and cross.json()["count"] == 0
        conflict = await _post(
            {"operation": "query", "payload": {"query": "x", "project_id": "other"}},
            session_id="session-1",
            proof=proof,
        )
        assert conflict.status_code == 403
        mutation = await _post(
            {"operation": "promote", "payload": {"request": {}}},
            session_id="session-1",
            proof=proof,
        )
        assert mutation.status_code == 403

    assert sessions == {"session-1": "native-context-1", "session-2": "native-context-2"}


def test_t2_task_shadow_is_concurrent_restart_safe_and_debt_bound(tmp_path, monkeypatch):
    api = _runtime_api("T2")
    repo, _, _ = _repository(tmp_path / "repo")
    repos = {str(repo): repo}
    db_path, _ = _legacy_db(tmp_path, monkeypatch, repos)
    config = _config(api, tmp_path, db_path, repos)
    from app import tm

    with api.knowledge_runtime_mode(config) as owner:
        receipt_before = owner.receipt_bytes("shadow")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(tm.api_create_task, "VPN-Service", f"concurrent-{index}")
                for index in (1, 2)
            ]
            created = [future.result(timeout=10) for future in futures]
        assert len({item["par"] for item in created}) == 2
        assert owner.parity()["mismatch_count"] == 0
        canonical = owner.paths["canonical_root"].resolve()
        assert all(path.resolve().is_relative_to(canonical) for path in canonical.rglob("*.json"))

    with api.knowledge_runtime_mode(config) as reopened:
        assert reopened.state["generation"] == 2
        assert reopened.receipt_bytes("shadow") == receipt_before
        monkeypatch.setattr(
            reopened.task_store,
            "task_update",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("candidate failed")),
        )
        result = tm.api_update_task("1", title="legacy survives", project="VPN-Service")
        assert result["title"] if "title" in result else result["updated"]
        assert result["shadow_match"] is False
        assert result["projection_debt"]
        assert reopened.state["debt_count"] >= 1
        with pytest.raises(Exception):
            reopened.cutover({
                "operation": "canonical",
                "expected_generation": 2,
                "required_gates": sorted(REQUIRED_GATES),
            })


def test_t3_git_evidence_is_pinned_private_and_projection_rebuildable(tmp_path, monkeypatch):
    api = _runtime_api("T3")
    repo, commit, body = _repository(tmp_path / "repo", marker="pinned-git-needle")
    repos = {str(repo): repo}
    db_path, _ = _legacy_db(tmp_path, monkeypatch, repos)
    vector = tmp_path / "legacy-vector.db"
    vector.write_bytes(b"retained-vector-projection")
    vector_before = hashlib.sha256(vector.read_bytes()).hexdigest()
    config = api.RuntimeConfig(
        state_root=tmp_path / "state",
        legacy_db_path=db_path,
        vector_db_path=vector,
        scope_roots=repos,
        prompt_assembler=_config(api, tmp_path, db_path, repos).prompt_assembler,
    )

    with api.knowledge_runtime_mode(config) as owner:
        refs = owner.evidence_records()
        topic = next(item for item in refs if item["source_path"] == "docs/kb/topic.md")
        assert topic["git_commit"] == commit
        assert topic["git_blob"] == _git(repo, "rev-parse", f"{commit}:docs/kb/topic.md")
        assert topic["source_sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
        assert "content" not in topic
        assert all(item["source_path"] != ".env" for item in refs)
        canonical_bytes = b"".join(path.read_bytes() for path in owner.paths["canonical_root"].rglob("*.json"))
        assert b"sk-or-v1-DO-NOT-IMPORT" not in canonical_bytes

        (repo / "docs/kb/topic.md").write_text("mutated working tree")
        result = owner.query_for_scope(str(repo), "pinned-git-needle")
        assert result["count"] >= 1
        with pytest.raises(Exception):
            owner.import_evidence({
                **topic,
                "git_commit": "0" * 40,
            })
        owner.paths["current_projection"].unlink()
        fallback = owner.query_for_scope(str(repo), "pinned-git-needle")
        assert fallback["count"] >= 1
        assert any(item.get("source") == "canonical-fallback" for item in fallback["items"])
        assert fallback["debt"]

    assert vector.exists()
    assert hashlib.sha256(vector.read_bytes()).hexdigest() == vector_before


def test_t4_cutover_receipts_survive_restart_and_keep_projections(tmp_path, monkeypatch):
    api = _runtime_api("T4")
    repo, _, _ = _repository(tmp_path / "repo")
    repos = {str(repo): repo}
    db_path, _ = _legacy_db(tmp_path, monkeypatch, repos)
    config = _config(api, tmp_path, db_path, repos)

    with api.knowledge_runtime_mode(config) as owner:
        first_shadow = owner.receipt_bytes("shadow")
        gates = owner.verify_gates()
        assert set(gates) == REQUIRED_GATES
        assert all(gate["status"] == "verified" for gate in gates.values())
        paths = {name: Path(path) for name, path in owner.paths.items() if name.endswith("projection")}
        before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
        canonical = owner.cutover({
            "operation": "canonical",
            "expected_generation": 2,
            "required_gates": sorted(REQUIRED_GATES),
        })
        assert canonical["generation"] == 3 and canonical["active_owner"] == "canonical"

    with api.knowledge_runtime_mode(config) as reopened:
        assert reopened.state["generation"] == 3
        assert reopened.receipt_bytes("shadow") == first_shadow
        with pytest.raises(Exception):
            reopened.cutover({
                "operation": "canonical",
                "expected_generation": 3,
                "required_gates": sorted(REQUIRED_GATES),
                "remove_projection": True,
            })
        rolled = reopened.cutover({
            "operation": "rollback", "expected_generation": 3, "target_owner": "legacy",
        })
        assert rolled["generation"] == 4 and rolled["active_owner"] == "legacy"
        after = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
        assert after == before

    with api.knowledge_runtime_mode(config) as rolled_reopen:
        assert rolled_reopen.state["generation"] == 4
        assert rolled_reopen.state["active_owner"] == "legacy"


def test_t5_prompt_and_restart_delivery_preserve_native_sessions(tmp_path, monkeypatch):
    api = _runtime_api("T5")
    repo, _, _ = _repository(tmp_path / "repo")
    repos = {str(repo): repo}
    db_path, sessions = _legacy_db(tmp_path, monkeypatch, repos)
    from app import db
    from app.manager import SessionManager
    from app.mcp_stdio import mcp

    manager = SessionManager()
    rebuilt, overlay = manager.assemble_prompt(
        pipeline="default", role="worker", scope=str(repo), is_orch=False,
        name="worker-1", owned_dirs=None, branch="", stored_overlay=None,
        old_prompt="<role>legacy worker</role>\n<memory-search>search_memory legacy</memory-search>",
        repository_path=str(repo),
    )
    assert KNOWLEDGE_ANCHOR in rebuilt
    assert overlay is not None
    custom = "operator-owned full prompt"
    preserved, custom_overlay = manager.assemble_prompt(
        pipeline="default", role="worker", scope=str(repo), is_orch=False,
        name="worker-1", owned_dirs=None, branch="", stored_overlay=None,
        old_prompt=custom, repository_path=str(repo),
    )
    assert preserved == custom and custom_overlay is None

    config = _config(api, tmp_path, db_path, repos)
    with api.knowledge_runtime_mode(config):
        pass
    with api.knowledge_runtime_mode(config):
        pass
    with db._conn() as connection:
        observed = {
            row["id"]: row["session_id"]
            for row in connection.execute(
                "SELECT id,session_id FROM sessions WHERE id IN ('session-1','session-2')"
            ).fetchall()
        }
    assert observed == sessions
    tools = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert "knowledge" in tools and "search_memory" in tools

    for service in (Path("deploy/orchestra.service"), Path("deploy/orchestra.service.template")):
        assert "StateDirectory=orchestra" in service.read_text()
    activation = Path("scripts/activate_knowledge.py")
    assert activation.is_file(), "#361 T5 missing activation CLI"
    text = activation.read_text().lower()
    assert "clear-session" not in text
    assert "projection_delete" not in text and "remove_projection" not in text
    assert "provider" not in text and "model" not in text
