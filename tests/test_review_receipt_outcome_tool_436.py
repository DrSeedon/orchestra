import sqlite3

import pytest


def _seed_receipt(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_receipts (
                receipt_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                runtime TEXT NOT NULL,
                reviewer_model TEXT NOT NULL,
                model_source TEXT NOT NULL,
                session_id TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                task_id TEXT NOT NULL,
                task_source TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                mode TEXT NOT NULL,
                round INTEGER,
                job_id TEXT NOT NULL,
                usage_event_id TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                return_code INTEGER,
                failure_code TEXT NOT NULL,
                artifact_exists INTEGER,
                artifact_bytes INTEGER,
                artifact_sha256 TEXT NOT NULL,
                verdict_present INTEGER,
                verdict_value TEXT NOT NULL,
                jsonl_response_present INTEGER,
                recovery_source TEXT NOT NULL,
                author_outcome TEXT NOT NULL,
                outcome_source TEXT NOT NULL,
                outcome_evidence_ref TEXT NOT NULL,
                notification_event_id TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO review_receipts
            (receipt_id, schema_version, runtime, reviewer_model, model_source,
             session_id, worker_name, scope, task_id, task_source, artifact_path,
             mode, round, job_id, usage_event_id, requested_at, status,
             failure_code, artifact_sha256, verdict_value, recovery_source,
             author_outcome, outcome_source, outcome_evidence_ref,
             notification_event_id)
            VALUES ('receipt-436', 1, 'codex', 'gpt-5.6-luna', 'direct',
                    'session-436', 'worker-436', '/scope', '436', 'session_lookup',
                    '/tmp/review.md', 'exec', 1, 'bg-436', 'usage-436',
                    '2026-09-02T00:00:00Z', 'completed', '', '', '', '',
                    'unknown', 'unknown', '', '')
        """)


@pytest.mark.asyncio
async def test_outcome_tool_is_idempotent_and_rejects_missing_dispute_evidence(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.mcp_stdio as mcp

    db_path = tmp_path / "outcome.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    _seed_receipt(db_path)

    # #493: исход подписывает АВТОР ревью. Тул спрашивает у сервера собственную сессию и
    # сверяет её с квитанцией, поэтому здесь нужна сессия автора — предмет самого теста
    # (идемпотентность и обязательное доказательство спора) от этого не меняется.
    async def _author_session(method, path, **kwargs):
        return {"id": "session-436", "worktree_path": str(tmp_path), "task_id": "436"}

    monkeypatch.setattr(mcp, "_api", _author_session)
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-436")

    first = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": "receipt-436",
        "outcome": "accepted",
        "outcome_evidence_ref": ".orchestra/tasks/436/report.md:1",
    })
    second = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": "receipt-436",
        "outcome": "accepted",
        "outcome_evidence_ref": ".orchestra/tasks/436/report.md:1",
    })
    disputed = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": "receipt-436",
        "outcome": "disputed",
        "outcome_evidence_ref": "",
    })

    assert first.isError is False, "T5 outcome must travel through the MCP tool path"
    assert second.structuredContent == first.structuredContent, (
        "T5 repeated outcome submission must be idempotent"
    )
    assert disputed.isError is True
    assert disputed.structuredContent["error"]["code"] == "invalid_argument"
