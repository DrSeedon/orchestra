# #436 — структурная квитанция Codex-review

## Объём и ограничения

- Входной корпус — `docs/tasks/435/report.md`, прочитан целиком. В нём 437 review-файлов, 56 (12.8%) без вердикта, 111 (25%) без авторского исхода, 276 model labels выведены по историческому default.
- Ограничение #435 сохраняется: Sol и Luna звали на разные задачи, поэтому корпус наблюдательный; сравнение Luna/Sol в дизайн и план не переносится.
- Полноту ревью измерить нельзя: неизвестно, какие дефекты ревью пропустило. `blocking` и количество замечаний не являются recall или точностью.
- Фаза только исследовательская. `app/mcp_stdio.py` и `app/db.py` не изменялись, потому что заняты #433.

## Физический путь текущего вызова

1. `app/mcp_stdio.py:3494-3516` принимает `context`, `target`, `output`, `mode`, `resume`, `model`. На `3516` разрешается модель через реестр; runtime проверяется на `codex` на `851-866`. Серверный default — `gpt-5.6-luna` (`828`), поэтому отсутствие аргумента нельзя считать прочитанной моделью.
2. После quota gate на `3533` делается `GET /api/sessions/<WORKER_NAME>`. Из ответа на `3539-3546` берутся immutable session id, `task_id`, worktree/cwd и строится абсолютный `output_abs` — будущий владелец текста.
3. На `3550-3555` строятся временные пути: `/tmp/codex_review_<worker>_<slug>.jsonl`, `.txt`, `.rc` и `<artifact>.round`. На `3557-3560` читается UUID предыдущего review. Сейчас сохраняется только `is_resume`; числовой round в БД не резервируется.
4. На `3570-3646` выбирается бинарник, строится `codex`/`codex resume` команда и передаётся выбранная `review_model`. `mode=review` смотрит diff, `mode=exec` получает target и требует в prompt секцию `## Verdict`.
5. На `3666-3685` в команду добавляются путь `app/codex_review_artifact.py`, `usage_event_id`, session/scope/task/model и `--require-verdict` только для `exec`. Здесь уже известны модель, runtime (`codex`), session, task (или пустое значение), artifact path, mode, resume и usage event id.
6. На `3692-3707` shell удаляет stale temp state, запускает Codex, пишет реальный exit code в `.rc`, а stdout/stderr через `tee` — в JSONL. Затем запускается финализатор и отдельная execution-failure проверка JSONL. `rc=0` читается на `3700-3701`; сейчас он живёт только в shell и не попадает в структурную запись.
7. На `3715-3722` создаётся bg-job типа `run`. В конфиге уже лежат `command`, `success_file=output_abs`, `success_pattern` и timeout 600 s. Ответ инструмента содержит `job_id` и event id; worker получает сообщение, что результат придёт асинхронно.
8. `app/bg_jobs.py:925-1029` запускает этот job. На `993-1001` фиксируются фактический `exit_code` и полный собранный output; ненулевой rc ведёт в `_fail_notify`. На `1005-1025` проверяется существование/размер artifact, optional `## Verdict`, затем `_blind_review_error`; ошибка будит worker через `_fail_notify` (`664-680`). Успех идёт через `_trigger` (`598-617`), который отправляет worker только последние 3000 символов и затем переводит job в `triggered`.
9. `app/codex_review_artifact.py:91-174` читает `.round`. Пустой round — `ValueError` на `101-102`; отсутствующий verdict при `--require-verdict` — `103-104`; при успехе текст атомарно пишется в `output` на `125-133`, UUID/turns — только в соседний `codex_sessions.json` на `135-149`. Учёт usage выполняется после записи текста и намеренно не роняет уже сохранённый результат (`155-174`).

### Где данные уже доступны без нового внешнего вызова

| Факт | Самая ранняя точка | Надёжность сейчас | Что надо записать |
|---|---|---|---|
| Выбранная модель | `mcp_stdio.py:3516` | прямая, после alias resolution | `reviewer_model`, `model_source=caller_or_server_default` |
| Runtime | `mcp_stdio.py:851-866`, выбранный CLI | прямая | `runtime=codex` |
| Worker/session и scope | `mcp_stdio.py:3533-3545` | прямая | immutable ids |
| Задача | `info.task_id` на `3539`, иногда пусто | прямая или явное `unknown` | `task_id`, `task_source=session_lookup` |
| Artifact path | `output_abs` на `3546` | прямая | `artifact_path` |
| Requested/resume round | `resume`, UUID на `3557-3560` | только `fresh`/`resume`; число не сохраняется | reserve integer round или explicit unknown |
| Job id | ответ POST на `3715-3722` | прямая | `job_id` |
| Реальный rc | `.rc` на `3700`, `_run_exec` на `993-1001` | прямая, но не durable | `return_code` |
| Artifact exists/bytes | `_run_exec:1005-1011` | прямая | `artifact_exists`, `artifact_bytes`, optional sha256 |
| Verdict present | `_run_exec:1012-1018`, finalizer `103-104` | положительный structural check, не слово `blocking` | `verdict_present` |
| Empty output | finalizer `101-102` или runner `1007-1008` | прямая причина отказа | `output_empty`, `failure_code` |
| JSONL agent response | `jsonl_file`, execution check `3687-3707` | доступна до cleanup; последний `item.type=agent_message` — положительный признак ответа | `jsonl_response_present`, `recovery_source` |
| Worker notification | `_trigger:608-616`, `_fail_notify:672-680`, timeout `652-658` | факт отправки есть, receipt нет | `notification_outcome`, `notification_event_id` |

## Artifact есть ≠ verdict есть

Текущий пайплайн имеет два независимых признака:

