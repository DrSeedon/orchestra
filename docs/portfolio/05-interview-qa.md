# Вопросы технического интервьюера

## 1. Объясните Orchestra за минуту

Это supervisor для долгоживущих AI CLI/SDK-сессий: оркестратор разбивает задачу, worker работает в отдельном Git worktree, а сервер проверяет и squash-мержит результат. Состояние сессий/доставки живёт в SQLite, рабочий результат и canonical knowledge — в Git (`app/manager.py:594-636`; `app/workspace.py:492-538`; `app/workspace.py:1229-1666`; `app/db.py:48-141`; `app/ia/task_store.py:308-351`).

## 2. Зачем отдельный оркестратор, если модель может сама вызвать tools?

Tools не дают authority и durable lifecycle сами по себе. Оркестратор выбирает задачу/роль/model, задаёт `owned_dirs`, принимает результат; server-side код до side effects проверяет spawn rights и конфликты владения (`app/manager.py:701-727`; `app/manager.py:741-767`).

## 3. Что именно даёт Git worktree-изоляция?

У worker свой checkout и branch, поэтому параллельные изменения не пачкают общий индекс. Она не отменяет логические конфликты: их раньше предотвращают `owned_dirs`, а перед merge ловят target-HEAD/dirty-tree/`merge-tree` gates (`app/workspace.py:492-538`; `app/manager.py:701-727`; `app/workspace.py:1264-1359`; `app/workspace.py:1463-1531`).

## 4. Почему merge делает Orchestra, а не сам worker?

Нужна единая transaction boundary: повторно проверить HEAD, конфликт, task refs, diff budget, создать squash commit и receipt. Ручной `git merge` обходит эти consumers; штатный путь сосредоточен в `merge_worktree_to_main` (`app/workspace.py:1229-1246`; `app/workspace.py:1313-1359`; `app/workspace.py:1594-1666`).

## 5. Как Claude, Codex и Grok помещаются за одним интерфейсом?

Общий слой минимален: `BackendLike` задаёт connect/send/events/interrupt/disconnect, registry связывает runtime с factory и матрицей capabilities. Поэтому Claude может иметь persistent stream/reconnect, Codex — per-turn CLI thread/hibernate, а Grok честно объявляет отсутствие mid-turn steering (`app/backend_protocol.py:8-16`; `app/runtime_registry.py:29-53`; `app/runtime_registry.py:330-388`).

## 6. Почему не LangGraph, CrewAI или AutoGen?

Не было отдельного benchmark, доказывающего, что эти проекты хуже; такого утверждения в портфолио нет. Orchestra решала нижний слой, который всё равно остался бы нашим: native CLI resume, OS processes, systemd handoff, Git worktrees/merge, durable FIFO/UNKNOWN delivery и subscription quota; зависимостей LangGraph/CrewAI/AutoGen в проекте нет (`pyproject.toml:1-41`; `app/runtime_registry.py:171-388`; `app/bg_jobs.py:333-510`; `app/workspace.py:492-1666`). Если доминирующей задачей станет декларативный application graph, сравнение надо провести отдельно.

## 7. Как агент переживает restart?

SQLite хранит session envelope и native `session_id`; provider/CLI хранит native thread/transcript, а Git — рабочий результат. На startup `auto_resume_all` сначала поднимает orchestrators, затем workers, усыновляет живые pipes или reconnect-ится по native id (`app/db.py:48-77`; `app/session.py:5126-5165`; `app/manager.py:2207-2329`).

## 8. Что происходит при compact?

Semantics runtime-specific: Codex делает native compact в том же thread; Claude строит structured handoff, получает новый native session id и re-arm-ит prompt injection. Старый id сохраняется в bounded history; Git/artifacts не заменяются summary (`app/session.py:536-553`; `app/session.py:2641-2703`; `app/session.py:2724-2765`; `app/session.py:2996-3019`).

## 9. Почему background jobs находятся на сервере?

Model turn должен закончиться, а timer/command/cron — пережить hibernate и restart. Job сначала пишется в SQLite, при restart восстанавливается, а terminal trigger atomically claim-ится и будит immutable session id (`app/bg_jobs.py:342-446`; `app/bg_jobs.py:474-510`; `app/db.py:2437-2445`; `app/bg_jobs.py:539-580`).

## 10. Зачем Git JSON, если уже есть SQLite?

Git даёт review/diff/provenance/clone и immutable task/fact events; SQLite даёт constraints, current query и FTS. Поэтому DB — content-bound projection с `projection_head`, которую можно удалить и rebuild-ить; на 1 545 JSON / 684 tasks это заняло 848.743 ms (`app/ia/task_store.py:308-390`; `app/ia/runtime.py:74-102`; `docs/tasks/408/measurements.md`, `Deleted task-current.db probe`).

## 11. Как контролируется стоимость?

