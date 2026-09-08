-- Runtime schema version 1. Historical conversion belongs to task_migration.

CREATE TABLE artifacts (
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
            );

CREATE TABLE dashboard_voice_transcriptions (
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

CREATE TABLE fan_barriers (
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

CREATE TABLE fan_members (
                fan_id TEXT NOT NULL REFERENCES fan_barriers(fan_id) ON DELETE CASCADE,
                child TEXT NOT NULL,
                state TEXT,
                report_path TEXT,
                PRIMARY KEY (fan_id, child)
            );

CREATE TABLE initial_deliveries (
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

CREATE TABLE kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

CREATE TABLE logs (
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

CREATE TABLE mailbox (
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

CREATE TABLE merge_operations (
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

CREATE TABLE message_deliveries (
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

CREATE TABLE openrouter_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                day TEXT NOT NULL,
                status INTEGER
            );

CREATE TABLE portfolio_activity_leases (
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                heartbeat_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                PRIMARY KEY(project_id, goal_id, session_id)
            );

CREATE TABLE portfolio_attention_events (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('legacy','incident','reversal','plan_change')),
                reason TEXT NOT NULL,
                source_session_id TEXT NOT NULL REFERENCES sessions(id),
                project_id TEXT REFERENCES portfolio_projects(id),
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );

CREATE TABLE portfolio_goal_progress (
                id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL UNIQUE,
                goal_id TEXT NOT NULL REFERENCES portfolio_goals(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                note TEXT NOT NULL,
                stall_generation INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

CREATE TABLE portfolio_goals (
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

CREATE TABLE portfolio_members (
                project_id TEXT NOT NULL REFERENCES portfolio_projects(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL CHECK (role IN ('owner','contributor')),
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                PRIMARY KEY (project_id, session_id, created_at)
            );

CREATE TABLE portfolio_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_namespace_id TEXT REFERENCES tm_projects(id),
                stage_order_json TEXT NOT NULL DEFAULT '[]',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            );

CREATE TABLE portfolio_task_links (
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

CREATE TABLE portfolio_waits (
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

CREATE TABLE portfolio_watchdog_outbox (
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

CREATE TABLE profiles (
                name TEXT PRIMARY KEY,
                config_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE restart_inbox (
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

CREATE TABLE review_receipts (
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
                notification_event_id TEXT NOT NULL DEFAULT '',
                subject_kind TEXT NOT NULL DEFAULT 'unknown',
                target_sha TEXT NOT NULL DEFAULT '',
                worker_head TEXT NOT NULL DEFAULT '',
                requested_by_session_id TEXT NOT NULL DEFAULT '',
                requested_by_worker TEXT NOT NULL DEFAULT '',
                policy_ref TEXT NOT NULL DEFAULT '',
                task_stable_id TEXT NOT NULL DEFAULT '',
                task_snapshot_ref TEXT NOT NULL DEFAULT '',
                prompt_template_start TEXT NOT NULL DEFAULT '',
                prompt_template_end TEXT NOT NULL DEFAULT '',
                terminal_operation_id TEXT NOT NULL DEFAULT ''
            );

CREATE TABLE runtime_handoff_attempts (
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

CREATE TABLE runtime_handoffs (
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

CREATE TABLE sessions (
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
                finished_at TEXT, cli_pid INTEGER DEFAULT 0, cli_started_at INTEGER DEFAULT 0, context_pct INTEGER DEFAULT 0, context_tokens INTEGER DEFAULT 0, progress_pct INTEGER DEFAULT 0, progress_status TEXT DEFAULT '', backend_type TEXT DEFAULT 'claude', task_id TEXT DEFAULT '', description TEXT DEFAULT '', cost_usd_cached REAL DEFAULT 0.0, context_cost REAL DEFAULT 0.0, cost_reset_v1 INTEGER DEFAULT 0, total_turns INTEGER DEFAULT 0, total_input_tokens INTEGER DEFAULT 0, total_output_tokens INTEGER DEFAULT 0, total_cache_read_tokens INTEGER DEFAULT 0, total_cache_create_tokens INTEGER DEFAULT 0, total_tool_calls INTEGER DEFAULT 0, template_hash TEXT DEFAULT '', disabled_tools TEXT DEFAULT '[]', role TEXT DEFAULT 'worker', parent_id TEXT DEFAULT '', parent_name TEXT DEFAULT '', pipeline TEXT DEFAULT '', owned_dirs TEXT DEFAULT '', tg_topic INTEGER DEFAULT 0, session_id_history TEXT DEFAULT '[]', effort TEXT DEFAULT '',
                UNIQUE(name, scope)
            );

CREATE TABLE subagents (
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

CREATE TABLE task_projection_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1), git_head TEXT NOT NULL);

CREATE TABLE test_lock (
                scope TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                holder_session_id TEXT NOT NULL DEFAULT '',
                reason TEXT DEFAULT '',
                acquired_at TEXT NOT NULL
            );

CREATE TABLE tg_file_chat_leases (
                chat_id INTEGER PRIMARY KEY,
                generation INTEGER NOT NULL CHECK(generation > 0),
                owner_token TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

CREATE TABLE tg_file_deliveries (
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

CREATE TABLE tg_file_delivery_targets (
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

CREATE TABLE tm_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'TASK',
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                yougile_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, canonical_id TEXT NOT NULL DEFAULT '',
                UNIQUE(prefix)
            );

CREATE TABLE tm_task_reservations (
                task_id INTEGER PRIMARY KEY REFERENCES tm_tasks(id) ON DELETE CASCADE,
                operation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

CREATE TABLE tm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                par_number INTEGER NOT NULL,
                ref_prefix TEXT NOT NULL DEFAULT '',
                stable_id TEXT NOT NULL DEFAULT '',
                task_revision TEXT NOT NULL DEFAULT '',
                task_commit TEXT NOT NULL DEFAULT '',
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
                status TEXT NOT NULL DEFAULT 'backlog',
                assignee TEXT NOT NULL DEFAULT '',
                sync_revision INTEGER NOT NULL DEFAULT 0,
                worker_session_id TEXT,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                acceptance_command TEXT NOT NULL DEFAULT '',
                acceptance_oracle_json TEXT NOT NULL DEFAULT '{}', priority INTEGER NOT NULL DEFAULT 2,
                CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
            );

CREATE TABLE tool_errors (
                id INTEGER PRIMARY KEY,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                session_name TEXT,
                scope TEXT,
                tool_name TEXT,
                error_text TEXT,
                runtime TEXT NOT NULL DEFAULT 'unknown',
                tool_use_id TEXT NOT NULL DEFAULT ''
            );

CREATE TABLE turn_usage (
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

CREATE TABLE undelivered_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, dedupe_key)
            );

CREATE TABLE usage_snapshots (
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

CREATE TABLE voice_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                session_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                cost_usd REAL NOT NULL,
                model TEXT NOT NULL DEFAULT 'nova-3',
                file_id TEXT NOT NULL
            );

CREATE INDEX idx_artifacts_expiry
                ON artifacts(state, expires_at);

CREATE INDEX idx_bg_jobs_scope ON bg_jobs(target_scope, status);

CREATE INDEX idx_bg_jobs_session ON bg_jobs(target_session_id, status);

CREATE INDEX idx_dashboard_voice_state
                ON dashboard_voice_transcriptions(state, created_at);

CREATE INDEX idx_fan_members_child
                ON fan_members(child, fan_id);

CREATE INDEX idx_initial_deliveries_scope_state_created
                ON initial_deliveries(scope, state, created_at);

CREATE INDEX idx_logs_event_id
           ON logs(event_id)
           WHERE event_id <> '';

CREATE INDEX idx_logs_session ON logs(session_id, id DESC);

CREATE INDEX idx_logs_status ON logs(session_id, ts) WHERE type='status';

CREATE INDEX idx_mailbox_pending
                ON mailbox(recipient, scope) WHERE delivered_at IS NULL;

CREATE UNIQUE INDEX idx_merge_operations_active_session
                ON merge_operations(session_id)
                WHERE resolved_at IS NULL
                  AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN');

CREATE INDEX idx_merge_operations_fingerprint
                ON merge_operations(dedupe_fingerprint);

CREATE INDEX idx_merge_operations_request
                ON merge_operations(session_id, request_hash, finished_at);

CREATE INDEX idx_message_deliveries_source_seq
                ON message_deliveries(source_session_id, accept_seq);

CREATE INDEX idx_message_deliveries_target_seq
                ON message_deliveries(target_session_id, accept_seq);

CREATE INDEX idx_or_attempts_day ON openrouter_attempts(day);

CREATE INDEX idx_or_attempts_ts ON openrouter_attempts(ts);

CREATE INDEX idx_portfolio_attention_project
                ON portfolio_attention_events(project_id, created_at);

CREATE INDEX idx_portfolio_goal_progress_goal
                ON portfolio_goal_progress(goal_id, created_at);

CREATE INDEX idx_portfolio_goals_project
                ON portfolio_goals(project_id, status);

CREATE INDEX idx_portfolio_task_links_project
                ON portfolio_task_links(project_id)
                WHERE removed_at IS NULL;

CREATE INDEX idx_portfolio_waits_goal
                ON portfolio_waits(goal_id, status);

CREATE INDEX idx_restart_inbox_pending
                ON restart_inbox(id) WHERE delivered_at IS NULL AND failed_at IS NULL;

CREATE INDEX idx_review_receipts_artifact
                ON review_receipts(artifact_path, round);



CREATE INDEX idx_runtime_handoff_attempts_handoff
                ON runtime_handoff_attempts(handoff_id, attempt_no);

CREATE UNIQUE INDEX idx_runtime_handoffs_live_session
                ON runtime_handoffs(session_id)
                WHERE status IN (
                    'prepared', 'target_staged', 'ingress_validated',
                    'capability_validated', 'source_released'
                );

CREATE INDEX idx_sessions_scope ON sessions(scope, is_orchestrator, status);

CREATE INDEX idx_subagents_session ON subagents(session_id);

CREATE INDEX idx_tg_file_deliveries_batch ON tg_file_deliveries(batch_id, batch_group, batch_index);

CREATE INDEX idx_tg_file_deliveries_source_seq
                ON tg_file_deliveries(source_session_id, accept_seq);

CREATE INDEX idx_tg_file_targets_chat_state
                ON tg_file_delivery_targets(chat_id, state, event_id);

CREATE INDEX idx_tm_tasks_project ON tm_tasks(project_id, status);

CREATE UNIQUE INDEX idx_tm_tasks_ref ON tm_tasks(project_id, ref_prefix, par_number);

CREATE UNIQUE INDEX idx_tm_tasks_stable_id ON tm_tasks(stable_id) WHERE stable_id<>'';

CREATE INDEX idx_tm_tasks_status ON tm_tasks(status);

CREATE UNIQUE INDEX idx_tool_errors_identity
           ON tool_errors(runtime, tool_use_id)
           WHERE tool_use_id <> '';

CREATE INDEX idx_turn_usage_session ON turn_usage(session_id, ts);

CREATE INDEX idx_turn_usage_ts ON turn_usage(ts);

CREATE INDEX idx_usage_ts ON usage_snapshots(ts);

CREATE UNIQUE INDEX uq_portfolio_active_goal
                ON portfolio_goals(project_id)
                WHERE status IN ('active','paused');

CREATE UNIQUE INDEX uq_portfolio_active_legacy_task
                ON portfolio_task_links(task_row_id)
                WHERE removed_at IS NULL;

CREATE UNIQUE INDEX uq_portfolio_active_member
                ON portfolio_members(project_id, session_id)
                WHERE revoked_at IS NULL;

CREATE UNIQUE INDEX uq_portfolio_active_stable_task
                ON portfolio_task_links(task_stable_id)
                WHERE removed_at IS NULL;

CREATE UNIQUE INDEX uq_portfolio_one_owner
                ON portfolio_members(project_id)
                WHERE role='owner' AND revoked_at IS NULL;

CREATE UNIQUE INDEX uq_portfolio_open_wait
                ON portfolio_waits(open_key) WHERE status='open';

CREATE UNIQUE INDEX uq_portfolio_primary_task_source
           ON portfolio_projects(task_namespace_id)
           WHERE archived_at IS NULL AND task_namespace_id IS NOT NULL;

CREATE UNIQUE INDEX uq_portfolio_wait_response_delivery
           ON portfolio_waits(response_delivery_id)
           WHERE response_delivery_id IS NOT NULL;

CREATE UNIQUE INDEX uq_review_receipts_artifact_round
                ON review_receipts(artifact_path, round)
                WHERE round IS NOT NULL;

CREATE UNIQUE INDEX uq_review_receipts_open_task_run_session ON review_receipts(session_id) WHERE subject_kind='task_run' AND status='requested';

CREATE UNIQUE INDEX uq_review_receipts_open_task_run_task ON review_receipts(scope, task_stable_id) WHERE subject_kind='task_run' AND status='requested' AND task_stable_id<>'';

CREATE TRIGGER portfolio_wait_response_submitted
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
           END;

CREATE TRIGGER sessions_id_required_insert
        BEFORE INSERT ON sessions
        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;

CREATE TRIGGER sessions_id_required_update
        BEFORE UPDATE OF id ON sessions
        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