- artifact может существовать и быть непустым (`bg_jobs.py:1005-1011`), но не иметь строки `## Verdict`; тогда `success_pattern`/`_blind_review_error` дают failure. Для `mode=review` финализатор сам не требует verdict, поэтому файл может быть уже атомарно записан (`codex_review_artifact.py:125-133`) до того, как bg-job объявит его непригодным.
- verdict — только положительный признак: заголовок `## Verdict` с непустым содержимым, дополнительно с классифицированным значением. Само наличие `blocking`, `P1`, `APPROVED` внутри произвольной прозы не доказывает авторский исход.

Исторический случай из KB: при `rc=0` artifact бывает пустым, хотя полный ответ сохранился в `/tmp/codex_review_*.jsonl`; достоверный recovery-кандидат — последний JSONL event с `item.type == "agent_message"`. Нельзя повторять review и нельзя считать пустой artifact состоявшимся без такого event.

### Проверка 437 артефактов и живых JSONL

На срезе, использованном #435 (до появления текущего #436), cross-match делался по точному output path из review-вызова и производному пути `/tmp/codex_review_<worker>_<artifact-stem>.jsonl`. Критерий «живой JSONL» — файл существует и содержит terminal `item.type="agent_message"`.

- 437 artifact paths из #435 → 56 классифицированы самим отчётом как `no_verdict`.
- Живых JSONL рядом с этими 56: **0**.
- Текущий `/tmp` содержит sidecars более поздних/других запусков; два существующих sidecar соответствуют #426 и #431, которые в отчёте не относятся к `no_verdict` (в них есть содержательный ответ/принятие). Они не меняют `0/56`.
- Следовательно, исторический recovery через сохранённый JSONL для этого корпуса сейчас не доступен. Миграция не должна объявлять эти 56 восстановленными: `jsonl_response_present=false`, verdict/outcome — `unknown`, если нет прямого доказательства.

## Что можно и нельзя достоверно перенести

| Поле receipt | Достоверно разбирается из старого корпуса | Источник | Иначе |
|---|---|---|---|
| `artifact_path`, exists, bytes, sha256 | да, если файл доступен | путь и файл | `unknown` при исчезновении |
| `verdict_present` | да как структурный факт при `## Verdict` + непустое тело | artifact | `false`, не «успешно» |
| `reviewer_model` | да при metadata или видимом model в log-вызове | metadata / первые 400 B log | `inferred` для исторического default |
| `runtime` | `codex` для вызовов `codex_review` | tool path/CLI | `unknown` при ручном файле без provenance |
| `task_id` | да, если artifact path/log содержит однозначный task path | output path/log | `unknown`, не угадывать по имени |
| `round` | explicit `## Round` даёт нижнюю границу; integer из old `codex_sessions.json` только если он сохранился | artifact/sidecar | `unknown` |
| author outcome | только будущий structured field/tool event | receipt | старые текстовые `FIXED`/`DISAGREE` — `inferred`, не direct; без маркера `unknown` |
| JSONL recovery | только при живом sidecar и terminal agent message | `/tmp/...jsonl` | `unknown`; не повторять вызов |

В частности, 276 model labels из #435 должны навсегда получить `model_source=inferred_historical_default` и `provenance=derived`, даже если значение совпало с фактической моделью. Выдавать их за прочитанные нельзя. Текст ревью остаётся только в artifact; receipt не содержит его копии.

## Разовая миграция

Скрипт должен работать от frozen manifest: один список 437 paths, SHA/размер на момент снимка, найденные metadata/log evidence и migration revision. `--dry-run` строит классификацию, `--apply` перечитывает manifest и отказывается при изменении входа; повторный apply идемпотентен. Для живой БД сначала делается `sqlite3.Connection.backup`, а не `cp`; тесты не вызывают `db.init_db()` на боевом пути.

Классы миграции:

1. **Direct** — path/bytes/hash, explicit metadata, explicit verdict heading, task path и model из вызова, если источник сохранён.
2. **Derived/inferred** — исторический default модели (все 276), round из последовательности текстовых секций, outcome из словесных `FIXED`/`DISAGREE`/`accepted` и только при явном однозначном маркере. Эти поля получают отдельный immutable `source=derived`; последующая выдача не может скрыть это.
3. **Unknown** — отсутствие sidecar, модели и task provenance, пустой artifact без JSONL agent message, а также авторский исход без прямой записи. Unknown — это значение, а не отсутствие строки.

Миграция не копирует prose в БД и не создаёт второй текстовый owner. Если когда-нибудь живой JSONL восстановит пустой artifact, recovery должен атомарно вернуть текст в исходный artifact, пометить `recovery_source=jsonl_agent_message` и не сохранять текст в receipt.

## Review gate

`Review: none — phase-1 read-only fact extraction and plan drafting; no new Codex self-review was necessary.`

- Author model/runtime: `gpt-5.6-luna` / `codex` (worker session `feat-review-receipts`).
- Changed consumers: none; only `docs/tasks/436/research.md` and `plan.md` are new. Future consumers are the named `mcp_stdio`, finalizer, DB and migration seams in the plan.
- Named phase AC: report #435 read whole; current call path reaches model/task/artifact/rc/empty-output/notification points; 0/56 JSONL result; three outcome options; migration provenance classes; different red seams per implementation ticket.
- Mechanical checks: `git diff --check` → no output/exit 0; `wc -l -c docs/tasks/436/{research,plan}.md` → `95 15026` and `110 12607`; required sections and `0/56` found by `rg`.
- Independent evidence: #435 is frozen input; production code was read without modification; sidecar count was cross-matched against exact output paths and terminal `item.type="agent_message"` rather than inferred from artifact prose.

Новых вызовов Codex не запускалось; выводы не являются утверждением о качестве будущей реализации.
