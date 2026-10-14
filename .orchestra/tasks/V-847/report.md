# V-847 — параллельный pytest, чистые артефакты и локальные падения

`pyproject.toml` задаёт для pytest `-n 2 --dist=loadscope`, сохраняя выбор `not live_probe`. CI команды наследуют эти опции; CI уже делит main suite на шесть round-robin шардов. В обоих местах использованы два worker-процесса. Полный serial и полный xdist запущены последовательно под `nice -n 15` и эксклюзивным test lock, на одном worktree и одном наборе исходников.

## Замер полного набора

| Режим | Итог | Pytest wall | Полный wall (`/usr/bin/time`) | Max RSS процесса time |
|---|---|---:|---:|---:|
| Serial, `-n 0` | 4 460 passed, 54 skipped, 4 deselected | 741,90 с | 745,90 с (12:25,90) | 2 409 596 KiB |
| xdist, `-n 2 --dist=loadscope` | 4 460 passed, 54 skipped, 4 deselected* | 388,52 с | 389,66 с (6:29,66) | 2 355 240 KiB |

xdist сократил wall на 356,24 с (47,8%); число passed/skipped/deselected совпало. Оба запуска вернули код 0. 8 предупреждений в xdist против 6 в serial относятся к тем же видам предупреждений (fork после создания thread, незавершённая coroutine mock, FastAPI operation id и websockets deprecation); порядок распределения тестов изменил, какой тест mailbox выдал предупреждение. В полном xdist логе нет красных/ошибочных node IDs.

`-n 2` выбран для машины с 8 CPU и cgroup `MemoryMax=16 GiB`; полный xdist run прошёл без OOM. `/usr/bin/time` измеряет RSS родительского процесса, а не сумму процессов xdist, поэтому его 2,36 GiB не является оценкой всей группы worker-процессов.

Промежуточные xdist-ошибки сохранены: [первый run](evidence/full_xdist2.log) обнаружил разные collection node IDs из `time.time()` в parametrization; после исправления [следующий run](evidence/full_xdist2_final.log) обнаружил зависимость `test_stream_reports_the_live_status_after_the_session_loads` от общего broker. Обе причины исправлены и покрыты детерминированными входами/локальным broker; итоговый [serial](evidence/full_serial_final_code.log) и [xdist](evidence/full_xdist2_final_code.log) прогоны после изменений прошли.

Полный serial log: [full_serial_final_code.log](evidence/full_serial_final_code.log). Полный xdist log: [full_xdist2_final_code.log](evidence/full_xdist2_final_code.log). Оба run выполнились после последних изменений исходников.

### Проверка CI-шарда

По фактическому правилу `.github/workflows/ci.yml` собран shard 0 из 6: те же первые 50 файлов `git ls-files 'tests/test_*.py' | sort`, что в workflow. Локальный replay использовал тот же фильтр `not live_probe and not browser` и `--timeout=30`.

| Режим | Collection | Результат | Wall |
|---|---:|---|---:|
| Serial | 979 collected, 1 deselected, 978 selected | 966 passed, 12 skipped | 88,75 с (pytest 86,13 с) |
| xdist 2 / loadscope | 978 items | 966 passed, 12 skipped | 62,52 с (pytest 61,91 с) |

Результат на этом шарде одинаковый, xdist быстрее на 26,23 с (29,6%). Это локальный replay содержимого CI-шарда, не запуск GitHub Actions. В CI xdist включается через проектный pytest `addopts`; browser job также получает `-n 2`.

Доказательства: [список файлов shard 0](evidence/ci_shard0.meta), [serial log/time](evidence/ci_shard0_serial.log), [xdist log/time](evidence/ci_shard0_xdist2.log).

### Merge gate

На реальном `run_pytest()` проверены те же два test-файла, что в V-841 targeted run: `tests/test_session_logs_conditional.py` и `tests/test_mcp_stdio.py`, 141 тест.

| Режим | Verdicts gate parser | Wall | Итог |
|---|---:|---:|---|
| Serial | 141 passed, 0 failed | 19,87 с | `PASSED` |
| xdist 2 / loadscope | 141 passed, 0 failed | 16,37 с | `PASSED` |

