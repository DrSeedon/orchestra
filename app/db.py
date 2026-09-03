"""SQLite storage for sessions and logs."""

import json
import logging
import math
import os
import re
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("db")

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"

def _resolve_db_path() -> Path:
    """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.

    Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
    друг друга через SQLite-лок при параллельной работе.
    """
    override = os.getenv("ORCHESTRA_DB_PATH", "").strip()
    if not override:
        return _DEFAULT_DB_PATH
    p = Path(override)
    return p if p.is_absolute() else (Path(__file__).parent.parent / p)


DB_PATH = _resolve_db_path()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # WAL: readers don't block writers — essential when many agents log concurrently
    conn.execute("PRAGMA journal_mode=WAL")
    # 5s busy timeout: retry on locked DB instead of raising immediately
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                active_turn_id TEXT DEFAULT '',
                leftover TEXT DEFAULT '',
                -- NOT NULL для новых БД; существующие закрывает триггер в _guard_session_id:
                -- ужесточить колонку без перестройки таблицы SQLite не даёт (#54)
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                cwd TEXT NOT NULL,
                model TEXT NOT NULL,
                system_prompt TEXT DEFAULT '',
                prompt_overlay TEXT,
                status TEXT DEFAULT 'starting',
                session_id TEXT,
                cost_usd REAL DEFAULT 0.0,
                worktree_path TEXT,
                branch TEXT,
                base_branch TEXT DEFAULT '',
                needs_switch INTEGER DEFAULT 0,
                is_orchestrator INTEGER DEFAULT 0,
                color TEXT DEFAULT '',
                mcp_servers_custom TEXT DEFAULT '',
                profile TEXT DEFAULT '',
                runtime_handoff TEXT DEFAULT '',
                history_import_source TEXT,
                last_summary TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(name, scope)
            );
            CREATE TABLE IF NOT EXISTS undelivered_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, dedupe_key)
            );
            CREATE TABLE IF NOT EXISTS profiles (
                name TEXT PRIMARY KEY,
                config_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                capability_verifier BLOB NOT NULL
                    CHECK(length(capability_verifier) = 32),
                stored_name TEXT NOT NULL UNIQUE,
                content_sha256 BLOB NOT NULL CHECK(length(content_sha256) = 32),
                display_name TEXT NOT NULL,
                publisher_session_id TEXT NOT NULL,
                publisher_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                size_bytes INTEGER NOT NULL
                    CHECK(size_bytes > 0 AND size_bytes <= 10485760),
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
                state TEXT NOT NULL CHECK(state IN ('pending', 'active', 'revoked')),
                activated_at INTEGER,
                revoked_at INTEGER,
                last_opened_at INTEGER,
                open_count INTEGER NOT NULL DEFAULT 0 CHECK(open_count >= 0),
                CHECK((state = 'pending' AND activated_at IS NULL AND revoked_at IS NULL)
                   OR (state = 'active' AND activated_at IS NOT NULL AND revoked_at IS NULL)
                   OR (state = 'revoked' AND revoked_at IS NOT NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_expiry
                ON artifacts(state, expires_at);
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                event_id TEXT NOT NULL DEFAULT '',
                tool_use_id TEXT,
                tool_name TEXT,
                tool_is_error INTEGER,
                origin TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(origin IN ('user','agent','background_task','platform','system','unknown')),
                origin_detail TEXT NOT NULL DEFAULT '{"senders":["unknown"]}'
            );
            CREATE TABLE IF NOT EXISTS dashboard_voice_transcriptions (
                voice_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                session_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                path TEXT NOT NULL,
                content_type TEXT NOT NULL,
                state TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dashboard_voice_state
                ON dashboard_voice_transcriptions(state, created_at);
            CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
            CREATE TABLE IF NOT EXISTS review_receipts (
                receipt_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL DEFAULT 1,
                runtime TEXT NOT NULL,
                reviewer_model TEXT NOT NULL,
                model_source TEXT NOT NULL CHECK(model_source IN ('direct','derived','unknown')),
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
                status TEXT NOT NULL CHECK(status IN (
                    'requested','completed','failed','timed_out','interrupted'
                )),
                return_code INTEGER,
                failure_code TEXT NOT NULL DEFAULT '',
                artifact_exists INTEGER,
                artifact_bytes INTEGER,
                artifact_sha256 TEXT NOT NULL DEFAULT '',
                verdict_present INTEGER,
                verdict_value TEXT NOT NULL DEFAULT '',
                jsonl_response_present INTEGER,
                recovery_source TEXT NOT NULL DEFAULT '',
                author_outcome TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(author_outcome IN ('accepted','disputed','partial','unknown')),
                outcome_source TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(outcome_source IN ('direct','derived','unknown')),
                outcome_evidence_ref TEXT NOT NULL DEFAULT '',
                notification_event_id TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_review_receipts_artifact
                ON review_receipts(artifact_path, round);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_review_receipts_artifact_round
                ON review_receipts(artifact_path, round)
                WHERE round IS NOT NULL;
            CREATE TABLE IF NOT EXISTS initial_deliveries (
                delivery_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                worker_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'unknown',
                origin_detail TEXT NOT NULL DEFAULT '{"senders":["unknown"]}',
                payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                user_log_id INTEGER UNIQUE REFERENCES logs(id),
                provider_ref TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_initial_deliveries_scope_state_created
                ON initial_deliveries(scope, state, created_at);
            CREATE TABLE IF NOT EXISTS message_deliveries (
                accept_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                source_session_id TEXT,
                source_principal TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                source_task_id TEXT NOT NULL,
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                target_task_id TEXT NOT NULL,
                target_generation TEXT NOT NULL,
                message TEXT NOT NULL,
                rendered_message TEXT NOT NULL,
                message_kind TEXT,
                wake INTEGER NOT NULL,
                origin TEXT NOT NULL DEFAULT 'unknown',
                origin_detail TEXT NOT NULL DEFAULT '{"senders":["unknown"]}',
                payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                user_log_id INTEGER UNIQUE REFERENCES logs(id) ON DELETE SET NULL,
                provider_ref TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_message_deliveries_target_seq
                ON message_deliveries(target_session_id, accept_seq);
            CREATE INDEX IF NOT EXISTS idx_message_deliveries_source_seq
                ON message_deliveries(source_session_id, accept_seq);
            CREATE TABLE IF NOT EXISTS tg_file_deliveries (
                accept_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                source_session_id TEXT,
                source_name TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                source_path TEXT NOT NULL,
                original_name TEXT NOT NULL,
                snapshot_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes > 0 AND size_bytes <= 52428800),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                caption TEXT NOT NULL,
                outbound_caption TEXT NOT NULL,
                as_document INTEGER NOT NULL CHECK(as_document IN (0,1)),
                payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
                orch_name TEXT,
                batch_id TEXT,
                batch_index INTEGER,
                batch_group INTEGER,
                batch_kind TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                snapshot_deleted_at TEXT,
                quarantined_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tg_file_delivery_targets (
                event_id TEXT NOT NULL REFERENCES tg_file_deliveries(event_id) ON DELETE CASCADE,
                target_kind TEXT NOT NULL CHECK(target_kind IN ('primary','mirror')),
                chat_id INTEGER NOT NULL,
                thread_id INTEGER,
                state TEXT NOT NULL CHECK(state IN
                    ('QUEUED','SUBMITTING','SENT','FAILED_BEFORE_SUBMIT','UNKNOWN')),
                message_id INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
                error_json TEXT,
                submitted_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(event_id, target_kind)
            );
            CREATE TABLE IF NOT EXISTS tg_file_chat_leases (
                chat_id INTEGER PRIMARY KEY,
                generation INTEGER NOT NULL CHECK(generation > 0),
                owner_token TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tg_file_targets_chat_state
                ON tg_file_delivery_targets(chat_id, state, event_id);
            CREATE INDEX IF NOT EXISTS idx_tg_file_deliveries_source_seq
                ON tg_file_deliveries(source_session_id, accept_seq);
            -- get_last_turn_map() runs on every /api/sessions; without this it scans
            -- every logs row (14 MB of content) to LIKE-match 8% of them: 16 ms → 0.6 ms.
            CREATE INDEX IF NOT EXISTS idx_logs_status ON logs(session_id, ts) WHERE type='status';
            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);

            CREATE TABLE IF NOT EXISTS runtime_handoffs (
                handoff_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                source_runtime TEXT NOT NULL,
                source_model TEXT NOT NULL,
                source_session_id TEXT,
                target_runtime TEXT NOT NULL,
                target_model TEXT NOT NULL,
                snapshot_log_id INTEGER NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                packet_json TEXT NOT NULL,
                packet_sha256 TEXT NOT NULL,
                preferred_mode TEXT NOT NULL,
                confirmed_attempt_no INTEGER,
                failure_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT,
                UNIQUE(session_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS runtime_handoff_attempts (
                handoff_id TEXT NOT NULL REFERENCES runtime_handoffs(handoff_id) ON DELETE CASCADE,
                attempt_no INTEGER NOT NULL CHECK (attempt_no IN (1, 2)),
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                cleanup_locator TEXT NOT NULL,
                target_session_id TEXT,
                candidate_sha256 TEXT NOT NULL,
                preflight_json TEXT,
                ingress_json TEXT,
                capability_json TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                retired_at TEXT,
                PRIMARY KEY (handoff_id, attempt_no)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_handoffs_live_session
                ON runtime_handoffs(session_id)
                WHERE status IN (
                    'prepared', 'target_staged', 'ingress_validated',
                    'capability_validated', 'source_released'
                );
            CREATE INDEX IF NOT EXISTS idx_runtime_handoff_attempts_handoff
                ON runtime_handoff_attempts(handoff_id, attempt_no);

            CREATE TABLE IF NOT EXISTS subagents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL,
                sdk_session_id TEXT DEFAULT '',
                tool_use_id TEXT DEFAULT '',
                description TEXT DEFAULT '',
                task_type TEXT DEFAULT '',
                status TEXT DEFAULT 'running',
                total_tokens INTEGER DEFAULT 0,
                tool_uses INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                last_tool_name TEXT DEFAULT '',
                output_file TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                raw_json TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                UNIQUE(session_id, task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);

            CREATE TABLE IF NOT EXISTS fan_barriers (
                fan_id TEXT PRIMARY KEY,
                parent_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                created_at REAL NOT NULL,
                deadline_at REAL NOT NULL,
                reducer TEXT NOT NULL DEFAULT '',
                summarised INTEGER NOT NULL DEFAULT 0,
                released INTEGER NOT NULL DEFAULT 0,
                complete INTEGER,
                partial_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS fan_members (
                fan_id TEXT NOT NULL REFERENCES fan_barriers(fan_id) ON DELETE CASCADE,
                child TEXT NOT NULL,
                state TEXT,
                report_path TEXT,
                PRIMARY KEY (fan_id, child)
            );
            CREATE INDEX IF NOT EXISTS idx_fan_members_child
                ON fan_members(child, fan_id);

            CREATE TABLE IF NOT EXISTS mailbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL,
                scope TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                origin TEXT NOT NULL
                    CHECK(origin IN ('user','agent','background_task','platform','system','unknown')),
                origin_detail TEXT NOT NULL,
                created_at REAL NOT NULL,
                delivered_at REAL,
                claimed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_mailbox_pending
                ON mailbox(recipient, scope) WHERE delivered_at IS NULL;

            CREATE TABLE IF NOT EXISTS restart_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                body TEXT NOT NULL,
                chat_id INTEGER NOT NULL DEFAULT 0,
                thread_id INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                delivered_at REAL,
                failed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_restart_inbox_pending
                ON restart_inbox(id) WHERE delivered_at IS NULL AND failed_at IS NULL;

            CREATE TABLE IF NOT EXISTS test_lock (
                scope TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                holder_session_id TEXT NOT NULL DEFAULT '',
                reason TEXT DEFAULT '',
                acquired_at TEXT NOT NULL
            );
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS tm_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'TASK',
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                yougile_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(prefix)
            );
            CREATE TABLE IF NOT EXISTS tm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                par_number INTEGER NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
                paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
                status TEXT NOT NULL DEFAULT 'backlog',
                assignee TEXT NOT NULL DEFAULT '',
                yougile_task_id TEXT UNIQUE,
                sync_revision INTEGER NOT NULL DEFAULT 0,
                worker_session_id TEXT,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                paid_at TEXT,
                acceptance_command TEXT NOT NULL DEFAULT '',
                acceptance_oracle_json TEXT NOT NULL DEFAULT '{}',
                CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
            );
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);
            CREATE TABLE IF NOT EXISTS tm_task_reservations (
                task_id INTEGER PRIMARY KEY REFERENCES tm_tasks(id) ON DELETE CASCADE,
                operation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_task_create_requests (
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                request_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                active_owner TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 1,
                state TEXT NOT NULL,
                task_id TEXT,
                par_number INTEGER,
                response_json TEXT NOT NULL DEFAULT '',
                error_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, request_key),
                CHECK (state IN ('PENDING','ACTIVE_COMMITTED','MIRRORS_COMMITTED'))
            );
            CREATE TABLE IF NOT EXISTS tm_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                balance_rub INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL REFERENCES tm_clients(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payment_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
                task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_task ON tm_payment_allocations(task_id);
            CREATE TABLE IF NOT EXISTS tm_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tm_tasks(id),
                direction TEXT NOT NULL DEFAULT 'push',
                action TEXT NOT NULL,
                sync_revision INTEGER,
                payload TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tm_sync_task ON tm_sync_log(task_id);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status);
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_namespace_id TEXT REFERENCES tm_projects(id),
                stage_order_json TEXT NOT NULL DEFAULT '[]',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS portfolio_members (
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL CHECK (role IN ('owner','contributor')),
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                PRIMARY KEY (project_id, session_id, created_at)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_one_owner
                ON portfolio_members(project_id)
                WHERE role='owner' AND revoked_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_active_member
                ON portfolio_members(project_id, session_id)
                WHERE revoked_at IS NULL;

            CREATE TABLE IF NOT EXISTS portfolio_task_links (
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                task_stable_id TEXT NOT NULL,
                task_row_id INTEGER NOT NULL REFERENCES tm_tasks(id) ON DELETE CASCADE,
                task_namespace_id TEXT NOT NULL,
                task_display_number INTEGER NOT NULL,
                linked_by_session_id TEXT NOT NULL REFERENCES sessions(id),
                stage_label TEXT,
                created_at TEXT NOT NULL,
                removed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_active_stable_task
                ON portfolio_task_links(task_stable_id)
                WHERE removed_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_active_legacy_task
                ON portfolio_task_links(task_row_id)
                WHERE removed_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_portfolio_task_links_project
                ON portfolio_task_links(project_id)
                WHERE removed_at IS NULL;

            CREATE TABLE IF NOT EXISTS portfolio_goals (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                objective TEXT NOT NULL CHECK(length(objective) BETWEEN 1 AND 4000),
                status TEXT NOT NULL CHECK(status IN ('active','paused','completed','cancelled')),
                watchdog_enabled INTEGER NOT NULL DEFAULT 0,
                stall_after_seconds INTEGER NOT NULL DEFAULT 1800 CHECK(stall_after_seconds > 0),
                last_progress_at TEXT NOT NULL,
                stall_generation INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 1,
                created_by_session_id TEXT NOT NULL REFERENCES sessions(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_active_goal
                ON portfolio_goals(project_id)
                WHERE status IN ('active','paused');
            CREATE INDEX IF NOT EXISTS idx_portfolio_goals_project
                ON portfolio_goals(project_id, status);

            CREATE TABLE IF NOT EXISTS portfolio_goal_progress (
                id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL UNIQUE,
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                note TEXT NOT NULL,
                stall_generation INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_goal_progress_goal
                ON portfolio_goal_progress(goal_id, created_at);

            CREATE TABLE IF NOT EXISTS portfolio_waits (
                id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL UNIQUE,
                open_key TEXT NOT NULL,
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                opened_by_session_id TEXT NOT NULL REFERENCES sessions(id),
                question TEXT NOT NULL,
                task_stable_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('open','resolved','cancelled')),
                opened_at TEXT NOT NULL,
                resolved_at TEXT,
                response_text TEXT,
                response_delivery_id TEXT,
                response_attempt INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_waits_goal
                ON portfolio_waits(goal_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_open_wait
                ON portfolio_waits(open_key) WHERE status='open';

            CREATE TABLE IF NOT EXISTS portfolio_activity_leases (
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                heartbeat_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                PRIMARY KEY(project_id, goal_id, session_id)
            );

            CREATE TABLE IF NOT EXISTS portfolio_watchdog_outbox (
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                stall_generation INTEGER NOT NULL,
                delivery_id TEXT NOT NULL UNIQUE,
                claim_token TEXT NOT NULL,
                target_owner_session_id TEXT NOT NULL REFERENCES sessions(id),
                state TEXT NOT NULL CHECK(state IN ('pending','delivering','accepted','retryable')),
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                accepted_at TEXT,
                PRIMARY KEY(goal_id, stall_generation)
            );

            CREATE TABLE IF NOT EXISTS portfolio_attention_events (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('legacy','incident','reversal','plan_change')),
                reason TEXT NOT NULL,
                source_session_id TEXT NOT NULL REFERENCES sessions(id),
                project_id TEXT REFERENCES portfolio_projects(id),
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_attention_project
                ON portfolio_attention_events(project_id, created_at);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                five_hour_pct REAL DEFAULT 0,
                seven_day_pct REAL DEFAULT 0,
                five_hour_resets_at TEXT,
                seven_day_resets_at TEXT,
                total_cost_usd REAL DEFAULT 0,
                active_agents INTEGER DEFAULT 0,
                provider_usage TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_snapshots(ts);

            CREATE TABLE IF NOT EXISTS voice_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                session_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                cost_usd REAL NOT NULL,
                model TEXT NOT NULL DEFAULT 'nova-3',
                file_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_errors (
                id INTEGER PRIMARY KEY,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                session_name TEXT,
                scope TEXT,
                tool_name TEXT,
                error_text TEXT,
                runtime TEXT NOT NULL DEFAULT 'unknown',
                tool_use_id TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS merge_operations (
                operation_id TEXT PRIMARY KEY,
                operation_type TEXT NOT NULL DEFAULT 'merge',
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                request_json TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                dedupe_fingerprint TEXT NOT NULL,
                accepted_worker_branch TEXT NOT NULL,
                accepted_worker_head TEXT NOT NULL,
                accepted_base_branch TEXT NOT NULL DEFAULT '',
                accepted_task_id TEXT NOT NULL DEFAULT '',
                accepted_needs_switch INTEGER NOT NULL DEFAULT 0,
                accepted_admission_json TEXT NOT NULL DEFAULT '{}',
                state TEXT NOT NULL,
                commit_point TEXT NOT NULL DEFAULT 'NOT_REACHED',
                result_json TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                terminal_worker_branch TEXT NOT NULL DEFAULT '',
                terminal_worker_head TEXT NOT NULL DEFAULT '',
                terminal_base_branch TEXT NOT NULL DEFAULT '',
                terminal_task_id TEXT NOT NULL DEFAULT '',
                terminal_needs_switch INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                resolved_at TEXT,
                resolution_outcome TEXT NOT NULL DEFAULT '',
                resolution_evidence_hash TEXT NOT NULL DEFAULT '',
                resolution_actor TEXT NOT NULL DEFAULT '',
                finalization_stage TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
                finalization_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_merge_operations_fingerprint
                ON merge_operations(dedupe_fingerprint);
            CREATE INDEX IF NOT EXISTS idx_merge_operations_request
                ON merge_operations(session_id, request_hash, finished_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_merge_operations_active_session
                ON merge_operations(session_id)
                WHERE resolved_at IS NULL
                  AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN');

            CREATE TABLE IF NOT EXISTS openrouter_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                day TEXT NOT NULL,
                status INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_or_attempts_ts ON openrouter_attempts(ts);
            CREATE INDEX IF NOT EXISTS idx_or_attempts_day ON openrouter_attempts(day);

            CREATE TABLE IF NOT EXISTS turn_usage (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                runtime TEXT NOT NULL,
                model TEXT NOT NULL,
                ok INTEGER NOT NULL,
                stop_reason TEXT NOT NULL,
                cost_usd REAL,
                cost_unaccounted INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cache_read_tokens INTEGER NOT NULL,
                cache_create_tokens INTEGER NOT NULL,
                quota_five_hour_pct REAL,
                quota_seven_day_pct REAL,
                quota_primary_pct REAL,
                quota_sampled_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_turn_usage_ts ON turn_usage(ts);
            CREATE INDEX IF NOT EXISTS idx_turn_usage_session ON turn_usage(session_id, ts);

            CREATE TABLE IF NOT EXISTS improvement_rules (
                id INTEGER PRIMARY KEY,
                rule_text TEXT,
                source_signal TEXT,
                proposed_by TEXT,
                proposed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'proposed'
                    CHECK (status IN ('proposed','active','retired')),
                approved_at TEXT,
                retired_at TEXT,
                target_file TEXT
            );
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        _migrate(c)


def kv_get(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def kv_delete(key: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM kv WHERE key=?", (key,))


def _reconstruct_costs(c) -> None:
    import re as _re
    sessions = c.execute("SELECT id FROM sessions").fetchall()
    for s in sessions:
        logs = c.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='status' "
            "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
            (s["id"],),
        ).fetchall()
        prev = 0.0
        real_cost = 0.0
        for l in logs:
            m = _re.search(r'\$(\d+\.?\d*)', l["content"])
            if not m:
                continue
            val = float(m.group(1))
            if val == 0:
                continue
            if val < prev:
                real_cost += prev
            prev = val
        real_cost += prev
        c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
                  (round(real_cost, 4), s["id"]))


def _guard_session_id(c) -> None:
    """Запретить строку-призрак: `sessions.id` не может быть NULL или пустым (#54).

    `id TEXT PRIMARY KEY` в SQLite ПУСКАЕТ NULL — проверено вставкой на копии живой БД:
    две строки с `id=NULL` прошли, а `UPDATE … WHERE id=?` по такой строке меняет ноль
    строк молча. Сессия существует, но ни одно обновление до неё не доходит: статус, счётчик
    ходов и `session_id` навсегда остаются теми, что были при вставке.

    Триггер, а не `NOT NULL`, по двум причинам: колонку в SQLite нельзя ужесточить без
    перестройки таблицы (а на неё завязан `logs … REFERENCES sessions(id) ON DELETE CASCADE`),
    и `NOT NULL` не ловит пустую строку — а она даёт ровно тот же призрак.
    """
    c.executescript("""
        CREATE TRIGGER IF NOT EXISTS sessions_id_required_insert
        BEFORE INSERT ON sessions
        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;

        CREATE TRIGGER IF NOT EXISTS sessions_id_required_update
        BEFORE UPDATE OF id ON sessions
        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
    """)


def _migrate_message_deliveries(c) -> None:
    """Preserve receipt identity across target/log deletion on pre-fix databases."""
    if c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_deliveries'"
    ).fetchone() is None:
        return
    foreign_keys = {
        (row["from"], row["table"], str(row["on_delete"]).upper())
        for row in c.execute("PRAGMA foreign_key_list(message_deliveries)").fetchall()
    }
    if (
        not any(column == "target_session_id" for column, _table, _delete in foreign_keys)
        and ("user_log_id", "logs", "SET NULL") in foreign_keys
    ):
        return

    columns = (
        "accept_seq", "delivery_id", "schema_version", "source_session_id",
        "source_principal", "source_name", "source_scope", "source_task_id",
        "target_session_id", "target_name", "target_scope", "target_task_id",
        "target_generation", "message", "rendered_message", "message_kind", "wake",
        "payload_hash", "state", "user_log_id", "provider_ref", "error_json",
        "created_at", "updated_at",
    )
    column_list = ", ".join(columns)
    savepoint = "migrate_message_deliveries_380"
    c.execute(f"SAVEPOINT {savepoint}")
    try:
        c.execute("ALTER TABLE message_deliveries RENAME TO message_deliveries_pre_380_fix")
        c.execute("""CREATE TABLE message_deliveries (
            accept_seq INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_id TEXT NOT NULL UNIQUE,
            schema_version INTEGER NOT NULL,
            source_session_id TEXT,
            source_principal TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_scope TEXT NOT NULL,
            source_task_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_scope TEXT NOT NULL,
            target_task_id TEXT NOT NULL,
            target_generation TEXT NOT NULL,
            message TEXT NOT NULL,
            rendered_message TEXT NOT NULL,
            message_kind TEXT,
            wake INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            user_log_id INTEGER UNIQUE REFERENCES logs(id) ON DELETE SET NULL,
            provider_ref TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute(
            f"INSERT INTO message_deliveries ({column_list}) "
            f"SELECT {column_list} FROM message_deliveries_pre_380_fix"
        )
        c.execute("DROP TABLE message_deliveries_pre_380_fix")
        c.execute(
            "CREATE INDEX idx_message_deliveries_target_seq "
            "ON message_deliveries(target_session_id, accept_seq)"
        )
        c.execute(
            "CREATE INDEX idx_message_deliveries_source_seq "
            "ON message_deliveries(source_session_id, accept_seq)"
        )
    except BaseException:
        c.execute(f"ROLLBACK TO {savepoint}")
        c.execute(f"RELEASE {savepoint}")
        raise
    else:
        c.execute(f"RELEASE {savepoint}")


def _migrate_tg_file_deliveries(c) -> None:
    """Add nullable v1 metadata to pre-release outbox tables without rewrites."""
    additions = {
        "tg_file_deliveries": {
            "snapshot_deleted_at": "TEXT",
            "quarantined_at": "TEXT",
            "batch_id": "TEXT",
            "batch_index": "INTEGER",
            "batch_group": "INTEGER",
            "batch_kind": "TEXT",
        },
        "tg_file_delivery_targets": {
            "error_json": "TEXT",
            "submitted_at": "TEXT",
            "sent_at": "TEXT",
        },
    }
    required = {
        "tg_file_deliveries": {
            "accept_seq", "event_id", "schema_version", "source_session_id",
            "source_name", "source_scope", "source_path", "original_name",
            "snapshot_path", "size_bytes", "content_sha256", "caption",
            "outbound_caption", "as_document", "payload_hash", "orch_name",
            "batch_id", "batch_index", "batch_group", "batch_kind",
            "created_at", "updated_at",
        },
        "tg_file_delivery_targets": {
            "event_id", "target_kind", "chat_id", "thread_id", "state",
            "message_id", "attempt_count", "lease_generation", "updated_at",
        },
        "tg_file_chat_leases": {
            "chat_id", "generation", "owner_token", "lease_expires_at", "updated_at",
        },
    }
    for table, columns in additions.items():
        if c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is None:
            continue
        existing = {
            row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, declaration in columns.items():
            if column not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        existing = {
            row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = required[table] - existing
        if missing:
            raise RuntimeError(
                f"unsupported pre-release {table} schema; missing {sorted(missing)}"
            )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_tg_file_deliveries_batch "
        "ON tg_file_deliveries(batch_id, batch_group, batch_index)"
    )
    lease_columns = {
        row[1] for row in c.execute("PRAGMA table_info(tg_file_chat_leases)").fetchall()
    }
    missing = required["tg_file_chat_leases"] - lease_columns
    if missing:
        raise RuntimeError(
            "unsupported pre-release tg_file_chat_leases schema; "
            f"missing {sorted(missing)}"
        )


def _migrate_portfolio_roadmap(c) -> None:
    """Add the optional roadmap source/order without synthesizing task links."""
    project_columns = {
        row[1] for row in c.execute("PRAGMA table_info(portfolio_projects)").fetchall()
    }
    if "task_namespace_id" not in project_columns:
        c.execute(
            "ALTER TABLE portfolio_projects ADD COLUMN "
            "task_namespace_id TEXT REFERENCES tm_projects(id)"
        )
    if "stage_order_json" not in project_columns:
        c.execute(
            "ALTER TABLE portfolio_projects ADD COLUMN "
            "stage_order_json TEXT NOT NULL DEFAULT '[]'"
        )

    link_columns = {
        row[1] for row in c.execute("PRAGMA table_info(portfolio_task_links)").fetchall()
    }
    if "stage_label" not in link_columns:
        c.execute("ALTER TABLE portfolio_task_links ADD COLUMN stage_label TEXT")

    wait_columns = {
        row[1] for row in c.execute("PRAGMA table_info(portfolio_waits)").fetchall()
    }
    if "response_text" not in wait_columns:
        c.execute("ALTER TABLE portfolio_waits ADD COLUMN response_text TEXT")
    if "response_delivery_id" not in wait_columns:
        c.execute("ALTER TABLE portfolio_waits ADD COLUMN response_delivery_id TEXT")
    if "response_attempt" not in wait_columns:
        c.execute(
            "ALTER TABLE portfolio_waits ADD COLUMN "
            "response_attempt INTEGER NOT NULL DEFAULT 0"
        )

    # A matching slug is not sufficient evidence. Bind only when the sole active
    # root owner maps to exactly one normalized technical scope and that row has
    # the same immutable id as the portfolio project.
    projects = c.execute(
        """SELECT id FROM portfolio_projects
           WHERE archived_at IS NULL AND task_namespace_id IS NULL
           ORDER BY id"""
    ).fetchall()
    for project in projects:
        owners = c.execute(
            """SELECT s.scope FROM portfolio_members m
               JOIN sessions s ON s.id=m.session_id
               WHERE m.project_id=? AND m.role='owner' AND m.revoked_at IS NULL
                 AND s.status!='archived' AND s.role='orchestrator'
                 AND TRIM(COALESCE(s.parent_id,''))=''""",
            (project["id"],),
        ).fetchall()
        if len(owners) != 1:
            continue
        matches = c.execute(
            """SELECT id FROM tm_projects
               WHERE RTRIM(scope,'/')=RTRIM(?,'/') ORDER BY id""",
            (owners[0]["scope"],),
        ).fetchall()
        if len(matches) != 1 or matches[0]["id"] != project["id"]:
            continue
        duplicate = c.execute(
            """SELECT 1 FROM portfolio_projects
               WHERE id!=? AND archived_at IS NULL AND task_namespace_id=?""",
            (project["id"], project["id"]),
        ).fetchone()
        if duplicate is None:
            c.execute(
                "UPDATE portfolio_projects SET task_namespace_id=? WHERE id=?",
                (project["id"], project["id"]),
            )

    # These objects must be created only after legacy columns exist. Putting the
    # index in the early CREATE TABLE script makes old databases fail before
    # _migrate() can run.
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_primary_task_source
           ON portfolio_projects(task_namespace_id)
           WHERE archived_at IS NULL AND task_namespace_id IS NOT NULL"""
    )
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_wait_response_delivery
           ON portfolio_waits(response_delivery_id)
           WHERE response_delivery_id IS NOT NULL"""
    )
    c.executescript(
        """CREATE TRIGGER IF NOT EXISTS portfolio_wait_response_submitted
           AFTER UPDATE OF state ON message_deliveries
           WHEN OLD.state!='SUBMITTED' AND NEW.state='SUBMITTED'
           BEGIN
             UPDATE portfolio_goals
                SET last_progress_at=NEW.updated_at,
                    stall_generation=stall_generation+1,
                    revision=revision+1,
                    updated_at=NEW.updated_at
              WHERE id=(
                    SELECT goal_id FROM portfolio_waits
                     WHERE response_delivery_id=NEW.delivery_id AND status='open'
              );
             UPDATE portfolio_waits
                SET status='resolved',resolved_at=NEW.updated_at
              WHERE response_delivery_id=NEW.delivery_id AND status='open';
           END;"""
    )


def _migrate(c) -> None:
    # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
    # Never drop columns: old Orchestra versions reading the same DB must still work.
    _guard_session_id(c)
    _migrate_message_deliveries(c)
    _migrate_tg_file_deliveries(c)
    _migrate_portfolio_roadmap(c)
    mb_cols = {row[1] for row in c.execute("PRAGMA table_info(mailbox)").fetchall()}
    if "claimed_at" not in mb_cols:
        c.execute("ALTER TABLE mailbox ADD COLUMN claimed_at REAL")
    mailbox_provenance_added = False
    if "origin" not in mb_cols:
        c.execute(
            "ALTER TABLE mailbox ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown' "
            "CHECK(origin IN ('user','agent','background_task','platform','system','unknown'))"
        )
        mailbox_provenance_added = True
    if "origin_detail" not in mb_cols:
        c.execute(
            "ALTER TABLE mailbox ADD COLUMN origin_detail TEXT NOT NULL "
            "DEFAULT '{\"senders\":[\"unknown\"]}'"
        )
        mailbox_provenance_added = True
    if mailbox_provenance_added:
        from app.events import MessageProvenance

        for mailbox_row in c.execute("SELECT id, sender FROM mailbox").fetchall():
            sender = str(mailbox_row["sender"] or "").strip()
            provenance = MessageProvenance(
                origin="agent" if sender else "unknown",
                senders=(sender or "unknown",),
                subtype="mailbox",
                ref=f"mailbox:{mailbox_row['id']}",
            )
            origin, origin_detail = provenance.to_storage()
            c.execute(
                "UPDATE mailbox SET origin=?, origin_detail=? WHERE id=?",
                (origin, origin_detail, mailbox_row["id"]),
            )
    fan_cols = {row[1] for row in c.execute("PRAGMA table_info(fan_barriers)").fetchall()}
    if "reducer" not in fan_cols:
        c.execute("ALTER TABLE fan_barriers ADD COLUMN reducer TEXT NOT NULL DEFAULT ''")
    if "summarised" not in fan_cols:
        c.execute("ALTER TABLE fan_barriers ADD COLUMN summarised INTEGER NOT NULL DEFAULT 0")
    lock_cols = {row[1] for row in c.execute("PRAGMA table_info(test_lock)").fetchall()}
    if lock_cols and "holder_session_id" not in lock_cols:
        c.execute("ALTER TABLE test_lock ADD COLUMN holder_session_id TEXT NOT NULL DEFAULT ''")
    cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
    # #230: what the NEXT supervisor generation needs to attribute an adopted stream —
    # which turn the incoming bytes belong to, and the bytes already pulled out of the pipe.
    if "active_turn_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN active_turn_id TEXT DEFAULT ''")
    if "leftover" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN leftover TEXT DEFAULT ''")
    if "cli_pid" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cli_pid INTEGER DEFAULT 0")
    if "cli_started_at" not in cols:
        # pid alone is not an identity: pids are reused (#230)
        c.execute("ALTER TABLE sessions ADD COLUMN cli_started_at INTEGER DEFAULT 0")
    if "color" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
    if "context_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
    if "context_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
    if "progress_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_pct INTEGER DEFAULT 0")
    if "progress_status" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_status TEXT DEFAULT ''")
    if "backend_type" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
    if "task_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT ''")
    if "description" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")
    if "cost_usd_cached" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_usd_cached REAL DEFAULT 0.0")
    if "context_cost" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_cost REAL DEFAULT 0.0")
    if "cost_reset_v1" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_reset_v1 INTEGER DEFAULT 0")
        _reconstruct_costs(c)
    proj_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_projects)").fetchall()}
    if proj_cols and "yougile_enabled" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN yougile_enabled INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE tm_projects SET yougile_enabled = 1 WHERE id = 'parsing-hub'")
    if proj_cols and "prefix" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN prefix TEXT NOT NULL DEFAULT 'TASK'")
        c.execute("UPDATE tm_projects SET prefix = 'PAR' WHERE id = 'parsing-hub'")
        c.execute("UPDATE tm_projects SET prefix = 'ORC' WHERE id = 'orchestra'")
    if "total_turns" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_turns INTEGER DEFAULT 0")
    if "total_input_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_input_tokens INTEGER DEFAULT 0")
    if "total_output_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_output_tokens INTEGER DEFAULT 0")
    if "total_cache_read_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_cache_read_tokens INTEGER DEFAULT 0")
    if "total_cache_create_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_cache_create_tokens INTEGER DEFAULT 0")
    if "total_tool_calls" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_tool_calls INTEGER DEFAULT 0")
    if "template_hash" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN template_hash TEXT DEFAULT ''")
    if "mcp_servers_custom" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN mcp_servers_custom TEXT DEFAULT ''")
    bg_ddl = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'"
    ).fetchone()
    if bg_ddl and "type IN ('timer'" in bg_ddl[0]:
        _bg_cols = ("id", "type", "config", "message", "target_session_id", "target_name",
                    "target_scope", "created_by_name", "status", "error", "expires_at",
                    "trigger_at", "created_at", "triggered_at", "last_output")
        _bg_col_list = ", ".join(_bg_cols)
        c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
        c.execute("""
            CREATE TABLE bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            )
        """)
        c.execute(f"INSERT INTO bg_jobs ({_bg_col_list}) SELECT {_bg_col_list} FROM bg_jobs_old")
        c.execute("DROP TABLE bg_jobs_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status)")
    try:
        c.execute("DROP TABLE IF EXISTS tm_par_sequence")
    except Exception as e:
        logger.warning(f"migration: tm_par_sequence drop failed: {e}", exc_info=True)
    for old_name in ("_tm_tasks_old", "tm_tasks_old"):
        old_exists = c.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{old_name}'").fetchone()
        if old_exists:
            c.execute("DROP TABLE IF EXISTS tm_tasks")
            c.execute(f"ALTER TABLE {old_name} RENAME TO tm_tasks")
            break
    try:
        auto_idx = [r[1] for r in c.execute("PRAGMA index_list(tm_tasks)").fetchall()
                    if r[1].startswith("sqlite_autoindex")]
    except Exception:
        auto_idx = []
    needs_recreate = False
    for idx in auto_idx:
        try:
            info = c.execute(f"PRAGMA index_info({idx})").fetchall()
            if [r[2] for r in info] == ["par_number"]:
                needs_recreate = True
                break
        except Exception as e:
            logger.warning(f"migration: index_info({idx}) probe failed: {e}", exc_info=True)
    if needs_recreate:
        c.execute("ALTER TABLE tm_tasks RENAME TO _tm_tasks_old")
        c.execute("""CREATE TABLE tm_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            par_number INTEGER NOT NULL,
            project_id TEXT NOT NULL REFERENCES tm_projects(id),
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
            paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
            status TEXT NOT NULL DEFAULT 'backlog', assignee TEXT NOT NULL DEFAULT '',
            yougile_task_id TEXT UNIQUE, sync_revision INTEGER NOT NULL DEFAULT 0,
            worker_session_id TEXT, git_commits TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            completed_at TEXT, paid_at TEXT,
            acceptance_command TEXT NOT NULL DEFAULT '',
            acceptance_oracle_json TEXT NOT NULL DEFAULT '{}',
            priority INTEGER NOT NULL DEFAULT 2,
            CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
        )""")
        target_columns = (
            "id", "par_number", "project_id", "title", "description",
            "price_rub", "paid_rub", "status", "assignee", "yougile_task_id",
            "sync_revision", "worker_session_id", "git_commits", "created_at",
            "updated_at", "completed_at", "paid_at", "acceptance_command",
            "acceptance_oracle_json", "priority",
        )
        old_columns = {
            row[1] for row in c.execute(
                "PRAGMA table_info(_tm_tasks_old)"
            ).fetchall()
        }
        defaults = {
            "acceptance_command": "''",
            "acceptance_oracle_json": "'{}'",
            "priority": "2",
        }
        missing_required = [
            column for column in target_columns
            if column not in old_columns and column not in defaults
        ]
        if missing_required:
            raise RuntimeError(
                "tm_tasks recreation missing required columns: "
                + ", ".join(missing_required)
            )
        column_list = ", ".join(target_columns)
        select_list = ", ".join(
            column if column in old_columns else defaults[column]
            for column in target_columns
        )
        c.execute(
            f"INSERT INTO tm_tasks ({column_list}) "
            f"SELECT {select_list} FROM _tm_tasks_old"
        )
        c.execute("DROP TABLE _tm_tasks_old")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status)")
    for tbl in ("tm_payment_allocations", "tm_sync_log", "tm_task_create_requests"):
        try:
            schema = c.execute(f"SELECT sql FROM sqlite_master WHERE name='{tbl}' AND type='table'").fetchone()
            if schema and "tm_tasks_old" in schema[0]:
                old_name = f"_{tbl}_fix"
                c.execute(f"ALTER TABLE {tbl} RENAME TO {old_name}")
                create_sql = schema[0].replace('"tm_tasks_old"', 'tm_tasks').replace("tm_tasks_old", "tm_tasks")
                c.execute(create_sql)
                c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
                c.execute(f"DROP TABLE {old_name}")
        except Exception as e:
            logger.warning(f"migration: {tbl} tm_tasks_old reference fix failed: {e}", exc_info=True)
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
    op_cols = {row[1] for row in c.execute("PRAGMA table_info(merge_operations)").fetchall()}
    if op_cols and "finalization_stage" not in op_cols:
        # Старые строки читаются прежним recovery path: у них нет стадии финализации.
        c.execute(
            "ALTER TABLE merge_operations ADD COLUMN finalization_stage TEXT "
            "NOT NULL DEFAULT 'NOT_REQUIRED'"
        )
    if op_cols and "finalization_json" not in op_cols:
        c.execute(
            "ALTER TABLE merge_operations ADD COLUMN finalization_json TEXT "
            "NOT NULL DEFAULT '{}'"
        )
    c.execute("""CREATE TABLE IF NOT EXISTS tm_task_reservations (
        task_id INTEGER PRIMARY KEY REFERENCES tm_tasks(id) ON DELETE CASCADE,
        operation_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tm_task_create_requests (
        project_id TEXT NOT NULL REFERENCES tm_projects(id),
        request_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        active_owner TEXT NOT NULL,
        generation INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL,
        task_id TEXT,
        par_number INTEGER,
        response_json TEXT NOT NULL DEFAULT '',
        error_json TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(project_id, request_key),
        CHECK (state IN ('PENDING','ACTIVE_COMMITTED','MIRRORS_COMMITTED'))
    )""")
    task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
    if task_cols and "acceptance_command" not in task_cols:
        c.execute(
            "ALTER TABLE tm_tasks ADD COLUMN acceptance_command TEXT NOT NULL DEFAULT ''"
        )
        task_cols.add("acceptance_command")
    if task_cols and "acceptance_oracle_json" not in task_cols:
        c.execute(
            "ALTER TABLE tm_tasks ADD COLUMN "
            "acceptance_oracle_json TEXT NOT NULL DEFAULT '{}'"
        )
        task_cols.add("acceptance_oracle_json")
    if task_cols and "priority" not in task_cols:
        # 0=critical, 1=high, 2=medium (default), 3=low — existing tasks land at medium
        c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
    merge_cols = {
        row[1] for row in c.execute(
            "PRAGMA table_info(merge_operations)"
        ).fetchall()
    }
    if merge_cols and "accepted_admission_json" not in merge_cols:
        c.execute(
            "ALTER TABLE merge_operations ADD COLUMN "
            "accepted_admission_json TEXT NOT NULL DEFAULT '{}'"
        )
    client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
    if client_cols and "journal_yougile_id" not in client_cols:
        c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
    if task_cols and not c.execute(
        "SELECT 1 FROM kv WHERE key='money_units_v1'"
    ).fetchone():
        # Однократность держит маркер, а не значения: цена 1..999 — законный ввод
        # (task_create принимает любое price >= 0), и без маркера сторож повторно
        # умножал бы живые деньги на 1000 при каждом старте
        max_price = c.execute("SELECT MAX(price_rub) FROM tm_tasks").fetchone()[0] or 0
        if 0 < max_price < 1000:
            # Schema changed from "thousands" to exact kopeks — multiply all money
            # columns by 1000 to bring old data in line with the new unit.
            # Маркер после ветки одинаков и при срабатывании, и при no-op, поэтому
            # единственный след умножения живых денег — эта строка журнала
            logger.warning("money units v1 migration fired: max_price=%s", max_price)
            c.execute("UPDATE tm_tasks SET price_rub = price_rub * 1000, paid_rub = paid_rub * 1000")
            c.execute("UPDATE tm_payment_allocations SET amount_rub = amount_rub * 1000")
            c.execute("UPDATE tm_payments SET amount_rub = amount_rub * 1000")
            c.execute("UPDATE tm_clients SET balance_rub = balance_rub * 1000")
        c.execute(
            "INSERT INTO kv(key, value) VALUES('money_units_v1', '1') "
            "ON CONFLICT(key) DO NOTHING"
        )
    if "role" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
        c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
    if "parent_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
    if "parent_name" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
    if "pipeline" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
    if "profile" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
    if "owned_dirs" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
    if "tg_topic" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN tg_topic INTEGER DEFAULT 0")
    if "session_id_history" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN session_id_history TEXT DEFAULT '[]'")
    if "effort" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN effort TEXT DEFAULT ''")
    if "runtime_handoff" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN runtime_handoff TEXT DEFAULT ''")
    if "history_import_source" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN history_import_source TEXT")
    if "last_summary" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN last_summary TEXT DEFAULT ''")
    if "base_branch" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN base_branch TEXT DEFAULT ''")
    if "needs_switch" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN needs_switch INTEGER DEFAULT 0")
    if "prompt_overlay" not in cols:
        # NULL distinguishes a legacy assembled prompt from a new, explicitly separated
        # overlay. _load_from_db migrates an empty or current-base legacy prompt safely.
        c.execute("ALTER TABLE sessions ADD COLUMN prompt_overlay TEXT")
    log_cols = {row[1] for row in c.execute("PRAGMA table_info(logs)").fetchall()}
    if log_cols and "event_id" not in log_cols:
        c.execute("ALTER TABLE logs ADD COLUMN event_id TEXT NOT NULL DEFAULT ''")
    if log_cols and "tool_use_id" not in log_cols:
        c.execute("ALTER TABLE logs ADD COLUMN tool_use_id TEXT")
    if log_cols and "tool_name" not in log_cols:
        c.execute("ALTER TABLE logs ADD COLUMN tool_name TEXT")
    if log_cols and "tool_is_error" not in log_cols:
        c.execute("ALTER TABLE logs ADD COLUMN tool_is_error INTEGER")
    if log_cols and "origin" not in log_cols:
        c.execute(
            "ALTER TABLE logs ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown' "
            "CHECK(origin IN ('user','agent','background_task','platform','system','unknown'))"
        )
    if log_cols and "origin_detail" not in log_cols:
        c.execute(
            "ALTER TABLE logs ADD COLUMN origin_detail TEXT NOT NULL "
            "DEFAULT '{\"senders\":[\"unknown\"]}'"
        )
    for table in ("initial_deliveries", "message_deliveries"):
        delivery_cols = {
            row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if delivery_cols and "origin" not in delivery_cols:
            c.execute(
                f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown'"
            )
        if delivery_cols and "origin_detail" not in delivery_cols:
            c.execute(
                f"ALTER TABLE {table} ADD COLUMN origin_detail TEXT NOT NULL "
                "DEFAULT '{\"senders\":[\"unknown\"]}'"
            )
    c.execute(
        """CREATE INDEX IF NOT EXISTS idx_logs_event_id
           ON logs(event_id)
           WHERE event_id <> ''"""
    )
    usage_cols = {row[1] for row in c.execute("PRAGMA table_info(usage_snapshots)").fetchall()}
    if usage_cols and "provider_usage" not in usage_cols:
        c.execute("ALTER TABLE usage_snapshots ADD COLUMN provider_usage TEXT NOT NULL DEFAULT '{}'")
    tool_error_cols = {
        row[1] for row in c.execute("PRAGMA table_info(tool_errors)").fetchall()
    }
    if tool_error_cols and "runtime" not in tool_error_cols:
        c.execute(
            "ALTER TABLE tool_errors ADD COLUMN runtime TEXT NOT NULL DEFAULT 'unknown'"
        )
    if tool_error_cols and "tool_use_id" not in tool_error_cols:
        c.execute(
            "ALTER TABLE tool_errors ADD COLUMN tool_use_id TEXT NOT NULL DEFAULT ''"
        )
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_errors_identity
           ON tool_errors(runtime, tool_use_id)
           WHERE tool_use_id <> ''"""
    )
    turn_usage_cols = {
        row[1] for row in c.execute("PRAGMA table_info(turn_usage)").fetchall()
    }
    if turn_usage_cols and "scope" not in turn_usage_cols:
        c.execute(
            "ALTER TABLE turn_usage ADD COLUMN scope TEXT NOT NULL DEFAULT ''"
        )
    if turn_usage_cols and "task_id" not in turn_usage_cols:
        c.execute(
            "ALTER TABLE turn_usage ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
        )
    if turn_usage_cols and "quota_five_hour_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_five_hour_pct REAL")
    if turn_usage_cols and "quota_seven_day_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_seven_day_pct REAL")
    if turn_usage_cols and "quota_primary_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_primary_pct REAL")
    if turn_usage_cols and "quota_sampled_at" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_sampled_at TEXT")
    if turn_usage_cols and "cost_unaccounted" not in turn_usage_cols:
        c.execute(
            "ALTER TABLE turn_usage ADD COLUMN "
            "cost_unaccounted INTEGER NOT NULL DEFAULT 0"
        )
    turn_usage_info = {
        row[1]: row for row in c.execute("PRAGMA table_info(turn_usage)").fetchall()
    }
    if turn_usage_info and turn_usage_info["cost_usd"][3]:
        c.execute(
            """CREATE TABLE turn_usage_nullable_cost (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                runtime TEXT NOT NULL,
                model TEXT NOT NULL,
                ok INTEGER NOT NULL,
                stop_reason TEXT NOT NULL,
                cost_usd REAL,
                cost_unaccounted INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cache_read_tokens INTEGER NOT NULL,
                cache_create_tokens INTEGER NOT NULL,
                quota_five_hour_pct REAL,
                quota_seven_day_pct REAL,
                quota_primary_pct REAL,
                quota_sampled_at TEXT
            )"""
        )
        c.execute(
            """INSERT INTO turn_usage_nullable_cost
               SELECT id, event_id, ts, session_id, scope, task_id,
                      runtime, model, ok, stop_reason,
                      cost_usd, cost_unaccounted,
                      input_tokens, output_tokens,
                      cache_read_tokens, cache_create_tokens,
                      quota_five_hour_pct, quota_seven_day_pct,
                      quota_primary_pct, quota_sampled_at
               FROM turn_usage"""
        )
        c.execute("DROP TABLE turn_usage")
        c.execute("ALTER TABLE turn_usage_nullable_cost RENAME TO turn_usage")
        c.execute("CREATE INDEX idx_turn_usage_ts ON turn_usage(ts)")
        c.execute(
            "CREATE INDEX idx_turn_usage_session ON turn_usage(session_id, ts)"
        )
    # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
    # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
    collector_started_at = datetime.now(timezone.utc).isoformat()
    c.execute(
        """INSERT OR IGNORE INTO kv(key, value)
           VALUES ('tool_error_collector_started_at', ?)""",
        (collector_started_at,),
    )
    c.execute(
        """INSERT OR IGNORE INTO kv(key, value)
           VALUES ('turn_usage_collector_started_at', ?)""",
        (collector_started_at,),
    )


def save_session(
    s: dict,
    *,
    _connection: sqlite3.Connection | None = None,
) -> None:
    # Пустой id — не «почти валидная» строка, а невидимка: все UPDATE … WHERE id=?
    # по ней меняют ноль строк молча (#54). Падать здесь, а не позже и не в другом месте.
    if not str(s.get("id") or "").strip():
        raise ValueError(
            f"session id is required and must be non-empty "
            f"(name={s.get('name')!r}, scope={s.get('scope')!r})"
        )
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    s.setdefault("task_id", "")
    s.setdefault("description", "")
    s.setdefault("cost_usd_cached", 0.0)
    s.setdefault("context_cost", 0.0)
    s.setdefault("total_turns", 0)
    s.setdefault("total_input_tokens", 0)
    s.setdefault("total_output_tokens", 0)
    s.setdefault("total_cache_read_tokens", 0)
    s.setdefault("total_cache_create_tokens", 0)
    s.setdefault("total_tool_calls", 0)
    s.setdefault("template_hash", "")
    s.setdefault("role", "worker")
    s.setdefault("parent_id", "")
    s.setdefault("parent_name", "")
    s.setdefault("pipeline", "")
    s.setdefault("profile", "")
    s.setdefault("mcp_servers_custom", "")
    s.setdefault("owned_dirs", "")
    s.setdefault("tg_topic", 0)
    s.setdefault("session_id_history", "[]")
    s.setdefault("effort", "")
    s.setdefault("runtime_handoff", "")
    s.setdefault("history_import_source", None)
    s.setdefault("last_summary", "")
    s.setdefault("base_branch", "")
    s.setdefault("needs_switch", 0)
    s.setdefault("prompt_overlay", None)
    connection_scope = (
        nullcontext(_connection) if _connection is not None else _conn()
    )
    with connection_scope as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt, prompt_overlay,
                status, session_id, cost_usd, worktree_path, branch, base_branch,
                needs_switch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type, task_id, description,
                cost_usd_cached, context_cost,
                total_turns, total_input_tokens, total_output_tokens,
                total_cache_read_tokens, total_cache_create_tokens, total_tool_calls,
                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
                profile, owned_dirs, tg_topic, session_id_history, effort, runtime_handoff,
                history_import_source, last_summary)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt, :prompt_overlay,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :base_branch,
                :needs_switch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type, :task_id, :description,
                :cost_usd_cached, :context_cost,
                :total_turns, :total_input_tokens, :total_output_tokens,
                :total_cache_read_tokens, :total_cache_create_tokens, :total_tool_calls,
                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
                :profile, :owned_dirs, :tg_topic, :session_id_history, :effort,
                :runtime_handoff, :history_import_source, :last_summary)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                model=excluded.model,
                system_prompt=excluded.system_prompt,
                prompt_overlay=excluded.prompt_overlay,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                cost_usd_cached=excluded.cost_usd_cached,
                context_cost=excluded.context_cost,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                base_branch=excluded.base_branch,
                needs_switch=excluded.needs_switch,
                cwd=excluded.cwd,
                color=excluded.color,
                finished_at=excluded.finished_at,
                context_pct=excluded.context_pct,
                context_tokens=excluded.context_tokens,
                progress_pct=excluded.progress_pct,
                progress_status=excluded.progress_status,
                backend_type=excluded.backend_type,
                task_id=excluded.task_id,
                description=excluded.description,
                total_turns=excluded.total_turns,
                total_input_tokens=excluded.total_input_tokens,
                total_output_tokens=excluded.total_output_tokens,
                total_cache_read_tokens=excluded.total_cache_read_tokens,
                total_cache_create_tokens=excluded.total_cache_create_tokens,
                total_tool_calls=excluded.total_tool_calls,
                template_hash=excluded.template_hash,
                role=excluded.role,
                parent_id=excluded.parent_id,
                parent_name=excluded.parent_name,
                mcp_servers_custom=excluded.mcp_servers_custom,
                pipeline=excluded.pipeline,
                profile=excluded.profile,
                owned_dirs=excluded.owned_dirs,
                tg_topic=excluded.tg_topic,
                session_id_history=excluded.session_id_history,
                effort=excluded.effort,
                runtime_handoff=excluded.runtime_handoff,
                history_import_source=excluded.history_import_source,
                last_summary=excluded.last_summary
        """, s)


def publish_ready_session(s: dict, task_identity: dict | None = None) -> None:
    """Atomically replace one archived identity with a fully prepared session."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM sessions WHERE id=?", (s["id"],)).fetchone():
            raise sqlite3.IntegrityError(f"session id already exists: {s['id']}")
        c.execute(
            "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
            (s["name"], s["scope"]),
        )
        save_session(s, _connection=c)
        if task_identity:
            if c.execute(
                "SELECT 1 FROM tm_task_reservations WHERE task_id = ?",
                (task_identity["id"],),
            ).fetchone():
                raise ValueError(f"task #{task_identity['par_number']} is reserved")
            cur = c.execute(
                "UPDATE tm_tasks SET worker_session_id=?, status='in_progress', "
                "sync_revision=sync_revision+1, updated_at=? "
                "WHERE id=? AND project_id=? AND par_number=? AND sync_revision=? "
                "AND worker_session_id IS NULL",
                (
                    s["id"], datetime.now(timezone.utc).isoformat(),
                    task_identity["id"], task_identity["project_id"],
                    task_identity["par_number"], task_identity["sync_revision"],
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    f"task #{task_identity['par_number']} binding compare-and-swap failed"
                )


def update_session_lifecycle(
    session_id: str,
    *,
    branch: str,
    base_branch: str,
    task_id: str,
    needs_switch: bool,
) -> bool:
    """Persist the Git lifecycle snapshot for loaded and detached sessions alike."""
    with _conn() as c:
        cur = c.execute(
            """UPDATE sessions
               SET branch=?, base_branch=?, task_id=?, needs_switch=?
               WHERE id=? AND status != 'archived'""",
            (branch, base_branch, task_id, int(needs_switch), session_id),
        )
        if cur.rowcount == 0:
            # Ноль строк — это не «нечего менять», это промах по идентичности (#54):
            # строка либо архивная, либо её id не совпадает ни с чем (пустой/призрак).
            logger.warning(
                "UPDATE sessions changed 0 rows: lifecycle for id=%r not persisted",
                session_id,
            )
        return cur.rowcount == 1


def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
    """Move an orchestrator's session to a new scope in one transaction.

    Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
    bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
    session_id (Claude resume token) is left intact — context survives.

    Rejected if another session with the same name already lives in new_scope
    (UNIQUE(name, scope)). A task-associated session also rejects a target task-project
    collision; without a task association, tm_projects/test_lock migration is skipped
    on UNIQUE collision and the explicit session move still succeeds.
    """
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT name, task_id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            return {"error": f"session not found: {session_id}"}
        name = row["name"]
        clash = c.execute(
            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
            (name, new_scope, session_id),
        ).fetchone()
        if clash:
            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}

        source_project = c.execute(
            "SELECT id FROM tm_projects WHERE scope=?", (old_scope,)
        ).fetchone()
        target_project = c.execute(
            "SELECT id FROM tm_projects WHERE scope=?", (new_scope,)
        ).fetchone()
        if (
            row["task_id"]
            and target_project
            and (not source_project or source_project["id"] != target_project["id"])
        ):
            return {
                "error": (
                    f"cannot change scope with task #{row['task_id']}: target scope "
                    f"belongs to task project '{target_project['id']}'"
                )
            }

        cur = c.execute(
            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
            (new_scope, new_cwd, session_id, old_scope),
        )
        if cur.rowcount == 0:
            return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}

        tm_migrated = False
        if not target_project:
            cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
            tm_migrated = cur.rowcount > 0

        c.execute(
            "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
            (new_scope, old_scope),
        )

        lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
        if not lock_target_taken:
            c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))

        return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_by_name(name: str, scope: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
            (name, scope),
        ).fetchone()
        return dict(row) if row else None


# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──

def list_profiles() -> list[dict]:
    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, config_dir FROM profiles ORDER BY name"
        ).fetchall()
        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]


def get_profile(name: str) -> dict | None:
    """Один профиль по имени или ``None``, если не найден."""
    with _conn() as c:
        row = c.execute(
            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None


def upsert_profile(name: str, config_dir: str) -> None:
    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
            (name, config_dir),
        )


def delete_profile(name: str) -> None:
    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
    if name == "personal":
        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
    with _conn() as c:
        c.execute("DELETE FROM profiles WHERE name = ?", (name,))


def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
    with _conn() as c:
        archived_filter = "" if include_archived else " AND status != 'archived'"
        if scope:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_last_turn_map() -> dict[str, str]:
    """{session_id: last 'turn ended' log ts} for cache-timer display. One query."""
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, MAX(ts) AS last_ts FROM logs "
            "WHERE type='status' AND content LIKE 'turn ended%' "
            "GROUP BY session_id"
        ).fetchall()
        return {r["session_id"]: r["last_ts"] for r in rows}


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_archived_session(name: str, scope: str) -> None:
    """Free the UNIQUE(name, scope) slot held by an archived row before re-spawn.

    get_session_by_name filters archived out, so the archived row is invisible to
    callers — this deletes it explicitly (name+scope scoped, never name-only).
    """
    with _conn() as c:
        c.execute(
            "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
            (name, scope),
        )


def archive_session(session_id: str) -> None:
    from app import tm

    with _conn() as c:
        cur = c.execute(
            "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )
        # Одна транзакция с архивацией: между «воркера больше нет» и «его задача
        # пересчитана» не должно существовать окна, в котором задача числится за мёртвым.
        tm.release_session_task_binding(c, session_id)
        if cur.rowcount == 0:
            logger.warning(
                "UPDATE sessions changed 0 rows: session id=%r not archived", session_id,
            )


def add_log(
    session_id: str,
    ts: datetime,
    type: str,
    content: str,
    event_id: str = "",
    *,
    provenance=None,
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    tool_is_error: bool | None = None,
) -> int:
    """ИНВАРИАНТ: строки logs неизменяемы — только этот INSERT и оптовый DELETE по
    возрасту в cleanup_old_logs. Ни одного UPDATE. На этом стоит зеркало журнала в
    браузере (#8): сохранённая строка не может стать неверной, только исчезнуть.
    Появится первый UPDATE logs (например, редактирование сообщения) — зеркало начнёт
    врать МОЛЧА; чинить придётся get_logs_sync и клиентское хранилище вместе.

    Здесь же — ЕДИНСТВЕННЫЙ шов маскирования для БД (#224): строки неизменяемы, значит
    замаскировать значение позже уже нельзя. Второй шов, живой SSE, идёт мимо этой функции
    и закрыт в live_broker.publish.
    """
    from app.events import MessageProvenance
    from app.secret_mask import mask_secrets

    if type == "user_message" and provenance is None:
        raise ValueError("user_message provenance is required")
    if provenance is not None and not isinstance(provenance, MessageProvenance):
        raise TypeError("provenance must be MessageProvenance")
    if provenance is None:
        origin, origin_detail = "unknown", '{"senders":["unknown"]}'
    else:
        origin, origin_detail = provenance.to_storage()
    content = mask_secrets(content)
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO logs (
                   session_id, ts, type, content, event_id,
                   tool_use_id, tool_name, tool_is_error, origin, origin_detail
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, ts.isoformat(), type, content, event_id,
                tool_use_id, tool_name,
                None if tool_is_error is None else int(tool_is_error),
                origin, origin_detail,
            ),
        )
        return cur.lastrowid


def dashboard_voice_enqueue(
    voice_id: str,
    session_id: str,
    session_name: str,
    scope: str,
    path: str,
    content_type: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO dashboard_voice_transcriptions
               (voice_id, session_id, session_name, scope, path, content_type,
                state, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', '', ?, ?)""",
            (voice_id, session_id, session_name, scope, path, content_type, now, now),
        )


def dashboard_voice_pending() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM dashboard_voice_transcriptions
               WHERE state IN ('QUEUED', 'RUNNING') ORDER BY created_at"""
        ).fetchall()
        return [dict(row) for row in rows]


def dashboard_voice_mark_running(voice_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE dashboard_voice_transcriptions SET state='RUNNING', updated_at=? WHERE voice_id=?",
            (now, voice_id),
        )


def dashboard_voice_mark_sent(voice_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE dashboard_voice_transcriptions SET state='SENT', updated_at=? WHERE voice_id=?",
            (now, voice_id),
        )


def dashboard_voice_mark_failed(voice_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """UPDATE dashboard_voice_transcriptions
               SET state='FAILED', error=?, updated_at=? WHERE voice_id=?""",
            (error, now, voice_id),
        )


def get_history_logs(session_id: str, conn=None) -> tuple[int, list[dict]]:
    """Return one immutable log boundary without the dashboard's 5k row cap."""
    c = conn or _conn()
    try:
        max_id = int(c.execute(
            "SELECT COALESCE(MAX(id), 0) FROM logs WHERE session_id = :session_id",
            {"session_id": session_id},
        ).fetchone()[0])
        rows = c.execute(
            """SELECT * FROM logs
               WHERE session_id = :session_id AND id <= :max_id
               ORDER BY id ASC""",
            {"session_id": session_id, "max_id": max_id},
        ).fetchall()
        return max_id, [_decode_log_provenance(dict(row)) for row in rows]
    finally:
        if conn is None:
            c.close()


_HANDOFF_COLUMNS = (
    "handoff_id", "session_id", "idempotency_key", "status",
    "source_runtime", "source_model", "source_session_id",
    "target_runtime", "target_model", "snapshot_log_id",
    "snapshot_sha256", "packet_json", "packet_sha256", "preferred_mode",
    "confirmed_attempt_no", "failure_code", "created_at", "updated_at",
    "confirmed_at",
)


def _insert_runtime_handoff(c: sqlite3.Connection, record: dict) -> dict:
    existing = c.execute(
        "SELECT * FROM runtime_handoffs WHERE session_id=? AND idempotency_key=?",
        (record["session_id"], record["idempotency_key"]),
    ).fetchone()
    if existing:
        return dict(existing)
    columns = [column for column in _HANDOFF_COLUMNS if column in record]
    placeholders = ", ".join("?" for _ in columns)
    c.execute(
        f"INSERT INTO runtime_handoffs ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(record[column] for column in columns),
    )
    return dict(c.execute(
        "SELECT * FROM runtime_handoffs WHERE handoff_id=?",
        (record["handoff_id"],),
    ).fetchone())


def create_runtime_handoff(record: dict) -> dict:
    """Insert an idempotent handoff operation without duplicating its packet."""
    with _conn() as c:
        return _insert_runtime_handoff(c, record)


def prepare_runtime_handoff_snapshot(
    session_id: str,
    idempotency_key: str,
    builder,
) -> tuple[dict | None, object | None]:
    """Freeze logs and create the prepared row under one SQLite write lock.

    ``builder`` receives the current session row, snapshot id, and rows. It returns
    ``(record, side_result)``; ``record=None`` is an ineligible preparation and does
    not create a live operation.
    """
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT * FROM runtime_handoffs WHERE session_id=? AND idempotency_key=?",
            (session_id, idempotency_key),
        ).fetchone()
        if existing:
            return dict(existing), None
        session = c.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session:
            raise RuntimeError("runtime handoff source session not found")
        snapshot_id, rows = get_history_logs(session_id, conn=c)
        record, side_result = builder(dict(session), snapshot_id, rows)
        if record is None:
            return None, side_result
        return _insert_runtime_handoff(c, record), side_result


def get_runtime_handoff(handoff_id: str) -> dict | None:
    with _conn() as c:
        try:
            row = c.execute(
                "SELECT * FROM runtime_handoffs WHERE handoff_id=?", (handoff_id,)
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return None
        return dict(row) if row else None


def list_runtime_handoff_attempts(handoff_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runtime_handoff_attempts WHERE handoff_id=? "
            "ORDER BY attempt_no",
            (handoff_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_latest_runtime_handoffs() -> list[dict]:
    """Return the one unfinished operation that can affect each session owner."""
    with _conn() as c:
        try:
            rows = c.execute(
                """SELECT h.*
                   FROM runtime_handoffs AS h
                   JOIN (
                       SELECT session_id, MAX(rowid) AS newest_rowid
                       FROM runtime_handoffs
                       WHERE status IN (
                           'prepared', 'target_staged', 'ingress_validated',
                           'capability_validated', 'source_released',
                           'recovery_required'
                       )
                       GROUP BY session_id
                   ) AS latest ON latest.newest_rowid = h.rowid
                   ORDER BY h.rowid"""
            ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return []
        return [dict(row) for row in rows]


def get_latest_runtime_handoff_for_session(session_id: str) -> dict | None:
    """Return the unfinished operation that owns a session's recovery gate."""
    with _conn() as c:
        try:
            row = c.execute(
                """SELECT * FROM runtime_handoffs
                   WHERE session_id=? AND status IN (
                       'prepared', 'target_staged', 'ingress_validated',
                       'capability_validated', 'source_released',
                       'recovery_required'
                   )
                   ORDER BY rowid DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return None
        return dict(row) if row else None


def get_confirmed_runtime_handoff_attempt(
    session_id: str,
    target_session_id: str | None,
) -> dict | None:
    """Locate the provider-owned target store for the current confirmed owner."""
    if not target_session_id:
        return None
    with _conn() as c:
        row = c.execute(
            """SELECT a.*, h.target_runtime, h.target_model
               FROM runtime_handoffs AS h
               JOIN runtime_handoff_attempts AS a
                 ON a.handoff_id=h.handoff_id
                AND a.attempt_no=h.confirmed_attempt_no
               WHERE h.session_id=? AND h.status='confirmed'
                 AND a.status='confirmed' AND a.target_session_id=?
               ORDER BY h.rowid DESC LIMIT 1""",
            (session_id, target_session_id),
        ).fetchone()
        return dict(row) if row else None


def retire_runtime_handoff(
    handoff_id: str,
    *,
    status: str,
    failure_code: str,
) -> None:
    """Atomically terminate an operation and retire every allocated target owner."""
    if status not in {"failed", "recovery_required"}:
        raise ValueError("runtime handoff retirement status must be terminal")
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        changed = c.execute(
            """UPDATE runtime_handoffs
               SET status=?, failure_code=?, updated_at=?
               WHERE handoff_id=?""",
            (status, failure_code, now, handoff_id),
        )
        if changed.rowcount != 1:
            raise RuntimeError("runtime handoff not found")
        c.execute(
            """UPDATE runtime_handoff_attempts
               SET status=CASE WHEN status='confirmed' THEN status ELSE 'retired' END,
                   error_code=COALESCE(error_code, ?),
                   retired_at=COALESCE(retired_at, ?), updated_at=?
               WHERE handoff_id=?""",
            (failure_code, now, now, handoff_id),
        )


def allocate_runtime_handoff_attempt(
    handoff_id: str,
    *,
    mode: str,
    candidate_sha256: str,
    cleanup_locator: str,
) -> dict:
    """Persist the cleanup owner before an external target can be created."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) FROM runtime_handoff_attempts "
            "WHERE handoff_id=?",
            (handoff_id,),
        ).fetchone()
        attempt_no = int(row[0]) + 1
        if attempt_no > 2:
            raise RuntimeError("runtime handoff fallback exhausted")
        c.execute(
            """INSERT INTO runtime_handoff_attempts
               (handoff_id, attempt_no, mode, status, cleanup_locator,
                candidate_sha256, created_at, updated_at)
               VALUES (?, ?, ?, 'allocated', ?, ?, ?, ?)""",
            (
                handoff_id, attempt_no, mode, cleanup_locator,
                candidate_sha256, now, now,
            ),
        )
        return dict(c.execute(
            "SELECT * FROM runtime_handoff_attempts "
            "WHERE handoff_id=? AND attempt_no=?",
            (handoff_id, attempt_no),
        ).fetchone())


def update_runtime_handoff_attempt(
    handoff_id: str,
    attempt_no: int,
    *,
    status: str,
    target_session_id: str | None = None,
    preflight_json: str | None = None,
    ingress_json: str | None = None,
    capability_json: str | None = None,
    error_code: str | None = None,
    retired_at: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            """UPDATE runtime_handoff_attempts SET
                   status=?, target_session_id=COALESCE(?, target_session_id),
                   preflight_json=COALESCE(?, preflight_json),
                   ingress_json=COALESCE(?, ingress_json),
                   capability_json=COALESCE(?, capability_json),
                   error_code=COALESCE(?, error_code),
                   retired_at=COALESCE(?, retired_at), updated_at=?
               WHERE handoff_id=? AND attempt_no=?""",
            (
                status, target_session_id, preflight_json, ingress_json,
                capability_json, error_code, retired_at, now,
                handoff_id, attempt_no,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("runtime handoff attempt not found")


def update_runtime_handoff_status(
    handoff_id: str, status: str, *, failure_code: str | None = None
) -> None:
    with _conn() as c:
        cur = c.execute(
            "UPDATE runtime_handoffs SET status=?, failure_code=?, updated_at=? "
            "WHERE handoff_id=?",
            (
                status, failure_code, datetime.now(timezone.utc).isoformat(),
                handoff_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("runtime handoff not found")


def confirm_runtime_handoff(
    *,
    handoff_id: str,
    attempt_no: int,
    expected_source: dict,
    target_session_id: str,
) -> None:
    """Commit target ownership and the operation ledger in one transaction."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        handoff = c.execute(
            "SELECT * FROM runtime_handoffs WHERE handoff_id=?", (handoff_id,)
        ).fetchone()
        if not handoff:
            raise RuntimeError("runtime handoff not found")
        session = c.execute(
            "SELECT model, session_id, backend_type FROM sessions WHERE id=?",
            (handoff["session_id"],),
        ).fetchone()
        actual_source = {
            "runtime": session["backend_type"],
            "model": session["model"],
            "session_id": session["session_id"],
        } if session else None
        if actual_source != expected_source:
            raise RuntimeError("runtime handoff source changed before confirmation")
        if handoff["status"] != "source_released":
            raise RuntimeError("runtime handoff source was not released")
        attempt = c.execute(
            "SELECT * FROM runtime_handoff_attempts "
            "WHERE handoff_id=? AND attempt_no=?",
            (handoff_id, attempt_no),
        ).fetchone()
        if not attempt or attempt["status"] != "capability_validated":
            raise RuntimeError("runtime handoff attempt was not capability validated")
        expected_candidate_sha256 = handoff["packet_sha256"]
        if attempt["mode"] == "fallback_packet":
            from app.runtime_history import build_runtime_packet_fallback

            packet = build_runtime_packet_fallback(json.loads(handoff["packet_json"]))
            expected_candidate_sha256 = packet["integrity"]["canonical_sha256"]
        if attempt["candidate_sha256"] != expected_candidate_sha256:
            raise RuntimeError("runtime handoff attempt hash mismatch")
        if not target_session_id or attempt["target_session_id"] != target_session_id:
            raise RuntimeError("runtime handoff target session mismatch")
        c.execute(
            "UPDATE sessions SET model=?, session_id=?, backend_type=?, "
            "runtime_handoff='', history_import_source=NULL WHERE id=?",
            (
                handoff["target_model"], target_session_id,
                handoff["target_runtime"], handoff["session_id"],
            ),
        )
        c.execute(
            "UPDATE runtime_handoffs SET status='confirmed', "
            "confirmed_attempt_no=?, confirmed_at=?, updated_at=? "
            "WHERE handoff_id=?",
            (attempt_no, now, now, handoff_id),
        )
        c.execute(
            "UPDATE runtime_handoff_attempts SET status='confirmed', updated_at=? "
            "WHERE handoff_id=? AND attempt_no=?",
            (now, handoff_id, attempt_no),
        )


# Sub-agent telemetry columns that upsert may set. Text cols use NULLIF-COALESCE
# (empty from a progress event must NOT wipe a value set by start/end). Numeric
# cols take the incoming value when > 0 (TaskUsage is cumulative → latest wins,
# never summed — session total already counts subagents, see backend_claude).
_SA_TEXT = ("sdk_session_id", "tool_use_id", "description", "task_type",
            "status", "last_tool_name", "output_file", "summary", "raw_json", "ended_at")
_SA_NUM = ("total_tokens", "tool_uses", "duration_ms")


def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
    """Insert or update one sub-agent row (keyed by session_id+task_id).

    start creates the row; progress/end update only the fields they carry.
    Empty text / zero numbers never overwrite an existing value.
    Explicit starts keep the earliest known lifecycle timestamp.
    """
    started_at = fields.get("started_at") or datetime.now(timezone.utc).isoformat()
    cols = ["session_id", "task_id", "started_at"]
    vals = [session_id, task_id, started_at]
    updates = [
        "started_at=CASE WHEN julianday(excluded.started_at) < "
        "julianday(subagents.started_at) THEN excluded.started_at "
        "ELSE subagents.started_at END"
    ]
    for k in _SA_TEXT:
        if k in fields and fields[k] is not None:
            cols.append(k); vals.append(fields[k])
            updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
    for k in _SA_NUM:
        if k in fields and fields[k]:
            cols.append(k); vals.append(int(fields[k]))
            updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
    if fields.get("ended_at") and not fields.get("duration_ms"):
        # local_bash notifications carry no TaskUsage. Preserve SDK duration
        # when present; otherwise derive wall time from the persisted lifecycle.
        updates.append(
            "duration_ms=CASE WHEN subagents.duration_ms > 0 "
            "THEN subagents.duration_ms ELSE MAX(0, CAST("
            "(julianday(excluded.ended_at) - julianday(subagents.started_at)) "
            "* 86400000 AS INTEGER)) END"
        )
    placeholders = ", ".join("?" for _ in cols)
    set_clause = ", ".join(updates) if updates else "task_id=task_id"
    with _conn() as c:
        c.execute(
            f"INSERT INTO subagents ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(session_id, task_id) DO UPDATE SET {set_clause}",
            vals,
        )


def get_subagents(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? ORDER BY started_at ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_subagent(session_id: str, task_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? AND task_id = ?",
            (session_id, task_id),
        ).fetchone()
        return dict(row) if row else None


def _decode_log_provenance(row: dict) -> dict:
    from app.events import MessageProvenance

    if not isinstance(row.get("origin"), str) or not row["origin"]:
        raise ValueError("stored log provenance origin is missing")
    if "origin_detail" not in row:
        raise ValueError("stored log provenance detail is missing")
    provenance = MessageProvenance.from_storage(
        row["origin"], row["origin_detail"],
    )
    return {
        **row,
        "origin": provenance.origin,
        "origin_detail": provenance.detail(),
    }


def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
    c = conn or _conn()
    try:
        if after_id > 0:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (session_id, after_id, limit),
            ).fetchall()
            return [_decode_log_provenance(dict(r)) for r in rows]
        else:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [_decode_log_provenance(dict(r)) for r in reversed(rows)]
    finally:
        if conn is None:
            c.close()


def get_log(log_id: int) -> dict | None:
    """Одна строка журнала целиком, без потолка — за ней приходят по кнопке «загрузить
    целиком», когда обрезанного текста не хватило (#74)."""
    with _conn() as c:
        row = c.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
        return _decode_log_provenance(dict(row)) if row else None


def get_logs_before(session_id: str, before_id: int, limit: int = 500, max_bytes: int = 0,
                    cap: int = 0) -> list[dict]:
    """Страница истории НАЗАД от before_id.

    ``max_bytes > 0`` — потолок на суммарный content ответа (#72). Считать порцию строками
    недостаточно: 25 строк в разных чатах дают от 5.2 до 46.6 КБ gzip, а канал юзера рвёт
    крупные ответы. Первая строка отдаётся всегда, даже если одна перебирает бюджет: иначе
    жирная строка даёт пустой ответ, и клиентский добор зациклится, ни разу не сдвинувшись.

    ``cap > 0`` — потолок на ОДНУ строку, тот же механизм, что у зеркала (#74). Без него
    бюджет выше бессилен против одиночного base64-блоба: у seo-cro такая строка едет одна
    на 507 КБ. Обрезанная строка помечается ``trunc`` и в чате получает видимый маркер.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (session_id, before_id, limit),
        ).fetchall()
        out, used = [], 0
        for r in rows:
            # Сперва потолок, потом бюджет: бюджет обязан считать то, что реально поедет,
            # иначе жирная строка съедает его целиком, будучи обрезанной до килобайта.
            decoded = _decode_log_provenance(dict(r))
            d = _cap_content(decoded, cap) if cap else decoded
            size = len((d.get("content") or "").encode())
            if max_bytes and out and used + size > max_bytes:
                break
            out.append(d)
            used += size
        return list(reversed(out))


_SYNC_COLS = (
    "id, session_id, ts, type, content, event_id, "
    "tool_use_id, tool_name, tool_is_error, origin, origin_detail"
)


def _project_image_generation_result(row: dict, cap: int) -> dict | None:
    """Return the useful, bounded part of a persisted ImageGeneration result.

    The PNG already lives at ``saved_path``. Shipping its multi-megabyte base64 field in
    dashboard history both blows the row cap and cuts off the path/prompt stored after it.
    """
    if row.get("type") != "tool_result" or row.get("tool_name") != "ImageGeneration":
        return None
    source = row.get("content") or ""
    try:
        data = json.loads(source)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not any(
        key in data for key in ("saved_path", "revised_prompt", "status")
    ):
        return None

    projected = {
        "status": str(data.get("status") or ""),
        "saved_path": str(data.get("saved_path") or ""),
        "revised_prompt": str(data.get("revised_prompt") or ""),
    }
    encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    if cap and len(encoded.encode()) > cap:
        # Keep valid JSON and the path even when an abnormal revised prompt alone exceeds
        # the row cap. The ordinary byte-prefix truncation would make JSON unparsable again.
        prompt = projected["revised_prompt"].encode()
        projected["revised_prompt"] = ""
        base_size = len(json.dumps(
            projected, ensure_ascii=False, separators=(",", ":"),
        ).encode())
        available = max(0, cap - base_size)
        projected["revised_prompt"] = prompt[:available].decode(errors="ignore")
        encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    if cap and len(encoded.encode()) > cap:
        return None

    row["content"] = encoded
    row["projection"] = "image_generation"
    row["source_bytes"] = len(source.encode())
    row.pop("trunc", None)
    return row


def _cap_content(row: dict, cap: int) -> dict:
    """Обрезать content до cap БАЙТ (не символов) и пометить обрезку.

    Байты, а не символы: бюджет клиентского зеркала считается в байтах, а кириллица
    в UTF-8 даёт 2 байта на символ — по символам потолок уехал бы вдвое. Срез может
    разрубить символ пополам, поэтому errors="ignore".
    """
    projected = _project_image_generation_result(row, cap)
    if projected is not None:
        return projected
    raw = (row.get("content") or "").encode()
    if len(raw) <= cap:
        return row
    row["content"] = raw[:cap].decode(errors="ignore")
    row["trunc"] = len(raw)  # исходная длина в байтах — её показывает кнопка «загрузить целиком»
    return row


def get_logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384) -> dict:
    """Журнал всех сессий всех проектов одним ответом — для зеркала в браузере.

    after_id == 0 — холодный старт: последние ``tail`` строк на каждую сессию.
    ``tail == 0`` — только карта сессий и отметка, без единой строки журнала: зеркало
    наполняется тем, что юзер реально открыл (#72). Раньше клиент просил tail=20 на все
    сессии и получал 145 КБ по проводу ради строк, из которых рисовалось ~5%.
    after_id > 0  — инкремент: всё, что появилось после этой отметки.

    ``live_sessions`` — полный список сессий БЕЗ фильтров, по ``{id, name, scope}``.
    Логи висят на sessions(id) с ON DELETE CASCADE (и foreign_keys=ON), поэтому
    удалённая сессия уносит свой журнал, и клиент обязан это повторить. Отсюда же
    требование к вызывающему: пустой список означает сбой, а не «сессий нет» — по нему
    нельзя вычищать зеркало.

    Имя и scope нужны не для красоты: после F5 браузер знает, какого агента показывать,
    но не знает его session_id, а логи ключуются именно по нему. Сохранённая карта
    имя+scope → id даёт показать историю до первого сетевого ответа.
    """
    with _conn() as c:
        max_log_id = c.execute("SELECT COALESCE(MAX(id), 0) FROM logs").fetchone()[0]
        live = [{"id": r["id"], "name": r["name"], "scope": r["scope"]}
                for r in c.execute("SELECT id, name, scope FROM sessions")]
        if after_id > 0:
            rows = c.execute(
                f"SELECT {_SYNC_COLS} FROM logs WHERE id > ? ORDER BY id ASC",
                (after_id,),
            ).fetchall()
        else:
            rows = c.execute(
                f"""WITH ranked AS (
                        SELECT {_SYNC_COLS},
                               ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY id DESC) rn
                        FROM logs
                    )
                    SELECT {_SYNC_COLS} FROM ranked WHERE rn <= ? ORDER BY id ASC""",
                (tail,),
            ).fetchall()
        return {
            "max_log_id": max_log_id,
            "live_sessions": live,
            "logs": [
                _cap_content(_decode_log_provenance(dict(r)), cap) for r in rows
            ],
        }


def get_stats(scope: str | None = None) -> dict:
    with _conn() as c:
        where = "WHERE scope = ?" if scope else ""
        params = (scope,) if scope else ()
        total = c.execute(f"SELECT COUNT(*) FROM sessions {where}", params).fetchone()[0]
        active = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status IN ('running', 'starting')",
            params,
        ).fetchone()[0]
        archived = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status = 'archived'",
            params,
        ).fetchone()[0]
        cost = c.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) FROM sessions {where}", params
        ).fetchone()[0]
        logs_where = (
            f"WHERE session_id IN (SELECT id FROM sessions {where})"
            if where else ""
        )
        total_logs = c.execute(
            f"SELECT COUNT(*) FROM logs {logs_where}", params
        ).fetchone()[0]
        agg = c.execute(
            f"""SELECT COALESCE(SUM(total_turns), 0),
                       COALESCE(SUM(total_input_tokens), 0),
                       COALESCE(SUM(total_output_tokens), 0),
                       COALESCE(SUM(total_tool_calls), 0)
                FROM sessions {where}""",
            params,
        ).fetchone()
        return {
            "total_sessions": total,
            "active": active,
            "archived": archived,
            "total_cost_usd": round(cost, 4),
            "total_logs": total_logs,
            "total_turns": agg[0],
            "total_input_tokens": agg[1],
            "total_output_tokens": agg[2],
            "total_tool_calls": agg[3],
        }


def cleanup_old_logs(days: int = 7) -> int:
    """REMOVED by owner decision — agent history is research data, never delete it.

    Kept as a loud tombstone: this function used to drop `logs` older than 7 days on a
    6-hour timer, which silently destroyed every diary older than a week while `sessions`
    rows survived since May. Any caller is a bug.
    """
    raise RuntimeError(
        "cleanup_old_logs is disabled: agent logs must never be deleted. "
        "If disk pressure is real, export to files first and ask the owner."
    )


# ── Review receipts ──

_REVIEW_RECEIPT_COLUMNS = (
    "receipt_id", "schema_version", "runtime", "reviewer_model", "model_source",
    "session_id", "worker_name", "scope", "task_id", "task_source", "artifact_path",
    "mode", "round", "job_id", "usage_event_id", "requested_at", "completed_at",
    "status", "return_code", "failure_code", "artifact_exists", "artifact_bytes",
    "artifact_sha256", "verdict_present", "verdict_value", "jsonl_response_present",
    "recovery_source", "author_outcome", "outcome_source", "outcome_evidence_ref",
    "notification_event_id",
)
_REVIEW_OUTCOMES = frozenset({"accepted", "disputed", "partial"})
_REVIEW_RECEIPT_SOURCES = frozenset({"direct", "derived", "unknown"})


def review_receipt_create(receipt: dict) -> bool:
    """Insert one immutable review start receipt; duplicate ids are replay-safe."""
    if not isinstance(receipt, dict):
        raise TypeError("review receipt must be a dict")
    missing = [
        key for key in (
            "receipt_id", "runtime", "reviewer_model", "model_source", "session_id",
            "worker_name", "scope", "task_id", "task_source", "artifact_path", "mode",
            "job_id", "usage_event_id", "status",
        ) if key not in receipt
    ]
    if missing:
        raise ValueError("review receipt missing fields: " + ", ".join(missing))
    if receipt["model_source"] not in _REVIEW_RECEIPT_SOURCES:
        raise ValueError("invalid review receipt model_source")
    if receipt.get("outcome_source", "unknown") not in _REVIEW_RECEIPT_SOURCES:
        raise ValueError("invalid review receipt outcome_source")
    values = {key: receipt.get(key) for key in _REVIEW_RECEIPT_COLUMNS}
    values["schema_version"] = int(values["schema_version"] or 1)
    values["round"] = None if values["round"] is None else int(values["round"])
    values["status"] = values["status"] or "requested"
    values["requested_at"] = values["requested_at"] or datetime.now(timezone.utc).isoformat()
    values["failure_code"] = values["failure_code"] or ""
    values["artifact_sha256"] = values["artifact_sha256"] or ""
    values["verdict_value"] = values["verdict_value"] or ""
    values["recovery_source"] = values["recovery_source"] or ""
    values["author_outcome"] = values["author_outcome"] or "unknown"
    values["outcome_source"] = values["outcome_source"] or "unknown"
    values["outcome_evidence_ref"] = values["outcome_evidence_ref"] or ""
    values["notification_event_id"] = values["notification_event_id"] or ""
    placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
    columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
    with _conn() as c:
        cursor = c.execute(
            f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT(receipt_id) DO NOTHING",
            tuple(values[key] for key in _REVIEW_RECEIPT_COLUMNS),
        )
        if cursor.rowcount == 0:
            existing = c.execute(
                "SELECT * FROM review_receipts WHERE receipt_id=?",
                (values["receipt_id"],),
            ).fetchone()
            if existing is None or any(
                existing[key] != values[key] for key in _REVIEW_RECEIPT_COLUMNS
            ):
                raise ValueError("review receipt id conflicts with existing provenance")
        return cursor.rowcount == 1


def review_receipt_get(receipt_id: str) -> dict | None:
    if not receipt_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
    return dict(row) if row else None


def review_receipt_reserve(receipt: dict) -> dict:
    """Allocate the next artifact round and insert its start receipt atomically."""
    if not isinstance(receipt, dict):
        raise TypeError("review receipt must be a dict")
    artifact_path = str(receipt.get("artifact_path") or "")
    if not artifact_path:
        raise ValueError("review receipt artifact_path is required")
    values = dict(receipt)
    values["round"] = None
    values.setdefault("schema_version", 1)
    values.setdefault("requested_at", datetime.now(timezone.utc).isoformat())
    values.setdefault("status", "requested")
    values.setdefault("failure_code", "")
    values.setdefault("artifact_sha256", "")
    values.setdefault("verdict_value", "")
    values.setdefault("recovery_source", "")
    values.setdefault("author_outcome", "unknown")
    values.setdefault("outcome_source", "unknown")
    values.setdefault("outcome_evidence_ref", "")
    values.setdefault("notification_event_id", "")
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT COALESCE(MAX(round), 0) FROM review_receipts WHERE artifact_path=?",
            (artifact_path,),
        ).fetchone()
        values["round"] = int(row[0] or 0) + 1
        placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
        columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
        c.execute(
            f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders})",
            tuple(values.get(key) for key in _REVIEW_RECEIPT_COLUMNS),
        )
        saved = c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?",
            (values["receipt_id"],),
        ).fetchone()
    return dict(saved)


def review_receipt_finish(receipt_id: str, updates: dict) -> bool:
    """Record terminal execution facts without allowing start provenance to drift."""
    allowed = {
        "job_id", "completed_at", "status", "return_code", "failure_code",
        "artifact_exists", "artifact_bytes", "artifact_sha256", "verdict_present",
        "verdict_value", "jsonl_response_present", "recovery_source",
        "notification_event_id",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError("review receipt terminal fields not allowed: " + ", ".join(sorted(unknown)))
    if updates.get("status") not in {None, "requested", "completed", "failed", "timed_out", "interrupted"}:
        raise ValueError("invalid review receipt status")
    if not updates:
        return False
    assignments = ", ".join(f"{key}=?" for key in updates)
    with _conn() as c:
        cursor = c.execute(
            f"UPDATE review_receipts SET {assignments} WHERE receipt_id=?",
            tuple(updates[key] for key in updates) + (receipt_id,),
        )
        return cursor.rowcount == 1


def review_receipt_set_outcome(
    receipt_id: str, outcome: str, outcome_evidence_ref: str = "",
) -> dict:
    """Set an author outcome once; identical replay returns the existing row."""
    if outcome not in _REVIEW_OUTCOMES:
        raise ValueError("outcome must be accepted, disputed, or partial")
    evidence = str(outcome_evidence_ref or "").strip()
    if outcome == "disputed" and not evidence:
        raise ValueError("outcome_evidence_ref is required for disputed outcome")
    with _conn() as c:
        row = c.execute(
            "SELECT author_outcome, outcome_evidence_ref FROM review_receipts WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if not row:
            raise LookupError("review receipt not found")
        current = row["author_outcome"] or "unknown"
        current_ref = row["outcome_evidence_ref"] or ""
        if current != "unknown":
            if current == outcome and current_ref == evidence:
                saved = c.execute(
                    "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,)
                ).fetchone()
                return dict(saved)
            raise ValueError("review receipt outcome is already fixed")
        c.execute(
            "UPDATE review_receipts SET author_outcome=?, outcome_source='direct', "
            "outcome_evidence_ref=? WHERE receipt_id=? AND author_outcome='unknown'",
            (outcome, evidence, receipt_id),
        )
        if c.execute("SELECT changes()").fetchone()[0] == 0:
            current_row = c.execute(
                "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
            current = current_row["author_outcome"] or "unknown"
            current_ref = current_row["outcome_evidence_ref"] or ""
            if current == outcome and current_ref == evidence:
                return dict(current_row)
            raise ValueError("review receipt outcome is already fixed")
        saved = c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
    return dict(saved)


# ── Background Jobs ──

def bg_save_job(job: dict) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)


def bg_replace_job(job: dict, replace_key: str) -> list[str]:
    """Atomically cancel an earlier keyed job and insert its replacement."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT id FROM bg_jobs "
            "WHERE status IN ('active','triggering') "
            "AND json_extract(config, '$.replace_key')=?",
            (replace_key,),
        ).fetchall()
        replaced_ids = [row["id"] for row in rows]
        if replaced_ids:
            placeholders = ",".join("?" for _ in replaced_ids)
            c.execute(
                f"UPDATE bg_jobs SET status='cancelled' "
                f"WHERE id IN ({placeholders})",
                replaced_ids,
            )
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)
        c.execute("COMMIT")
        return replaced_ids


def bg_cron_should_fire(job_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM bg_jobs WHERE id=? AND status='active' AND expires_at >= ?",
            (job_id, now),
        ).fetchone()
        return row is not None


def bg_cron_record_fire(job_id: str) -> None:
    # IMMEDIATE lock: prevents two scheduler ticks from recording the same fire
    # (cron jobs can fire again while the previous trigger is still being processed)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT config, status FROM bg_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "active":
            c.execute("ROLLBACK")
            return
        try:
            cfg = json.loads(row["config"])
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg["last_fired_at"] = now_iso
        cfg["fire_count"] = cfg.get("fire_count", 0) + 1
        c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? WHERE id=? AND status='active'",
            (json.dumps(cfg), f"fired #{cfg['fire_count']} at {now_iso}", job_id),
        )
        c.execute("COMMIT")


def bg_claim_trigger(job_id: str) -> bool:
    # Atomic CAS: only one concurrent checker can move job to 'triggering' —
    # multiple scheduler ticks could race here without this guard
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
            (datetime.now(timezone.utc).isoformat(), job_id),
        )
        return cur.rowcount > 0


def bg_get_job(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM bg_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def bg_finish_trigger(job_id: str, last_output: str = "") -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='triggered', last_output=? WHERE id=?",
            (last_output[-3000:], job_id),
        )


def bg_fail_job(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status IN ('active','triggering')",
            (error[:1000], job_id),
        )


def bg_fail_job_if_active(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status='active'",
            (error[:1000], job_id),
        )


def bg_cancel_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_expire_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='expired' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_update_output(job_id: str, output: str) -> None:
    with _conn() as c:
        c.execute("UPDATE bg_jobs SET last_output=? WHERE id=?", (output[-3000:], job_id))


def bg_update_config(job_id: str, config: dict, output: str = "") -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? "
            "WHERE id=? AND status='triggering'",
            (json.dumps(config), output[-3000:], job_id),
        )
        return cur.rowcount > 0


def bg_get_jobs(scope: str | None = None, session_id: str | None = None,
                active_only: bool = False) -> list[dict]:
    with _conn() as c:
        clauses, params = [], []
        if scope:
            clauses.append("target_scope = ?")
            params.append(scope)
        if session_id:
            clauses.append("target_session_id = ?")
            params.append(session_id)
        if active_only:
            clauses.append("status IN ('active','triggering')")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = c.execute(
            f"SELECT * FROM bg_jobs {where} ORDER BY created_at DESC LIMIT 50", params
        ).fetchall()
        return [dict(r) for r in rows]


def bg_cancel_by_session(session_id: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE target_session_id=? AND status='active'",
            (session_id,),
        )
        return cur.rowcount


def bg_get_active_all() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM bg_jobs WHERE status IN ('active','triggering')"
        ).fetchall()
        return [dict(r) for r in rows]


def bg_expire_overdue() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='active' AND expires_at < ?", (now,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='expired' WHERE id IN ({placeholders})", ids)
        stale = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?",
            ((datetime.now(timezone.utc).replace(second=0, microsecond=0)).isoformat(),),
        ).fetchall()
        return ids + [r["id"] for r in stale]


def bg_reset_stale_triggering() -> list[str]:
    """Зовётся только при старте, где ЛЮБОЙ 'triggering' — сирота: процесс, забравший
    его через bg_claim_trigger, мёртв. Порог по возрасту оставлял джоб, чей триггер
    убит рестартом секунды назад, в 'triggering' навсегда: никто больше этот статус
    не трогает, а слот scope он занимать продолжает.
    """
    with _conn() as c:
        rows = c.execute("SELECT id FROM bg_jobs WHERE status='triggering'").fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})", ids)
        return ids


def bg_reset_wake_triggering() -> list[str]:
    """Wake batches are safe to replay because each target turn is revalidated."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' "
            "AND json_extract(config, '$.action')='wake_subscription_limited'"
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(
                f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})",
                ids,
            )
        return ids


def bg_count_active(scope: str) -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM bg_jobs WHERE target_scope=? AND status IN ('active','triggering')",
            (scope,),
        ).fetchone()[0]


def bg_cleanup_old(max_age_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM bg_jobs WHERE status IN ('triggered','expired','cancelled','failed') AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount


def tool_error_add(
    session_name: str,
    scope: str,
    tool_name: str,
    error_text: str,
    *,
    runtime: str = "unknown",
    tool_use_id: str = "",
) -> bool:
    """Atomically record one bounded tool failure; return false on replay."""
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO tool_errors
               (session_name, scope, tool_name, error_text, runtime, tool_use_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_name,
                scope,
                tool_name or "unknown",
                str(error_text or "")[:4000],
                runtime or "unknown",
                tool_use_id or "",
            ),
        )
        return cursor.rowcount == 1


def turn_usage_add(
    *,
    event_id: str,
    session_id: str,
    scope: str = "",
    task_id: str = "",
    runtime: str,
    model: str,
    ok: bool,
    stop_reason: str,
    cost_usd: float | None,
    cost_unaccounted: bool = False,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_create_tokens: int,
    quota_five_hour_pct: float | None = None,
    quota_seven_day_pct: float | None = None,
    quota_primary_pct: float | None = None,
    quota_sampled_at: str | None = None,
    ts: str | None = None,
) -> bool:
    """Persist one provider-identified terminal turn; return false on replay."""
    if not event_id:
        return False
    quota_pcts = (
        quota_five_hour_pct,
        quota_seven_day_pct,
        quota_primary_pct,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
        for value in quota_pcts
        if value is not None
    ):
        raise ValueError("quota percentages must be finite numbers from 0 to 100")
    if any(value is not None for value in quota_pcts) and not quota_sampled_at:
        raise ValueError("quota_sampled_at is required with quota percentages")
    if all(value is None for value in quota_pcts):
        quota_sampled_at = None
    observed_at = ts or datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO turn_usage
               (event_id, ts, session_id, scope, task_id,
                runtime, model, ok, stop_reason,
                cost_usd, cost_unaccounted, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens,
                quota_five_hour_pct, quota_seven_day_pct,
                quota_primary_pct, quota_sampled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                observed_at,
                session_id,
                scope,
                task_id,
                runtime,
                model,
                int(bool(ok)),
                stop_reason,
                None if cost_unaccounted else max(0.0, float(cost_usd or 0)),
                int(bool(cost_unaccounted)),
                max(0, int(input_tokens or 0)),
                max(0, int(output_tokens or 0)),
                max(0, int(cache_read_tokens or 0)),
                max(0, int(cache_create_tokens or 0)),
                quota_five_hour_pct,
                quota_seven_day_pct,
                quota_primary_pct,
                quota_sampled_at,
            ),
        )
        return cursor.rowcount == 1


def rule_propose(
    rule_text: str,
    source_signal: str,
    proposed_by: str,
    target_file: str = "",
) -> int:
    """Create a proposed improvement rule and return its database id."""
    with _conn() as c:
        cursor = c.execute(
            """INSERT INTO improvement_rules
               (rule_text, source_signal, proposed_by, target_file)
               VALUES (?, ?, ?, ?)""",
            (rule_text, source_signal, proposed_by, target_file),
        )
        return cursor.lastrowid


def rule_approve(rule_id: int) -> None:
    """Mark an improvement rule active and record its approval time."""
    with _conn() as c:
        c.execute(
            """UPDATE improvement_rules
               SET status = 'active', approved_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (rule_id,),
        )


