import json


def test_receipt_round_trip_preserves_provenance_and_unknowns(tmp_path, monkeypatch):
    import app.db as db

    db_path = tmp_path / "storage.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    receipt = {
        "receipt_id": "review-436-storage",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-436",
        "worker_name": "worker-436",
        "scope": "/scope",
        "task_id": "436",
        "task_source": "session_lookup",
        "artifact_path": "/tmp/review.md",
        "mode": "exec",
        "round": 1,
        "job_id": "bg-436",
        "usage_event_id": "codex-review:436",
        "status": "requested",
        "return_code": None,
        "failure_code": "",
        "artifact_exists": None,
        "artifact_bytes": None,
        "artifact_sha256": "",
        "verdict_present": None,
        "verdict_value": "",
        "jsonl_response_present": None,
        "recovery_source": "",
        "author_outcome": "unknown",
        "outcome_source": "unknown",
        "outcome_evidence_ref": "",
        "notification_event_id": "",
    }

    create = getattr(db, "review_receipt_create", None)
    assert callable(create), "T1 receipt storage API is missing"
    assert create(receipt) is True, "T1 receipt insert must be idempotent"
    saved = db.review_receipt_get(receipt["receipt_id"])
    assert saved["receipt_id"] == receipt["receipt_id"]
    assert saved["model_source"] == "direct"
    assert saved["author_outcome"] == "unknown"
    assert json.loads(json.dumps(saved, sort_keys=True))["runtime"] == "codex"
