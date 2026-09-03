import sqlite3


def test_t1_normalizes_every_independent_constraint_and_fast_is_not_a_bucket():
    from app.routes.system import _provider_usage_snapshot

    providers = _provider_usage_snapshot(
        {
            "five_hour": {"utilization": 11, "resets_at": "2030-01-01T05:00:00Z"},
            "seven_day": {"utilization": 22, "resets_at": "2030-01-07T00:00:00Z"},
            "limits": [
                {
                    "kind": "weekly_scoped",
                    "scope_model_display_name": "Fable",
                    "percent": 33,
                    "resets_at": "2030-01-07T00:00:00Z",
                }
            ],
        },
        {
            "plan_type": "pro",
            "primary": {
                "utilization": 44,
                "window_minutes": 10080,
                "resets_at": "2030-01-07T00:00:00Z",
            },
            "spark": {
                "plan_type": "pro",
                "primary": {
                    "utilization": 5,
                    "window_minutes": 10080,
                    "resets_at": "2030-01-07T00:00:00Z",
                },
            },
        },
        {
            "plan_type": "supergrok",
            "primary": {
                "utilization": 66,
                "window_minutes": 10080,
                "resets_at": "2030-01-07T00:00:00Z",
            },
        },
    )

    assert "anthropic_fable" in providers
    assert [window["id"] for window in providers["anthropic"]["windows"]] == [
        "five_hour",
        "seven_day",
    ]
    assert providers["anthropic_fable"]["windows"][0]["utilization"] == 33
    assert set(providers) == {
        "anthropic",
        "anthropic_fable",
        "codex",
        "codex_spark",
        "grok",
    }
    assert "codex_fast" not in providers


def test_t1_grok_observation_has_its_own_freshness(monkeypatch):
    from app.routes import system

    monkeypatch.setattr(
        system,
        "_grok_usage_cache",
        {
            "data": {
                "primary": {
                    "utilization": 7,
                    "window_minutes": 10080,
                    "resets_at": "2030-01-07T00:00:00Z",
                }
            },
            "ts": 123.0,
        },
    )
    observation = system._quota_observation_from_cache()

    assert observation["observed_at_by_provider"]["grok"] == 123.0
    assert "grok" in system._quota_refresh_locks


def test_t1_migrates_durable_shadow_tables_without_changing_old_rows(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE usage_snapshots ("
            "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, five_hour_pct REAL, "
            "seven_day_pct REAL, five_hour_resets_at TEXT, seven_day_resets_at TEXT, "
            "total_cost_usd REAL, active_agents INTEGER, provider_usage TEXT)"
        )
        conn.execute(
            "INSERT INTO usage_snapshots VALUES "
            "(1,'2029-01-01T00:00:00Z',1,2,'a','b',3,4,'{}')"
        )
    before = path.read_bytes()
    monkeypatch.setattr(db, "DB_PATH", path)

    db.init_db()
    db.init_db()

    with sqlite3.connect(path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        old_row = conn.execute(
            "SELECT * FROM usage_snapshots WHERE id=1"
        ).fetchone()
    assert {
        "quota_controller_decisions",
        "quota_controller_outcomes",
        "quota_controller_inflight_reservations",
        "quota_controller_reserve_intents",
        "quota_controller_evidence_sets",
    } <= names
    assert old_row == (1, "2029-01-01T00:00:00Z", 1.0, 2.0, "a", "b", 3.0, 4, "{}")
    assert before != b""  # the fixture itself was real, not a vacuous migration check


def test_t1_audit_rows_are_schema_immutable_and_reservations_have_fk(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "controller.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO quota_controller_decisions "
            "(decision_id,created_at,mode,source,task_class,model,fast_mode,"
            "policy_version,regime_set_hash,observation_json,decision_json,"
            "legacy_decision_json) VALUES "
            "('d1','2030-01-01T00:00:00Z','shadow','dispatch','worker','m',0,1,"
            "'r','{}','{}','{}')"
        )
        conn.execute(
            "INSERT INTO quota_controller_evidence_sets "
            "(evidence_id,created_at,dataset_start,dataset_end,policy_version,"
            "regime_set_hash,source_digest,prospective,metrics_json,reasons_json,eligible) "
            "VALUES ('e1','2030-01-01T00:00:00Z','2029-01-01T00:00:00Z',"
            "'2030-01-01T00:00:00Z',1,'r','sha256:x',1,'{}','[]',0)"
        )
        conn.execute(
            "INSERT INTO quota_controller_outcomes "
            "(decision_id,terminal_event_id,submitted_at,ended_at,settled_at,status,"
            "concurrent_dispatches,actual_json) VALUES "
            "('d1','terminal-1','t','t','t','exact',0,'{}')"
        )
        for sql in (
            "UPDATE quota_controller_decisions SET model='other' WHERE decision_id='d1'",
            "DELETE FROM quota_controller_decisions WHERE decision_id='d1'",
            "INSERT OR REPLACE INTO quota_controller_decisions "
            "(decision_id,created_at,mode,source,task_class,model,fast_mode,"
            "policy_version,regime_set_hash,observation_json,decision_json,"
            "legacy_decision_json) VALUES "
            "('d1','2030-01-01T00:00:00Z','shadow','dispatch','worker','other',0,1,"
            "'r','{}','{}','{}')",
            "UPDATE quota_controller_evidence_sets SET eligible=1 WHERE evidence_id='e1'",
            "DELETE FROM quota_controller_evidence_sets WHERE evidence_id='e1'",
            "INSERT OR REPLACE INTO quota_controller_evidence_sets "
            "(evidence_id,created_at,dataset_start,dataset_end,policy_version,"
            "regime_set_hash,source_digest,prospective,metrics_json,reasons_json,eligible) "
            "VALUES ('e1','2030-01-01T00:00:00Z','2029-01-01T00:00:00Z',"
            "'2030-01-01T00:00:00Z',1,'r','sha256:y',1,'{}','[]',1)",
            "UPDATE quota_controller_outcomes SET status='interval' WHERE decision_id='d1'",
            "DELETE FROM quota_controller_outcomes WHERE decision_id='d1'",
        ):
            try:
                conn.execute(sql)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError(f"immutable audit mutation succeeded: {sql}")

        with __import__("pytest").raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO quota_controller_inflight_reservations "
                "(decision_id,bucket,window_id,reserved_pp,state,created_at,updated_at) "
                "VALUES ('missing','codex:primary','w',1,'reserved','t','t')"
            )
        with __import__("pytest").raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO quota_controller_inflight_reservations "
                "(decision_id,bucket,window_id,reserved_pp,state,created_at,updated_at) "
                "VALUES ('d1','codex:primary','w',-1,'reserved','t','t')"
            )

        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert {
        "idx_quota_controller_decisions_created",
        "idx_quota_controller_inflight_bucket",
        "idx_quota_controller_evidence_created",
    } <= indexes


def test_t1_controller_schema_migration_rolls_back_as_one_unit(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "broken-shape.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE quota_controller_inflight_reservations (broken TEXT)"
        )
    monkeypatch.setattr(db, "DB_PATH", path)

    with __import__("pytest").raises(sqlite3.OperationalError):
        db.init_db()

    with sqlite3.connect(path) as conn:
        created = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'quota_controller_%'"
            )
        }
    assert created == {"quota_controller_inflight_reservations"}
