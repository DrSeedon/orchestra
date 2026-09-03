# grok-impl — личная память

- Приёмка веера «N детей → 1 пробуждение» зелёная и при потерянном тексте: `record_terminal`
  вызывали без `report_path`, `summary` убивался `del summary`. Оракул должен идти через
  прод-пути (`send_message` / `fire_auto_report`) и читать файл из манифеста, не звать
  примитив с уже подставленным путём.
- Живая колонка `fan_members.report_path` может существовать и быть NULL у всех строк —
  наличие схемы ≠ запись. Сначала `SELECT COUNT(*) WHERE report_path IS NOT NULL`.
- `send_message` родителю через веер снова может потерять текст, пока этот фикс не в
  живом процессе: DONE дублируй коротко, длинное — в файл.
- Веер терминален только по `message_kind` ∈ {done,failed,timeout,killed} или по концу
  хода. Факт вызова `send_message` — не сигнал. Мутация одного `is_terminal_report`
  выжила: `record_terminal(None)` и так отвергает state — ломать надо гейт в
  `sessions.py` вместе с хардкодом `"done"`.
- Снял `_did_report` внутри открытого веера → гвард ПОСЛЕ веерной ветки обязателен,
  иначе тул+idle даёт второй on_idle. Счётчик пробуждений, не «веер закрылся».
  Отвергнутые варианты 2/3 #276 — в `docs/tasks/276/rejected-variants.md`, не писать
  «жду ответа» заново.
- Приёмку тикета гоняет `merge_operations` до `execute_merge_session`, команду берёт из
  `tm_tasks.acceptance_command`, не из текста DONE и не из `description`. inconclusive ≠ failed.
- Кто пишет команду: ROLE-фильтр в `task_create` (`_acceptance_command_from_caller`).
  HTTP privileged-поля (`acceptance_command`, `waive_diff_budget`) требуют
  `ORCHESTRA_MCP_PROOF` из env MCP, не session-id. Proof не в systemd env;
  переиздаётся в `_make_mcp_config`. /proc, mcp-config.json, config.toml, SQL —
  вне модели. Мутировать весь `caller_may_use_orchestrator_privilege`.
- Мерж без acceptance_command всё равно гоняет подмножество (`app/merge_test_gate.py`),
  не полный сьют: 728s + один test_lock на проект. Mapping `app/foo.py` →
  `tests/test_foo.py` + route snapshot при routes/main. Никогда pytest -x.
  Нет git-диффа → skip (фикстуры #240). Гейт в `_run_operation`, не в
  `merge_worktree_to_main` (#250 живёт там). Мутировать весь `evaluate_test_gate`.