Gate ускорился на 3,50 с (17,6%). До исправления parser xdist печатал node ID отдельной строкой, а verdict — в следующей строке `[gw0] ...`; `_partial_progress()` засчитал ноль завершённых тестов. Это не пропускало красный набор, но потеряло диагностику и при timeout сообщило бы только `INCONCLUSIVE`. `app/merge_test_gate.py` теперь распознаёт worker verdict и считает passed/failed node IDs, сохраняя поведение serial parser. Новый тест `test_partial_progress_reads_xdist_worker_verdict_lines` проверяет одновременно зелёный и красный worker verdict, включая параметризированный node ID с пробелами. Повторный реальный gate run распознал 141/141 passed node.

Доказательства: [serial JSON/log](evidence/merge_gate_serial.json), [xdist JSON/log](evidence/merge_gate_xdist2.json).

## Исправления

| Наблюдение | Исправление | Проверка |
|---|---|---|
| Browser-тесты перезаписывали четыре отслеживаемых PNG; Grok test создавал `.orchestra/tasks/356/*.png` | `tests/test_t344_quota_lines_browser.py`, `tests/test_compact_chat_672.py`, `tests/test_workflow_cards.py`, `tests/test_grok_usage_frontend.py` сохраняют диагностические изображения в `tmp_path`; эталонные fixtures читаются | Полные serial и xdist прогоны завершились без изменений этих PNG и без каталога `tasks/356` |
| `test_final_tool_call_is_persisted...` зависел от завершённого глобального broker | В `tests/test_live_tool_activity_831.py` тест получает новый `LiveBroker`, не закрытый другими тестами | Целевой тест прошёл; полные serial и xdist runs зелёные |
| CLI directory encoding расходился с путём `/tmp/v11-opus-wnuo_okv` | `app.manager.enc_cli_dir()` заменяет `_` на `-` вместе с `/` и `.` | 992 реальных `cwd → directory` пары из `~/.claude/projects`: совпадений стало 992/992 вместо 991/992; тест с underscore добавлен |
| `test_t1_clean_supervisor_exit...` превышал двухсекундный `communicate()` limit | Ограничения ожидания процессов в этом test стали 5 с; assertions `clean_exit`, `forced`, phase, pid/start ticks и target return code сохранены | Целевой тест и полный набор прошли |
| Два `test_tg_bridge_instance_guard` видели `tb.bot`, оставленный предыдущими тестами | `bridge_body_tripwire` сбрасывает `tb.bot` через `monkeypatch` перед отказной проверкой | Обе ветви и разрешающая ветвь прошли в полных запусках |
| `test_hidden_orchestrator_list_reuses_tab_status_and_cache` флакал через минутную границу (`54m`/`55m`) | В тестовой странице `Date.now()` заморожен на одном значении во время повторного рендера | Отдельный rerun и два полных serial/xdist run прошли |
| xdist worker-и собирали различные node IDs из `time.time()` в `pytest.mark.parametrize` | `tests/test_turn_usage.py` параметризует возраст кеша (0/301 с) и вычисляет timestamp при исполнении | Финальный `--collect-only`: 4 514/4 518, 4 deselected и serial, и xdist |
| `test_stream_reports_the_live_status_after_the_session_loads` иногда получал закрытый глобальный broker | `tests/test_audit0901_delivery.py` подменяет глобальный broker свежим экземпляром на время теста | Оба теста файла прошли в serial и xdist; полный финальный xdist run прошёл |

Скриншоты не используются как golden-file assertions: это диагностические снимки, поэтому они создаются только в `tmp_path`. Проверка состояния Git после полных запусков подтвердила, что `.orchestra/tasks/V-652/quota-timeline.png`, `V-654/quota-timeline-live-fixture.png`, `V-672/compact-card.png`, `V-776/workflow-v167.png` и `.orchestra/tasks/356/` не изменены и не созданы.

## Обновление TODO

Из `TODO.md` удалены уже закрытые пункты про загрязнение дерева скриншотами, два падения instance guard, CLI-path encoding и пять локальных ошибок из V-844. Полный serial и полный xdist на этом commit одинаково завершились с 4 460 passed / 54 skipped / 4 deselected.

`app/manager.py` и `app/merge_test_gate.py` — Python-код: изменения вступят в действие в живой Orchestra после merge и инициированного владельцем рестарта.

## Ограничения замера

CI-шард воспроизведён на этой машине, а не на GitHub runner. Merge gate измерен на двух связанных модулях (141 узел), не на всех возможных наборах файлов; при этом его parser теперь сохраняет результаты и неполного xdist прогона. RSS в таблице — максимум процесса `/usr/bin/time`, не сумма дочерних workers. Полный xdist test run был один зелёный после исправления всех найденных order-dependent состояний; отдельное повторение всего прогона не выполнялось.
