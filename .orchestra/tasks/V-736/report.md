# V-736 — восстановление CI на main

Run `37346416907` на `02b387c6` имел 14 падений по 8 файлам. Исходный лог сохранён в `targeted.log`.

| Падавшая проверка | Причина | Исход |
|---|---|---|
| `test_ruaccent_marks_text_before_it_reaches_vosk_synthesis`, `test_missing_ruaccent_fails_with_install_command`, `test_cache_key_changes_when_accented_text_changes` | TTS/RUAccent unit-тесты требовали личный Vosk runtime, которого нет на runner; отказ происходил до mock-границ subprocess. | Тесты создают в `tmp_path` фиктивные пути к python/model и по-прежнему мокают subprocess. Все три прошли без локального TTS. |
| `test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox` | Проверка исходника искала присваивание `openBtn.href` внутри HTML-ветки, хотя текущий код выставляет ссылку до выбора типа файла. | Проверка переведена на браузерное поведение: iframe использует `/api/files/raw`, sandbox разрешает только scripts, ссылка открытия ведёт в новую вкладку. |
| `test_send_file_single_keeps_existing_rendering` | Ассерт ожидал две кнопки; текущий PDF-путь добавляет Open рядом с Copy и Download. | Проверка теперь требует отсутствие multi-file списка и по одной кнопке Download и Open. |
| `test_new_frontend_remains_compatible_with_old_analytics_payload` | Стенд без i18n выбирает английское форматирование, а тест ждал старую русскую запятую. | Ожидание суммы изменено с `$1,74` на `$1.74`; проверка совместимости старого payload сохранена. |
| `test_claude_adapter_keeps_primary_limit_signal[allowed|allowed_warning|rejected]` | Текущий SDK включает `RateLimitInfo.raw`; адаптер сохраняет поле, а старый assert ожидал закрытый набор метаданных. | Ожидание включает `raw: {}` для входного события. |
| `test_switch_releases_clean_worker_and_requeues_previous_task` | По текущей семантике V-705 предшествующий run закрывается как `task_superseded`, а не `binding_released`. | Ожидание обновлено под подтверждённый контракт. |
| `test_switch_keeps_binding_while_worker_holds_unlanded_work[force-unmerged_commit]` | `force=True` переключал git при незлитом коммите прежней задачи до того, как task-store отказывал в назначении; commit мог потеряться. | `switch_branch` теперь отвечает 409 до git-переключения, если у прежней привязанной задачи есть unlanded work. Тест проверяет 409 и сохранность старой привязки. |
| `test_null_column_yields_no_window` | Resetless-zero fix из V-700 исключал resetless nonzero: `seven_day_pct=69` терялся вместе с нулём. | History fallback включает оба non-NULL значения с reset metadata или без неё; NULL по-прежнему не становится точкой. |
| `test_t380_r7_accept_while_runner_exits_cannot_lose_wake` | Тестовая обёртка `_next_target_delivery` имела старую сигнатуру после добавления keyword-only `connection`. | Обёртка принимает и передаёт соединение дальше. |
| `test_readiness_endpoint_blocks_above_the_line` | Ожидание 55.5% не учитывало текущий восьмичасовой сдвиг недельной линии Claude; на середине окна порог 59.833333%. | Комментарий и порог обновлены по `claude_weekly_shift_hours=8.0`. |

Дополнительно: браузерный тест HTML preview стартовал module-scoped `dashboard_browser` перед async raw-file тестами. Это оставляло Playwright loop активным, после чего async tests падали `Runner.run() cannot be called from a running event loop`. Переставил browser-тест после async-проверок; полный файл после этого проходит.

## Проверки

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_frontend.py -q` — **111 passed, 1 skipped**; лог в `frontend.log`.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_explainer_video.py tests/test_usage_analytics_frontend.py tests/test_model_text_control_flow.py tests/test_switch_after_continue_620.py tests/test_usage_snapshot.py tests/test_message_delivery_receipts_380.py tests/test_usage_readiness.py -q` — **119 passed**.
- Итого по восьми файлам из CI падений: **230 passed, 1 skipped**.
- `git diff --check` — без замечаний. Импортированный app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.
- Полный GitHub Actions прогон после мержа не запускался; его проверит оркестратор. Orchestra не перезапускал.
