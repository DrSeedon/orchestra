# V-882 — «listen task exited without exception (silent death)»

## Причина

В журнале `logs` (`type=error`, «listen task exited unexpectedly while RUNNING») найдено 14 случаев
(в задаче названо 13; журнал содержит ещё один за 2026-09-16). Сырой контекст — `raw-context.txt`.
Для 13 из 14 порядок событий один и тот же: ход N завершается (`turn ended`, любой stop_reason, в том
числе `error` по квоте Codex), `handle_turn_end` видит непустой mailbox и запускает
`_deliver_mailbox` → `send()` → `status=RUNNING` для хода N+1. Слушатель хода N (`_turn_event_loop`) к
этому моменту ещё не завершил `async for`, а `_listen_task` указывает на него, потому что слушатель N+1 создаётся только после
`await provider_send(...)`. Когда старая задача завершается, `_on_task_done` проходит проверку
`task is self._listen_task`, видит `RUNNING` (уже принадлежащий ходу N+1) и объявляет «silent death»:
`_finish_failed_running_turn` ставит IDLE и шлёт auto-report «Turn failed before an explicit report (no output)»,
хотя ход N+1 живой (в логах сразу после — `codex turn=… started`). Тот же ложный вердикт мог дать `finally`
самого `_turn_event_loop`. Квота Codex — лишь частый повод конца хода N с последующим mailbox; её собственная причина
(«квота Codex исчерпана, сброс …») уже записывалась корректно и затиралась ложным «unexpectedly while RUNNING».
Случай 5 (harness, compact ack timeout) — другой путь, без mailbox: слушатель сжатия завершился по таймауту ack; этим исправлением не покрыт.

## Исправление

`app/session.py`: `_turn_event_loop` запоминает поколение хода (`_turn_gen`) при старте и в `finally`
пишет `_ended_listener=(task, gen)`. `_on_task_done` и `finally` не считают смертью конец слушателя, если
`_turn_gen` с тех пор вырос: RUNNING принадлежит следующему ходу. Настоящая смерть (то же поколение) обрабатывается по-прежнему.

## Таблица случаев

| # | Время UTC | Воркер | Runtime (на момент хода) | Что было перед смертью |
|---|---|---|---|---|
| 1 | 2026-09-16 12:28:43 | balatro-assets | codex | `turn FAILED: rate_limit` → `mailbox: 2 — продолжаю ход` → user_message |
| 2 | 2026-09-24 08:38:04 | seo-cro | codex | steer ждёт, mailbox: 4 → user_message |
| 3 | 2026-09-28 15:12:43 | nedorosl-v2 | codex | `turn ended (end_turn)` SILENT_TURN → mailbox: 1 → user_message |
| 4 | 2026-09-30 04:20:47 | collector-llm | codex | `turn FAILED: error` (interrupted) → mailbox: 1 → user_message |
| 5 | 2026-10-01 08:43:21 | openrouter-lab-orchestrator | harness | `compact ack turn did not complete (60s)` (иной путь, без mailbox) |
| 6 | 2026-10-05 11:53:20 | fix-codex | codex | DONE end_turn → mailbox: 1 → user_message |
| 7 | 2026-10-08 11:54:34 | feat-workflow-tool | codex | `квота Codex исчерпана` → turn ended (error) → mailbox: 4 → user_message |
| 8 | 2026-10-08 11:54:51 | disk-audit | codex | `квота Codex исчерпана` → turn ended (error) → mailbox: 2 → user_message |
| 9 | 2026-10-10 09:19:26 | tender-triage | codex | `turn FAILED: error` (interrupted) → mailbox: 1 → user_message |
| 10 | 2026-10-13 12:46:25 | feat-video-sound | codex | `turn FAILED: error` (interrupted) → mailbox: 1 → bg-job message |
| 11 | 2026-10-13 12:49:41 | feat-video-sound | codex | end_turn → mailbox: 1 → bg-job message |
| 12 | 2026-10-14 11:21:57 | tts-research | codex | interrupted → `waiting for bg jobs` → mailbox: 6 → bg-job message |
| 13 | 2026-10-15 08:33:58 | decision-cost | codex | interrupted → mailbox: 2 → user_message |
| 14 | 2026-10-15 09:23:46 | feat-task-cards | codex | `квота Codex исчерпана, сброс 5h 2026-10-15T11:13:10Z` → turn ended (error) → mailbox: 2 → user_message |

Runtime взят из соседних записей журнала (`codex turn=… started`, `backend: codex` в precompact), т.к. `sessions.backend_type` отражает текущее состояние.

## Проверка

- `tests/test_listen_task_done_648.py` (2 новых) и `tests/test_session.py::TestTurn::test_v882_continuation_turn_started_during_listener_exit_is_not_failed`: красные без правки `app/session.py`, зелёные с ней (проверено откатом файла).
- Деплой: Python-правка, нужен рестарт Orchestra (самостоятельно не выполнялся).
