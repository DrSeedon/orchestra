from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app.ia.runtime import KnowledgeRuntime


def _runtime(tmp_path: Path, content: str) -> KnowledgeRuntime:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sessions(id TEXT, scope TEXT, name TEXT)")
        connection.execute("CREATE TABLE logs(id INTEGER, session_id TEXT, type TEXT, content TEXT)")
        connection.execute("INSERT INTO sessions VALUES('session-398', 'scope', 'worker')")
        connection.execute("INSERT INTO logs VALUES(398, 'session-398', 'agent_msg', ?)", (content,))

    runtime = object.__new__(KnowledgeRuntime)
    runtime.scope_registry = {"scope": {"canonical_project_id": "orchestra"}}
    runtime.state = {
        "canonical_head": "canonical-head",
        "projection_head": "projection-head",
        "indexed_head": "indexed-head",
    }
    runtime._session = lambda _session_id: {
        "scope": "scope",
        "role": "worker",
        "is_orchestrator": 0,
    }

    def connection():
        value = sqlite3.connect(database)
        value.row_factory = sqlite3.Row
        return value

    runtime._connection = connection
    runtime._query_evidence = lambda *_args: ([], [])
    return runtime


def _request() -> Request:
    return Request({
        "type": "http",
        "headers": [
            (b"x-orchestra-session-id", b"session-398"),
            (b"x-orchestra-mcp-proof", b"proof"),
        ],
    })


def test_authorized_runtime_query_summarizes_legacy_content(monkeypatch, tmp_path):
    content = "restart watchdog pidfd " + "x" * 69_980
    runtime = _runtime(tmp_path, content)
    monkeypatch.setattr("app.mcp_proof.check_mcp_proof", lambda _session_id, _proof: True)

    result = runtime.authorized_request(
        _request(),
        {
            "operation": "query",
            "detail": "summary",
            "text": "restart watchdog pidfd",
            "limit": 1,
        },
    )

    item = result["items"][0]
    assert len(item["content"]) <= 1_000
    assert item["content"] == content[:300]
    assert item["content_length"] == len(content)
    assert item["stable_id"]
    assert item["uri"].startswith("orch://project/orchestra/")
    assert item["record_type"] == "session.history"
    assert item["status"] == "current"
    assert item["project_id"] == "orchestra"
    assert item["source"] == "legacy-shadow"
    assert item["source_log_ids"] == [398]
    assert item["canonical_head"] == "canonical-head"
    assert item["projection_head"] == "projection-head"
    assert item["indexed_head"] == "indexed-head"
    assert result["count"] == 1
    assert result["detail"] == "summary"


def test_authorized_runtime_record_and_evidence_keep_full_content(monkeypatch, tmp_path):
    content = "full evidence " + "y" * 69_986
    runtime = _runtime(tmp_path, content)
    monkeypatch.setattr("app.mcp_proof.check_mcp_proof", lambda _session_id, _proof: True)

    for detail in ("record", "evidence"):
        result = runtime.authorized_request(
            _request(),
            {
                "operation": "query",
                "detail": detail,
                "text": "full evidence",
                "limit": 1,
            },
        )
        assert result["items"][0]["content"] == content
        assert result["detail"] == detail