Три уровня: model routing по классу задачи, server admission по subscription quota и telemetry виртуальной API-стоимости. Главное измерение: tool round-trip стоит около $0.1349 для Claude и $0.1064 для Codex, 69%/72% marginal cost — cache read; поэтому уменьшаются шаги, а не только длина фраз (`app/quota_gate.py:1-20`; `app/quota_gate.py:62-125`; `docs/tasks/345/call-to-dollar.md`; #345). Эти доллары — telemetry, не фактический subscription bill (`app/models.py:263-266`).

## 12. Автоматически ли система выбирает Luna/Sol/Opus?

Не полностью: `spawn_worker` требует, чтобы caller выбрал model по prompt-policy; server затем валидирует model registry/availability и quota admission. Полноценного code-router по task class сейчас нет — это сознательно не выдаётся за реализованную автоматику (`app/mcp_stdio.py:932-949`; `app/manager.py:638-677`; `pipelines/default/prompts/modules/model-routing.md:1-27`; #229).

## 13. Как тестировать недетерминированную систему?

Provider call не является merge oracle. Критичные seams тестируются fake transport/clock/DB, frozen RED до реализации, positive/negative controls и мутациями; live probes вынесены из default pytest (`pyproject.toml:43-61`; `docs/tasks/333/report.md`, `Acceptance evidence`; `docs/tasks/379/report.md`, `Mutation evidence`). Prompt-чеклист сам результата не улучшил: paired score остался 28/30 против 28/30 (`docs/tasks/250/analysis-summary.json`; #250).

## 14. Как доказывается надёжность доставки?

Не обещанием exactly-once. Для внутренних сообщений есть durable state/FIFO; для внешнего Telegram boundary stable receipt может стать `SENT`, retryable pre-submit failure или terminal `UNKNOWN`. UNKNOWN не replay-ится, потому что timeout не доказывает ни отправку, ни неотправку (`docs/tasks/333/contract.md`; `docs/tasks/333/report.md`, `Breaking changes and remaining limits`).

## 15. Самый показательный reliability bug?

Autoincrement `id` приняли за event order: 10.0% из 42 661 call/result пар были инвертированы по `id`, и gate блокировал 266/361 sessions. Pairing по `(ts,id)` и terminal classification сократили закрытые sessions до 2, а восемь мутаций доказали оба направления (`docs/tasks/340/report.md`, §§1,5–6; #340).

## 16. Как система масштабируется?

Измеренно — вертикально: exact 10–12 concurrent Codex turns дали 0/22 errors, TTFT p90 18.372 s и output throughput 32.107 token/s (`docs/tasks/255/measurements.md`; #255). Горизонтальное масштабирование не заявлено готовым: local SQLite, repo mutation lock, worktrees и systemd singleton являются coordination boundaries (`app/db.py:34-42`; `app/workspace.py:496`; `app/workspace.py:1264`; `deploy/orchestra.service:1`). Следующий шаг — shard по repo/scope либо вынести эти owners в distributed stores, но это отдельный design.

## 17. Где были проблемы производительности и как их искали?

Не по ощущению: путь разбивается на transport/canonical/Git/projection/legacy и гоняется A/B/A/B с loadavg. Так `task_create` 38.029–39.876 s локализовали в 36.821–36.893 s projection rebuild и сократили end-to-end до 3.144–4.784 s без роста timeout (`docs/tasks/408/measurements.md`; task #405).

## 18. Как предотвращаете повреждение данных при сбое?

Canonical JSON пишется temp→replace, generation получает content hash; DB projection сверяет exact head и rebuild-ится при долге. Внешние side effects получают idempotency/UNKNOWN state, а merge проверяет target HEAD повторно под repo lock (`app/ia/task_store.py:82-108`; `app/ia/task_store.py:659-729`; `app/ia/runtime.py:74-102`; `app/workspace.py:1264-1359`).

## 19. Что в проекте сделал Максим, а что модели?

Максим — владелец product direction, prompts/pipelines, architecture decisions, approvals и production acceptance; модели выполняют значительную долю research/code/tests в worker sessions. Task reports прямо сохраняют model автора — например, durable Telegram executor был `gpt-5.6-sol`, batch reviewer `gpt-5.6-luna` (`docs/tasks/333/report.md`, `Review`; `docs/tasks/402/report.md`, `Review`). Git identity не разделяет эти роли, поэтому 2 526 коммитов `Maxim`/`DrSeedon` нельзя честно назвать 2 526 ручными коммитами (`docs/portfolio/04-stack.md:85-105`).

## 20. Что пошло не так и чему научились?

Главный паттерн — правдоподобная первая гипотеза часто была неверна: wrapper не объяснил latency (#240), socket queue не ломала restart (#379), новый embedding не улучшил retrieval (#364), «30 перечитываний» оказались обязательным read-before-edit (#345). Поэтому в проекте ценится отозванный вывод с первичным artifact, а не гладкая история успеха (`02-hard-problems.md`; `03-measurements.md`).
