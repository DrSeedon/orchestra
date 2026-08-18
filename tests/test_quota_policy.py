from concurrent.futures import ThreadPoolExecutor

import pytest

import app.db as db
from app.quota_gate import evaluate_worker_admission


NOW = 2_000_000_000.0


def _provider(label: str, utilization: float):
    return {
        "label": label,
        "windows": [{
            "window_minutes": 10080,
            "utilization": utilization,
            "resets_at": "2033-05-18T04:33:20+00:00",
        }],
    }


@pytest.fixture
def policy_db(tmp_path, monkeypatch):
    path = tmp_path / "quota-policy.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.quota_controller_connection(path).close()
    return path


def _providers(codex=10, spark=10):
    return (
        {"codex": _provider("Codex", codex), "codex_spark": _provider("Spark", spark)},
        {"codex": NOW - 10, "codex_spark": NOW - 10},
    )


def test_policy_defaults_and_exact_boundaries(policy_db):
    snapshot = db.quota_policy_snapshot()
    assert snapshot["label"] == "TEMPORARY STATIC OVERRIDE"
    assert {lane: item["threshold"] for lane, item in snapshot["lanes"].items()} == {
        "sol": 95.0, "luna": 98.0, "spark": 95.0, "claude": 90.0,
    }
    anthropic = (
        {"anthropic": _provider("Claude", 89)}, {"anthropic": NOW - 10},
    )
    assert evaluate_worker_admission(
        "claude-opus-5[1m]", *anthropic, now=NOW, policy=snapshot,
    ).allowed
    anthropic = (
        {"anthropic": _provider("Claude", 90)}, {"anthropic": NOW - 10},
    )
    assert not evaluate_worker_admission(
        "claude-opus-5[1m]", *anthropic, now=NOW, policy=snapshot,
    ).allowed
    providers, observed = _providers(codex=94)
    assert evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW, policy=snapshot).allowed
    providers, observed = _providers(codex=95)
    assert not evaluate_worker_admission("gpt-5.6-sol", providers, observed, now=NOW, policy=snapshot).allowed
    providers, observed = _providers(codex=97)
    assert evaluate_worker_admission("gpt-5.6-luna", providers, observed, now=NOW, policy=snapshot).allowed
    providers, observed = _providers(codex=98)
    assert not evaluate_worker_admission("gpt-5.6-luna", providers, observed, now=NOW, policy=snapshot).allowed


def test_policy_update_is_audited_and_persists(policy_db):
    before = db.quota_policy_snapshot()
    changed = db.replace_quota_policy(
        {"luna": 97}, actor="owner", reason="temporary runway correction",
        expected_revision=before["revision"],
    )
    assert changed["revision"] == before["revision"] + 1
    assert changed["lanes"]["luna"]["threshold"] == 97
    assert db.quota_policy_snapshot()["lanes"]["luna"]["threshold"] == 97
    audit = db.quota_policy_audit()
    assert audit[0]["actor"] == "owner"
    assert audit[0]["reason"] == "temporary runway correction"
    assert audit[0]["old"]["luna"] == 98.0
    assert audit[0]["new"]["luna"] == 97.0


@pytest.mark.parametrize("value", [94, 100, "97", float("nan")])
def test_luna_range_is_fail_closed(policy_db, value):
    with pytest.raises((TypeError, ValueError)):
        db.replace_quota_policy({"luna": value}, actor="owner", reason="bad")


def test_rollback_restores_defaults_and_is_audited(policy_db):
    db.replace_quota_policy({"luna": 97}, actor="owner", reason="test change")
    restored = db.rollback_quota_policy(actor="owner", reason="hot rollback")
    assert restored["lanes"]["luna"]["threshold"] == 98
    assert db.quota_policy_audit()[0]["action"] == "rollback"


def test_revision_cas_serializes_concurrent_updates(policy_db):
    revision = db.quota_policy_snapshot()["revision"]

    def update(value):
        try:
            result = db.replace_quota_policy(
                {"luna": value}, actor="owner", reason=f"set {value}",
                expected_revision=revision,
            )
            return "ok", result["revision"]
        except db.QuotaPolicyRevisionMismatch:
            return "cas", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [96, 97]))
    assert sorted(item[0] for item in results) == ["cas", "ok"]
    assert len(db.quota_policy_audit()) == 1