def rule_retire(rule_id: int) -> None:
    """Mark an improvement rule retired and record its retirement time."""
    with _conn() as c:
        c.execute(
            """UPDATE improvement_rules
               SET status = 'retired', retired_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (rule_id,),
        )


def rule_list(status: str | None = None) -> list[dict]:
    """Return all improvement rules, optionally filtered by status."""
    query = "SELECT * FROM improvement_rules"
    params: tuple[str, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY proposed_at DESC, id DESC"
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
        return [dict(row) for row in rows]


# ── Usage Snapshots ──

def voice_cost_add(session_name: str, scope: str, duration_sec: float,
                   cost_usd: float, file_id: str, model: str = "nova-3") -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO voice_costs
               (ts, session_name, scope, duration_sec, cost_usd, model, file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), session_name, scope,
             duration_sec, cost_usd, model, file_id),
        )


def voice_cost_total_usd() -> float:
    with _conn() as c:
        return float(c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM voice_costs"
        ).fetchone()[0])


def usage_save_snapshot(five_hour_pct: float | None, seven_day_pct: float | None,
                        five_hour_resets_at: str, seven_day_resets_at: str,
                        total_cost_usd: float, active_agents: int,
                        providers: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             five_hour_pct, seven_day_pct,
             five_hour_resets_at or "", seven_day_resets_at or "",
             total_cost_usd, active_agents,
             json.dumps(providers or {}, ensure_ascii=False)),
        )


def usage_exchange_rate(hours: int = 72, min_five_hour_pct: float = 30.0) -> dict | None:
    """Сколько п.п. недельного окна съедает 1 п.п. пятичасового — по своей же истории (#162)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, five_hour_pct, seven_day_pct, five_hour_resets_at, seven_day_resets_at"
            " FROM usage_snapshots WHERE ts > ? ORDER BY ts ASC", (cutoff,)
        ).fetchall()
    clean = []
    for row in rows:
        if row["five_hour_pct"] is None or row["seven_day_pct"] is None:
            continue
        if (row["five_hour_pct"] == 0 and row["seven_day_pct"] == 0
                and not (row["five_hour_resets_at"] or "")
                and not (row["seven_day_resets_at"] or "")):
            continue
        clean.append((datetime.fromisoformat(row["ts"]),
                      float(row["five_hour_pct"]), float(row["seven_day_pct"])))
    five = seven = 0.0
    for (t1, a5, a7), (t2, b5, b7) in zip(clean, clean[1:]):
        if (t2 - t1).total_seconds() > 1800:
            continue
        five += max(0.0, b5 - a5)
        seven += max(0.0, b7 - a7)
    if five < min_five_hour_pct or seven <= 0:
        return None
    return {"rate": seven / five, "five_hour_pct_sum": five,
            "seven_day_pct_sum": seven, "window_hours": hours}


def _usage_providers_from_row(row: dict) -> dict:
    providers = json.loads(row.pop("provider_usage", "{}") or "{}")
    if providers:
        return providers
    windows = []
    # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
    # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
    fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct):
        windows.append({
            "id": "five_hour", "label": "5h",
            "utilization": fh_pct,
            "window_minutes": 300,
            "resets_at": row.get("five_hour_resets_at") or None,
        })
    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct):
        windows.append({
            "id": "seven_day", "label": "7d",
            "utilization": sd_pct,
            "window_minutes": 10080,
            "resets_at": row.get("seven_day_resets_at") or None,
        })
    return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}


