# V-658: переключение на Sonnet 5.5, 29.09.2026

`claude-sonnet-5-5[1m]` заменил Sonnet 5 в каталоге выбора. ModelSpec задаёт runtime `claude`, окно 1,000,000 и API-equivalent тариф $2/$10 за миллион. Учёт кэша в `backend_claude.py` использует 10% тарифа на чтение и 125% на запись, что даёт указанные $0.20/$2.50. Алиасы `sonnet`, `sonnet5.5`, `claude-sonnet-5-5` и старые Sonnet 5/4.x id ведут к новому id; старый Sonnet 5 отсутствует в MODELS.

`SessionManager._load_from_db` разрешает сохранённый id до выбора backend и создания AgentSession, поэтому старые строки БД запускаются на Sonnet 5.5 при восстановлении. Схема и содержимое БД этим кодом не переписываются. Явные legacy specs Sonnet 4.x остаются для прямого чтения исторических записей; runtime восстановления использует канонический id.

В `model-routing.md` правило выбора Sonnet сохранено, модель названа Sonnet 5.5, а результат связан с V-656: две задачи за $3.71 против $9.54 у Sonnet 5, качество выше. В `.orchestra/pipelines/default/pipeline.yaml` после синхронизации с main `703728ce` сохранён выбранный владельцем `claude-sonnet-5-5[1m]: medium`; карты effort для остальных моделей не менялись.

## Заменённые места

Код и конфигурация: `app/models.py`, `app/session.py`, `app/routes/sessions.py`, `app/manager.py`, `app/tg_bridge.py`, `app/static/js/app.js`, `app/static/js/chat.js`, `.orchestra/pipelines/default/prompts/modules/model-routing.md`, `CHANGELOG.md`.

В 42 изменённых тестовых файлах обновлены фикстуры с текущим id модели и добавлены проверки alias/регистрации/восстановления:
- `tests/test_agent_colors_567.py`
- `tests/test_antigravity_runtime.py`
- `tests/test_api.py`
- `tests/test_audit0901_session.py`
- `tests/test_auto_report_undelivered.py`
- `tests/test_backend_claude.py`
- `tests/test_backend_routing.py`
- `tests/test_backend_stream.py`
- `tests/test_bug_report_notify.py`
- `tests/test_compact_gate_438.py`
- `tests/test_db.py`
- `tests/test_fan_report_delivery.py`
- `tests/test_handoff_effect_classification.py`
- `tests/test_initial_delivery_review_regressions.py`
- `tests/test_manager.py`
- `tests/test_mcp_config_isolation.py`
- `tests/test_mcp_stdio.py`
- `tests/test_message_delivery_receipts_380.py`
- `tests/test_models.py`
- `tests/test_native_history_import.py`
- `tests/test_orchestrators_payload.py`
- `tests/test_owned_dirs_migration_473.py`
- `tests/test_p1_union.py`
- `tests/test_p4_cost.py`
- `tests/test_pipeline.py`
- `tests/test_rate_limit_capture_441.py`
- `tests/test_return_to_merged_branch.py`
- `tests/test_runtime_handoff_recovery.py`
- `tests/test_runtime_handoff_v2.py`
- `tests/test_runtime_history.py`
- `tests/test_runtime_registry.py`
- `tests/test_secret_mask.py`
- `tests/test_session.py`
- `tests/test_session_id_guard.py`
- `tests/test_stall_signals_642.py`
- `tests/test_subagents.py`
- `tests/test_task_binding_417.py`
- `tests/test_task_tracker_integration.py`
- `tests/test_tg_bridge.py`
- `tests/test_undelivered.py`
- `tests/test_undelivered_queue.py`
- `tests/test_workspace.py`

## Проверки

Указанный runtime загрузил модуль из `/home/kesha/orchestra/worktrees/home-kesha-orchestra/impl-sonnet55/app/__init__.py`. После возврата трёх базовых файлов, отмеченных TEST_GATE_FAILED, запущены 42 изменённых pytest-файла и эти три файла, а `test_backend_routing.py` временно запускался с четырьмя файлами (всего 45) после синхронизации main:

```sh
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest $(git show --format= --name-only f78d0e2d -- 'tests/*.py') --junitxml=/tmp/V658-modified-final.xml -q
```

Основной пакетный прогон после возврата четырёх файлов, до финальной правки assertions в backend routing: 1716 passed, 37 failed, 6 skipped, 4 deselected. Отдельная прицельная проверка `tests/test_models.py` и `TestAutoResume.test_resume_upgrades_retired_sonnet_model_id`: 6 passed. Проверки alias, отсутствия Sonnet 5 в MODELS, окна/цен/дефолта и восстановления старой строки БД на Sonnet 5.5 прошли.

