# STATE.md — Orchestra (Живая память проекта)

**Обновлено:** 2026-11-17 (**`hub-gemini-4-hydrogen` 24/7 ОРКЕСТРАТОР ВЫКАЧЕН В БОЙ `:8888` И ПОДТВЕРЖДЁН ЖИВЫМ E2E В `hydrogen-sandbox-orchestrator`**)

## 1. Боевой контур (`orchestra-vps:/home/kesha/orchestra`, `:8888`)
- **Статус деплоя:** `orchestra.service` — `active` (код `178ec13b1` + конфиг скоупа `d4c63cade`), `telegram-bot-api.service` не тронут, `restart_cut_turns` дельта `0`, все 3 локально изменённых файла в `/home/kesha/orchestra` сохранены побайтово, остальные боевые оркестраторы Максима нетронуты.
- **Сессия Максима `hydrogen-sandbox-orchestrator` (`626ea34f-d213-4ebc-81e1-b209468d31cd`, TG `#300743`, `/home/kesha/projects/hydrogen-sandbox`):**
  - Переведена на **`hub-gemini-4-hydrogen` (`effort: high`, `status: idle`)** — работает 24/7 через Ultra-пул хаба без пиковых блокировок consumer `g1-pro`.
  - Скоуп `/home/kesha/projects/hydrogen-sandbox` прописан в `data/hub-projects.json` (`persistent: true`) и `.orchestra/projects.yaml` (`git:vps-hydrogen-sandbox`).

## 2. Полноценный оркестраторский контур для `HubBackend` (`role == "orchestrator"`)
1. **Контракт рядовых воркеров (`role != "orchestrator"`) сохранён 100% без изменений:** доступны только `send_message`, `update_checklist`, `update_progress` + защита в `parse_outbox` и `execute()`.
2. **Оркестраторские команды `.orchestra-outbox.jsonl` (`app/hub_outbox.py`, `app/backend_hub.py`, `app/session.py`):**
   - `spawn_worker` (2-шаговый `POST /api/sessions` + `initial-deliveries` с `use_worktree=True`, `parent_name=who.name`, проверками `resolve_model` / `ensure_project_model_allowed`), `send_to_worker`, `merge_worker` (с авто-подстановкой 40-символьного `expected_head` из worktree воркера и ожиданием `SUCCEEDED`), `close_worker`, `update_checklist`, `update_progress`.
   - Жёсткая изоляция владения: команды действуют строго на прямых дочерних воркеров своего `who.scope` (`parent_name == who.name` / `parent_id == who.session_id`).
   - Живой срез `<orchestra-workers>` (`status`, `model`, `role`, `branch`, 40-символьный `head`) подаётся на 1-м и всех последующих ходах; барьер `_finalizing_turn` гарантирует постановку входящих авто-отчётов/уведомлений в очередь без потери пробуждения следующего хода.
3. **Верификация:**
   - Офлайн: `223 passed` (`test_hub_orchestrator_outbox.py` + `test_hub_workspace.py` + `test_default_pipeline.py`), `87 passed` (`test_backend_hub.py` + `test_hub_completion_directive_v1244.py`), `69 passed` (`test_hub_outbox_validation_v1222.py` + `test_v1028_hub_outbox_report.py` + `test_hub_report_order_v1213.py`), `check_instruction_contract.py` (`PASS`).
   - **Живой E2E на `:8888` (`PASS`, `85.6s`):** Ход 1 (`hub-gemini-4-hydrogen`, `24.15s`) заспавнил `hello-worker` (`hub-gpt-6-luna`, `task-V-1/hello-worker`) → `hello-worker` создал `hello_hydrogen.py` + `test_hello_hydrogen.py`, прогнал `unittest` (`2 ok`), отправил отчёт → Ход 2 (`hub-gemini-4-hydrogen`, `25.33s`) выполнил `merge_worker` (`5531fe0a`, `SUCCEEDED` → `a28af45`) + `close_worker` (`archived`) → Ход 3 (`8.47s`) подтвердил чистое слияние и закрытие воркера.

## 3. Ранее выкаченный Шаг 2 (`Antigravity ACP` на VPS)
- В бою активны auto-approve (`--dangerously-skip-permissions`), `--process-per-session`, `asyncio.Semaphore(3)`, `canonical_profile("personal")`, прокси `127.0.0.1:18080` (`NL`) + `nftables skgid 977 reject` (`0/0`).