def usage_history_oldest_ts() -> str:
    """Время самого первого снимка — по нему фронт понимает, есть ли что грузить дальше."""
    with _conn() as c:
        row = c.execute("SELECT ts FROM usage_snapshots ORDER BY id ASC LIMIT 1").fetchone()
        return row["ts"] if row else ""


def usage_history_ts_before(ts: str) -> str:
    """Ближайший снимок старше ts. Окно навигации привязано к данным, а не к календарю."""
    with _conn() as c:
        row = c.execute(
            "SELECT ts FROM usage_snapshots WHERE ts < ? ORDER BY ts DESC LIMIT 1", (ts,)
        ).fetchone()
        return row["ts"] if row else ""


def usage_get_history(hours: int = 24, step_minutes: int = 5, until: str = "") -> list[dict]:
    # until — правая граница окна, исключительно: фронт передаёт время самой старой
    # уже загруженной точки, и следующий кусок обязан к ней примыкать, а не дублировать её.
    end = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)
    cutoff = (end - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM usage_snapshots WHERE ts > ? AND ts < ? ORDER BY ts ASC",
            (cutoff, end.isoformat()),
        ).fetchall()
        raw = []
        for db_row in rows:
            row = dict(db_row)
            row["providers"] = _usage_providers_from_row(row)
            raw.append(row)
    if not raw:
        return []
    step = timedelta(minutes=step_minutes)
    # Дольше двух шагов тянуть последнее значение нельзя: снимки регулярно
    # прерываются на часы (ночь, рестарт), и forward-fill рисовал ровную линию
    # там, где данных не было вовсе. Точку не выдаём — на графике будет разрыв.
    stale_limit = step * 2
    start = datetime.fromisoformat(raw[0]["ts"]).replace(tzinfo=timezone.utc)
    grid: list[dict] = []
    ri = 0
    t = start
    prev = raw[0]
    prev_ts = start
    while t < end:
        # Step-forward interpolation: for each grid point, use the last known
        # snapshot at or before that time — matches "last-value" chart semantics
        while ri < len(raw) - 1:
            next_ts = datetime.fromisoformat(raw[ri + 1]["ts"]).replace(tzinfo=timezone.utc)
            if next_ts > t:
                break
            ri += 1
            prev = raw[ri]
            prev_ts = next_ts
        if t - prev_ts <= stale_limit:
            grid.append({**prev, "ts": t.isoformat()})
        t += step
    if not grid or grid[-1].get("id") != raw[-1].get("id"):
        grid.append(raw[-1])
    return grid