После пакетного прогона `test_backend_routing.py` приведён к текущему контракту и проверен целиком: **21 passed**. В нём `test_backend_for_model_registered_wins` теперь проверяет новый selectable Sonnet id, а `test_opus5_registry_and_aliases` — `opus` → Opus 5.5. 37-й результат относительно 35 известных main-baseline падений — `tests.test_frontend::test_send_chart_result_renders_image_and_keeps_delivery_receipt[False]`; файл `tests/test_frontend.py` возвращён к main и исключён из diff. В том же промежуточном прогоне был ещё один новый сбой, `test_backend_for_model_registered_wins` в `tests/test_backend_routing.py`; он исправлен, весь этот файл теперь зелёный. Другие проверки Sonnet прошли. Полный список 37 промежуточных сбоев:

- `tests.test_backend_routing::test_opus5_registry_and_aliases`
- `tests.test_backend_routing::test_backend_for_model_registered_wins`
- `tests.test_frontend::test_model_xml_is_displayed_without_execution_verdict`
- `tests.test_frontend::test_dropped_path_lands_at_caret_not_at_end`
- `tests.test_frontend::test_chat_drop_handles_files_tree_paths_and_upload_errors`
- `tests.test_frontend::test_claude_cache_pill_keeps_exact_thresholds`
- `tests.test_frontend::test_photo_batch_renders_as_compact_expandable_gallery`
- `tests.test_frontend::test_send_chart_result_renders_image_and_keeps_delivery_receipt[False]`
- `tests.test_frontend::test_document_upload_card_appears_immediately_and_reports_progress`
- `tests.test_frontend::test_send_files_batch_renders_paths_and_download_actions`
- `tests.test_frontend::test_notify_user_call_is_highlighted_and_navigable_from_the_timeline[normal]`
- `tests.test_frontend::test_restart_button_shows_current_attempt_failure`
- `tests.test_frontend::test_restart_button_shows_journal_loss_before_reboot`
- `tests.test_frontend::test_connection_state_confirms_external_restart_by_process_generation`
- `tests.test_frontend::test_restart_owns_one_status_and_suppresses_component_diagnoses`
- `tests.test_frontend::test_history_failure_is_fail_loud_and_never_streams_archive_row_by_row`
- `tests.test_frontend::test_unmatched_tool_result_is_visible_and_never_attaches_to_another_call[normal]`
- `tests.test_frontend::test_unmatched_tool_result_is_visible_and_never_attaches_to_another_call[compact]`
- `tests.test_frontend::test_task_result_leads_with_action_and_keeps_raw_details[normal]`
- `tests.test_frontend::test_task_result_leads_with_action_and_keeps_raw_details[compact]`
- `tests.test_frontend::test_live_task_tool_rows_show_russian_labels_and_escaped_title[normal]`
- `tests.test_frontend::test_live_task_tool_rows_show_russian_labels_and_escaped_title[compact]`
- `tests.test_frontend::test_task_tool_rows_from_history_keep_raw_details_and_fallback[normal]`
- `tests.test_frontend::test_task_tool_rows_from_history_keep_raw_details_and_fallback[compact]`
- `tests.test_frontend::test_agent_result_summarizes_statuses_and_keeps_raw_details[normal]`
- `tests.test_frontend::test_agent_result_summarizes_statuses_and_keeps_raw_details[compact]`
- `tests.test_frontend::test_task_card_uses_real_long_description_and_shared_expandable_body`
- `tests.test_frontend::test_chat_restores_last_read_boundary_only_when_unread`
- `tests.test_frontend::test_chat_timeline_navigates_events_and_cycles_user_messages`
- `tests.test_frontend::test_chat_timeline_marker_height_tracks_message_height`
- `tests.test_frontend::test_chat_timeline_navigates_final_agent_answers_only`
- `tests.test_frontend::test_chat_open_waits_for_authoritative_snapshot_and_paints_once`
- `tests.test_frontend::test_dashboard_survives_lossy_channel_from_snapshot`
- `tests.test_frontend::test_dashboard_shows_error_class_when_nothing_cached`
- `tests.test_initial_deliveries::test_t1_http_status_lookup_returns_the_same_committed_resource`
- `tests.test_model_text_control_flow::test_round_guard_quote_preserved_and_runtime_hint_ephemeral`
- `tests.test_model_text_control_flow::test_limit_arriving_during_admission_stops_retry_before_submit`
`git diff --check` прошёл. Orchestra не перезапускалась; живая БД не читалась и не изменялась.