# ── Test Lock ──

def _same_lock_holder(row, holder: str, holder_session_id: str) -> bool:
    """Тот же держатель?

    По НЕИЗМЕНЯЕМОМУ id, когда он известен обеим сторонам: имя агента меняется
    `rename_worker` и может быть занято другим агентом — тогда сравнение по строке либо
    не даёт снять свой лок, либо даёт снять ЧУЖОЙ. Строка от старого сервера id не имеет,
    и для неё остаётся сравнение по имени — иначе живой лок стал бы неснимаемым в окне
    между мержем и рестартом.
    """
    stored_id = row["holder_session_id"] if "holder_session_id" in row.keys() else ""
    if stored_id and holder_session_id:
        return stored_id == holder_session_id
    return row["holder"] == holder


def acquire_test_lock(scope: str, holder: str, reason: str = "",
                      holder_session_id: str = "") -> tuple[bool, str | None]:
    """Захватить глобальный тест-лок для scope.

    Возвращает (ok, current_holder):
    - (True, None)   — лок свободен, захвачен
    - (True, holder) — лок уже за этим же держателем (идемпотентно), reason обновлён
    - (False, name)  — занят другим, name = текущий держатель
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        if row is not None:
            if _same_lock_holder(row, holder, holder_session_id):
                # Имя держателя могло смениться с момента захвата — показываем текущее.
                c.execute(
                    "UPDATE test_lock SET holder = ?, holder_session_id = ?, reason = ?, "
                    "acquired_at = ? WHERE scope = ?",
                    (holder, holder_session_id or row["holder_session_id"], reason, now, scope),
                )
                return True, holder
            return False, row["holder"]
        c.execute(
            "INSERT INTO test_lock (scope, holder, holder_session_id, reason, acquired_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope, holder, holder_session_id, reason, now),
        )
        return True, None


def release_test_lock(scope: str, holder: str, holder_session_id: str = "") -> bool:
    """Освободить лок. True — освобождён (был за этим держателем); False — не держатель."""
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        if row is None or not _same_lock_holder(row, holder, holder_session_id):
            return False
        cur = c.execute("DELETE FROM test_lock WHERE scope = ?", (scope,))
        return cur.rowcount > 0


def get_test_lock(scope: str) -> dict | None:
    """Текущий держатель лока для scope или None."""
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        return dict(row) if row else None


def find_merge_proof(scope: str, branch: str) -> dict | None:
    """Доказательство, что ветка УЖЕ слита в базу (#61).

    После сквош-мержа git этого доказать не может: предок не сохраняется, а сравнение
    деревьев (`branch_content_status`) даёт «конфликт», как только база правит те же
    строки. Единственный надёжный источник — наша собственная запись об операции.

    Возвращает {"heads": [...], "operation_id": ...} с головами, на которых мерж
    состоялся: принятой при приёме операции и фактически слитой (они расходятся, когда
    воркер дописал коммит во время ожидания хода — BENIGN_ADVANCE из #17).
    """
    scope = (scope or "").rstrip("/")
    with _conn() as c:
        row = c.execute(
            """SELECT operation_id, accepted_worker_head, result_json
                 FROM merge_operations
                WHERE scope = ? AND accepted_worker_branch = ?
                  AND state = 'SUCCEEDED' AND commit_point = 'REACHED'
                ORDER BY rowid DESC LIMIT 1""",
            (scope, branch),
        ).fetchone()
    if not row:
        return None
    heads = {row["accepted_worker_head"]}
    try:
        merged = (json.loads(row["result_json"]).get("git") or {}).get("worker_head")
    except (ValueError, TypeError, AttributeError):
        merged = None
    if merged:
        heads.add(merged)
    return {"operation_id": row["operation_id"], "heads": sorted(h for h in heads if h)}


# Потолок фактов на сессию. Цифра НЕ измерена: недоставки редки по построению, мерить
# было бы не на чем. Переполнение не отбрасывается молча — оно сворачивается в видимую
# строку, поэтому реальный масштаб станет виден на первом же инциденте (#50).
FACTS_PER_SESSION = 20


def enqueue_fact(session_id: str, dedupe_key: str, text: str) -> bool:
    """Поставить в очередь ФАКТ недоставки для сессии. Повтор того же события — не дубль.

    Очередь durable намеренно: недоставка и рестарт — один и тот же сценарий, и очередь
    в памяти (`_pending_messages`, P1 из #35) терялась бы ровно тогда, когда нужна.
    """
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO undelivered_facts (session_id, dedupe_key, text, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id, dedupe_key) DO NOTHING""",
            (session_id, dedupe_key, text, datetime.now(timezone.utc).isoformat()),
        )
        return cur.rowcount == 1


def peek_facts(session_id: str, limit: int = FACTS_PER_SESSION) -> dict:
    """Факты для показа агенту: последние `limit` плюс число свёрнутых старых.

    Ключи возвращаются ВСЕ, включая свёрнутые: их существование агенту сообщено, значит
    гасить надо и их — иначе счётчик «и ещё N» рос бы вечно.
    """
    with _conn() as c:
        rows = c.execute(
            """SELECT dedupe_key, text, created_at FROM undelivered_facts
                WHERE session_id = ? ORDER BY id""",
            (session_id,),
        ).fetchall()
    if not rows:
        return {"facts": [], "collapsed": 0, "keys": []}
    shown = rows[-limit:] if limit > 0 else []
    return {
        "facts": [{"text": r["text"], "created_at": r["created_at"]} for r in shown],
        "collapsed": len(rows) - len(shown),
        "keys": [r["dedupe_key"] for r in rows],
    }


def ack_facts(session_id: str, keys: list[str]) -> int:
    """Погасить факты, которые ДОШЛИ. Зовётся только после возврата из backend.send."""
    if not keys:
        return 0
    with _conn() as c:
        cur = c.execute(
            f"DELETE FROM undelivered_facts WHERE session_id = ? AND dedupe_key IN "
            f"({','.join('?' * len(keys))})",
            (session_id, *keys),
        )
        return cur.rowcount


def save_handover_state(session_id: str, active_turn_id: str, leftover: str,
                        cli_pid: int = 0, cli_started_at: int = 0) -> None:
    """Persist what an adopted turn needs to be picked up by the next generation (#230 T4).

    `leftover` is the bytes already consumed out of the kernel pipe into our userspace buffer:
    everything still IN the pipe survives the restart by itself (measured — research F3), these
    do not, so they travel through the DB or they are lost.
    """
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET active_turn_id = ?, leftover = ?, cli_pid = ?, "
            "cli_started_at = ? WHERE id = ?",
            (active_turn_id or "", leftover or "", int(cli_pid or 0),
             int(cli_started_at or 0), session_id),
        )
