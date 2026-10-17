# Context for item-36

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/AGENTS.md b/AGENTS.md
index f1c7af14d..b626e2f78 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1,25 +1,26 @@
 # Orchestra — правила работы
 
-Общий источник правил проекта — этот версионируемый AGENTS.md.
-CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
-После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
+Единственный источник правил проекта — этот версионируемый AGENTS.md; его читают оба CLI.
+CLAUDE.md в корне быть не должно: Claude Code подхватывает ОБА файла сразу, и разошедшиеся
+копии дают агенту два противоречащих набора правил (проверено 19.09.2026 на 2.1.263).
+Проверка контракта: python scripts/check_instruction_contract.py.
 Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
 а этот файл регулирует работу над самой Orchestra.
 
 ## Границы полномочий
 
 - Не добавляй в корневые инструкции отчёты, логи аварий, текущие проценты квот,
   длинные примеры и разовые обходы. В корне остаются только ограничения, нужные
   практически любой задаче. Исследовательские выводы — в KB, результаты — в tasks.
   Новое постоянное правило требует согласования владельца; существующее уточняй
   у его владельца, не дописывай ещё одну версию в конец файла.
   Каждый корневой файл должен быть меньше 16 KiB. Не повышай этот предел ради
   очередного дополнения и не подключай подробности через автоматические импорты.
 
 - Выполняй согласованную задачу в её границах. Исследование не разрешает реализацию,
   а разовое «делай» не создаёт постоянного разрешения на другие работы.
 - Рестарт Orchestra инициирует только владелец. Самостоятельно не перезапускай,
   не останавливай и не запускай Orchestra или telegram-bot-api, даже ради аварии.
   Если Python-правки требуют рестарта, сообщи об этом одной строкой и жди команды.
   После состоявшегося рестарта проверь cut_names и восстанови срезанных воркеров;
   не принимай потерянное продолжение за отказ работника выполнять задачу.
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7c64a5170..0390cd196 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -13,40 +13,58 @@
   `chat.js`, `usage.js`, `analytics.js`, `tool-renderers.js`, `connection.js`).
   Русский — язык по умолчанию, выбор хранится в `localStorage['orch_lang']` и
   переживает перезагрузку, переключатель доступен со страницы входа, до логина.
   Ключ словаря — сама английская строка, поэтому английская локаль работает без
   словаря и осталась дословно прежней. Механизм целиком клиентский: шаблоны и JS
   дашборд читает с диска живьём, а Python живёт в памяти до рестарта, так что
   серверный перевод доехал бы до экрана только после ручного перезапуска.
   *Triggered case:* продукт подаётся в реестр российского ПО, подп. «л» п. 5 Правил
   (ПП РФ от 16.11.2015 № 1236) требует русский графический интерфейс, а проверяет его
   живой эксперт по экранам — «перевели строки в исходниках» приёмкой не является.
   Приёмка снята прогоном по 41 отрисованному экрану (`.orchestra/tasks/V-584/audit_screens.py`):
   ноль находок латиницы, отрицательный контроль сработал на каждом экране, обратный
   контроль на английской локали — 1564 находки на 41 экране из 41.
   *Known tradeoff:* словарь по английскому ключу молча роняет перевод в английский,
   если надпись в коде переименуют; ловится только тем же прогоном по экранам, поэтому
   его надо звать руками после заметных правок интерфейса. Старый браузерный набор
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
+### Removed
+- 🪞 **Зеркало `CLAUDE.md` убрано: корневые правила проекта живут в одном `AGENTS.md`**
+  (удалён `CLAUDE.md`; `scripts/check_instruction_contract.py` больше не умеет `--sync`, а
+  ЗАПРЕЩАЕТ появление дубля; `app/workspace.py` — `PROJECT_FILES` копирует в worktree и
+  `AGENTS.md`). Claude Code 2.1.263 читает `AGENTS.md` сам — проверено экспериментом: в пустом
+  каталоге с одним `AGENTS.md` агент назвал записанное в нём кодовое слово. Проверен и случай
+  двух файлов: CLI подхватывает ОБА сразу и сообщает о расхождении, то есть копия — не
+  «совместимость», а второй источник правды.
+  *Triggered case:* пока зеркало существовало, оно дважды разъезжалось с источником; в одном
+  из случаев `CLAUDE.md` был на 671 байт короче и не содержал правил владельца про маскирование
+  секретов и про Codex — Claude-агенты их просто не видели.
+  *Known tradeoff:* проекты, где в корне лежит только `CLAUDE.md` (например `University`),
+  продолжают работать через `sync_agents_md`, который копирует их правила в `AGENTS.md` для
+  Codex; этот путь не тронут.
+  *Reasoning:* пользовательский уровень остаётся на `~/.claude/CLAUDE.md` — глобальный
+  `~/.claude/AGENTS.md` CLI НЕ читает (проверено там же), поэтому дубля наверху нет: у нас
+  `~/.codex/AGENTS.md` симлинком указывает на тот же файл.
+
 ### Fixed
 - 🧯 **Один кривой вызов инструмента больше не убивает остаток сессии воркера**
   (`app/harness/loop.py` — `_sanitize_tool_args`, вызывается после диспетча раунда).
   Ассистентский месседж с `tool_calls` уезжает в КАЖДЫЙ следующий запрос, а строгий
   провайдер отвергает весь запрос, если аргументы хоть одного вызова — не строка-объект
   JSON: Cohere отвечает `invalid tool call provided in messages[42].tool_calls[0]: tool
   arguments must be a stringified JSON object`. Разбор и сообщение об ошибке уже
   происходят при вызове инструмента, поэтому в истории негодное значение заменяется
   на `{}`; валидный объект не переформатируется — он уезжает рядом с подписью рассуждений.
   *Triggered case:* 17.09.2026 воркер на `cohere/north-mini-code:free` после одного
   такого вызова не смог сделать больше ни одного хода.
 - 🚫 **Бесплатные маршруты, отказавшие в нашей пробе, больше не предлагаются и не
   проходят спавн** (`app/models.py` — `BLOCKED_HARNESS_ROUTES` и проверка в
   `validate_harness_model_spec`; `app/model_catalog.py` — фильтр в `apply_model_catalog`).
   Каталог OpenRouter продолжает рекламировать у них поддержку инструментов, поэтому
   допуск по живому каталогу (#V-582) их пропускал. Заблокированы восемь: `inkling`
   и `inkling-small` (HTTP 403 — открыты только в харнесах провайдера), `laguna-s-2.1`,
   `laguna-xs-2.1`, `gemma-4-31b-it` (HTTP 429 в обоих прогонах), `nex-n2.5-mini`
   (таймаут чтения 90 с), `nemotron-3-nano-omni-...-reasoning` (инструмент не вызывается),
   `ling-3.0-flash-vl` (вызывает и игнорирует результат).
diff --git a/CLAUDE.md b/CLAUDE.md
deleted file mode 100644
index f1c7af14d..000000000
--- a/CLAUDE.md
+++ /dev/null
@@ -1,98 +0,0 @@
-# Orchestra — правила работы
-
-Общий источник правил проекта — этот версионируемый AGENTS.md.
-CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
-После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
-Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
-а этот файл регулирует работу над самой Orchestra.
-
-## Границы полномочий
-
-- Не добавляй в корневые инструкции отчёты, логи аварий, текущие проценты квот,
-  длинные примеры и разовые обходы. В корне остаются только ограничения, нужные
-  практически любой задаче. Исследовательские выводы — в KB, результаты — в tasks.
-  Новое постоянное правило требует согласования владельца; существующее уточняй
-  у его владельца, не дописывай ещё одну версию в конец файла.
-  Каждый корневой файл должен быть меньше 16 KiB. Не повышай этот предел ради
-  очередного дополнения и не подключай подробности через автоматические импорты.
-
-- Выполняй согласованную задачу в её границах. Исследование не разрешает реализацию,
-  а разовое «делай» не создаёт постоянного разрешения на другие работы.
-- Рестарт Orchestra инициирует только владелец. Самостоятельно не перезапускай,
-  не останавливай и не запускай Orchestra или telegram-bot-api, даже ради аварии.
-  Если Python-правки требуют рестарта, сообщи об этом одной строкой и жди команды.
-  После состоявшегося рестарта проверь cut_names и восстанови срезанных воркеров;
-  не принимай потерянное продолжение за отказ работника выполнять задачу.
-- Не выкатывай код и не выполняй git pull на VPS самостоятельно.
-  Не обращайся к чужим оркестраторам ради инфраструктурной координации.
-- Git remote origin — наш публичный. Другие remotes (включая enterprise и vadim)
-  не трогай. Сверяй git remote -v; не делай force-push и не теряй чужие коммиты.
-- Существующие чужие правки сохраняй. Работай в отдельной ветке/worktree;
-  мерж и запуск сервисов не следуют автоматически из успешных тестов.
-  Не убивай full-cycle воркера только из-за завершённого merge: он может ждать
-  следующего этапа. Условия завершения принадлежат модулю worker-lifecycle.
-- Перед закрытием воркера сохрани результат в main либо выводы и причину отказа
-  в хронике со ссылкой на исходную ветку. Одна preserve/*-метка не заменяет
-  извлечение знаний; полномочия на мерж и удаление проверяются отдельно.
-- **Маскирование секретов снято с пути ОТОБРАЖЕНИЯ и живёт только на границе публикации (решение владельца 06.09.2026, дословно: «журнал наш бд по дефолту должен быть гит игнор и утечки быть не должно, а на фронте мне не ломай секреты отображение»).** `db.add_log`, `live_broker.publish` и копии доставок пишут и отдают содержимое ДОСЛОВНО: `data/` целиком под `.gitignore` (`git check-ignore -v data/orchestra.db` → `.gitignore:11`), в индексе её нет, наружу журнал не публикуется. Маскирование там не предотвращало утечку, а портило рабочие данные — ссылка-приглашение MTProto-прокси приходила изуродованной, потому что её ПУБЛИЧНЫЙ параметр `secret=` попадал под общее правило. `app/secret_mask.py` и его тесты сохранены и остаются владельцем правила: применять их надо к тому, что уезжает В GIT и наружу, а не к тому, что владелец читает у себя. Остаточный риск назван явно: агент, копирующий содержимое лога в трекаемый артефакт, по-прежнему может протащить секрет — поэтому сырые выгрузки проверяются фильтром ПО ФОРМЕ секрета перед коммитом, и это единственное место, где маска обязательна.
-- Не публикуй пароли, OAuth-токены, ключи, содержимое .env или секреты из логов.
-  Секрет в собственном локальном хранилище сам по себе не доказывает утечку.
-  Не ротируй его и не останавливай работу только из-за существования; публичную
-  утечку сообщай немедленно. Сырые выгрузки проверяй перед коммитом.
-- Ноутбук владельца — рабочая машина: тяжёлые проверки последовательно,
-  nice=15 и MemoryMax=2G. /tmp может быть tmpfs; большие временные данные — /mnt/data.
-  Не убивай процессы по широкому pkill/сохранённому PGID; работай с точным владельцем.
-- Никаких новых платных API-вызовов вместо подписки без разрешения.
-  OpenRouter Harness допускает только точные разрешённые :free маршруты.
-
-## Текущие владельцы и рабочие пути
-
-- FastAPI + SSE, SQLite, внешние CLI и stdio MCP; главный код — app/.
-  Локальный dashboard обычно на 127.0.0.1:8888. Состояние конкретного сервиса
-  проверяй read-only; исторический рассказ не подтверждает, что он сейчас запущен.
-- Модели, effort и допуск: текущий pipeline, model-routing и app/quota_gate.py.
-  Не меняй политику по историческим процентам. Денежные суммы dashboard —
-  API-equivalent, не счёт владельцу; цена API не доказывает размер подписочной квоты.
-- Чат показывает свежий сетевой snapshot последних сообщений, затем SSE.
-  Не возвращай зеркало истории в IndexedDB или stale-while-revalidate для чата.
-- База знаний — .orchestra/kb/, доказательства задач — .orchestra/tasks/,
-  память — .orchestra/workers/, история — в Git по kb/history.md.
-  Raw-отчёт не становится текущим правилом без проверки и принятия вывода.
-
-## Найти нужное, не прочитать всё
-
-Оглавление тем и порядок поиска по нему платформа вставляет в системный промпт сама
-(`app/kb_index.py`, модуль knowledge). Здесь остаётся только обязанность автора:
-новую тему заводи файлом в .orchestra/kb/ И строкой с кратким описанием в
-.orchestra/kb/README.md — тема без этой строки до агентов не доедет.
-Запись и поиск: .orchestra/pipelines/default/prompts/modules/knowledge.md.
-
-## Реализация и проверка
-
-- Перед починкой симптома сверь текущий код. Историю изменения символа изучай
-  при регрессии, неясном происхождении поведения или риске отменить прежнее решение.
-  Не меняй соседние системы, не расширяй задачу и не добавляй новую зависимость
-  в обязательный промпт раньше, чем её реальный путь проверен.
-- Один владелец правила и состояния; данные из API, конфигов и текущего кода
-  важнее исторического замера. Индекс/проекция не заменяет канонический источник.
-- Тестируй поведение: отрицательное и разрешающее плечо, границы, конкурентность,
-  восстановление. Зелёный тест должен краснеть при возвращении дефекта.
-  Таймауты тестов ограничивают зависание, а не подменяют замер производительности.
-- Тесты не используют боевую БД, токены TG, NOTIFY_SOCKET живого сервиса и настоящие
-  CLI провайдеров без отдельной цели прогона. Копия живой SQLite — backup(), не cp.
-- CLI-окружение проверяется по месту импорта: запускай тесты через python -m pytest,
-  а не консольный pytest; в отчёте укажи абсолютный путь импортированного app-модуля.
-- Прежние опыты замеров — .orchestra/kb/evidence-methods.md. Разделяй до/после и шум;
-  не объявляй улучшение по размеру файла, числу тестов или имени модели.
-- Не выдавай код на диске за работающий Python в живом процессе.
-  JS/CSS могут загрузиться без рестарта; Python/CLI-конфиги имеют свой жизненный цикл.
-- Ошибки платформы фиксируй через report_bug, если инструмент доступен;
-  результаты своей задачи сохраняй в .orchestra/tasks/<id>/.
-- До закрытия работы: проверь diff, нужные тесты, отсутствие секретов и потерь
-  чужих правок. Сообщи результат, фактическую проверку и оставшийся риск.
-
-## Исторический источник
-
-Полный прежний документ доступен в Git:
-`git show 9a1735f1695519a445f393802c2154bd37337e38:.orchestra/archive/instructions/2026-09-05-CLAUDE.md`.
-Это история, не действующие правила. Остальные исходники — по .orchestra/kb/history.md.
diff --git a/README.md b/README.md
index 288284704..5412938bd 100644
--- a/README.md
+++ b/README.md
@@ -107,41 +107,41 @@ not to*:
 | Survive a platform restart; idle workers hibernate and release the process tree | ✅ | SQLite sessions + auto-resume, `app/session_hibernate.py` |
 | Workers message each other directly, with durable delivery receipts | ✅ | `app/message_deliveries.py` |
 | Workers spawning their own workers | 🚧 | Forbidden by the worker's role prompt, not by the code: `spawn_worker` carries no role gate, so a worker that ignores its instructions can still call it. The rule exists because the child edits the same files on a second branch, so the two diffs compete at merge and one of them loses — plus a task nobody ordered |
 | Git worktree per worker, squash merge to main | ✅ | `app/workspace.py` |
 | Two workers cannot own the same directory | ✅ | spawn refuses on overlap, `dirs_overlap` at `app/manager.py:616` |
 | Insertion budget at merge, with a waiver that is recorded | ✅ | 2 000 lines, `MAX_DIFF_INSERTIONS` at `app/diff_budget.py:16` |
 | The platform, not the agent, runs the tests that decide a merge | ✅ | A mapped test subset gates every merge and blocks on failed *or* inconclusive (`gate_blocks`, `app/merge_operations.py:2089`). A frozen acceptance oracle is pinned and run when the task carries one (`evaluate_pinned_oracle`, `app/acceptance.py:349`); without one, a merge touching `app/` or `tests/` on a non-main target is refused outright (`nested_behavioral`, `app/merge_operations.py:1071`) |
 | Cross-model review as a **code-enforced** merge gate | ✅ | Enforced at merge since #462: the merge runner blocks on a review-coverage verdict (`review_coverage_policy_active`, `app/merge_operations.py:1934`) and refuses with `RECORD_REVIEW_THEN_NEW_OPERATION` when no receipt matches the exact snapshot (`app/merge_operations.py:635`). The policy is switched on by a marker inside the review skill and read at runtime (`policy_active`, `app/review_coverage.py:382`) — on as of 2026-09-05. Known limit: the receipt is matched by the worker's own session id, so an orchestrator cannot certify a review on the worker's behalf |
 | Human approval as machine-checkable state | 🚧 | Lives in chat and in the `<approval-gate>` prompt block. No approval receipt exists in the database and merge doesn't ask for one |
 | Sandbox around commands an agent runs | 🚧 | The worktree isolates *files*, not execution. Our reviewer runs `-s danger-full-access -a never` (`app/mcp_stdio.py:4449`). That is a decision we have lived with, not a limit of the machine: `cat /proc/sys/kernel/unprivileged_userns_clone` answers `1` here, and no sandbox binary is installed to use it. No isolation work is underway |
 | Several vendors' models behind one runtime contract | ✅ | 4 runtimes: the Claude Code, Codex and Grok CLIs, plus our own in-process OpenRouter Harness — `BUILTIN_RUNTIMES` at `app/runtime_registry.py:330` |
 | Adding a new CLI agent by config | 🚫 | Every runtime is a hand-written backend; there is no config path. Orca, by contrast, advertises "any CLI agent" |
 | Write with one vendor's model, review with another's | ✅ | `codex_review`, `app/mcp_stdio.py:4154` — the review starts a different vendor's CLI |
 | Quota gate that blocks workers near a subscription wall | ✅ | `line_limit` at `app/quota_gate.py:115` |
 | The same gate applied to orchestrators | 🚫 | Exempt on purpose (owner, 2026-09-03): an orchestrator that stops talking is worse than one that overspends |
 | Paid model routes in the built-in harness | 🚫 | Exact `:free` routes only, `app/harness/llm.py:167` |
 | Free models as the default workhorse | 🚫 | Measured: 2 of 30 closed tickets solved (6.67 %), and 53 of 60 runs failed on availability rather than quality (#422) |
 | Grok kept current with Claude and Codex | 🚫 | Added for one narrow job and left unmaintained. It still runs; it is not a peer |
 | Lexical project memory agents must read before working | ✅ | `.orchestra/kb/`, one fact per line with the command that proves it |
 | Vector / semantic memory | 🚫 | Built, measured, retired: on an 18-question holdout from this repo, vector search scored **0 unique wins against 6 for plain `rg`**. The implementation and optional ML dependencies have been removed |
-| Bounded shared startup instructions | ✅ | `AGENTS.md` and `CLAUDE.md` are byte-identical. The KB topic directory is not in them: the platform injects it into the system prompt from `.orchestra/kb/README.md` of the agent's own project, so a new topic is visible on the next turn without a restart. CI rejects drift, missing topics and oversized files (`python3 scripts/check_instruction_contract.py`). Topic details and the full former guide stay on demand |
+| Bounded shared startup instructions | ✅ | `AGENTS.md` is the single root rules file — both Claude Code and Codex read it, and a `CLAUDE.md` copy is refused because the agent receives BOTH at once and any drift hands it contradictory rules. The KB topic directory is not in them: the platform injects it into the system prompt from `.orchestra/kb/README.md` of the agent's own project, so a new topic is visible on the next turn without a restart. CI rejects the duplicate, missing topics and oversized files (`python3 scripts/check_instruction_contract.py`). Topic details and the full former guide stay on demand |
 | Dashboard (`dashboard.html` via `app/routes/system.py:77`) and Telegram control (`app/tg_bridge.py`) | ✅ | Voice messages are transcribed with Deepgram `nova-3`, `app/transcription.py:72` |
 | Terminal client, desktop or mobile app | 🚫 | Never built: the workplace is the dashboard plus Telegram. Phone access is Telegram, not an app |
 | Browser-side cache of chat history | 🚫 | Built, then removed on purpose: a local mirror cannot prove nothing appeared after its watermark, so it can show a stale frame as current. `no-store` is set on the server (`app/routes/sessions.py:602`) and on the client (`app/static/js/app.js:1274`) |
 | One-command install, prebuilt binaries, Docker image | 🚧 | `git clone` + `uv sync` + your own vendor CLIs and subscriptions. Nothing is published as a release artifact |
 | CI that runs on every push and passes | 🚧 | The workflow is real and runs on every push and PR to `main` (`.github/workflows/ci.yml`), and it is red: as of 2026-09-05 fewer than one completed run in a hundred has ended green. Two causes, both visible in the log of the last failure — it printed dozens of failed tests, and then the process was killed outright with exit code 137, out of memory, about four fifths of the way through. The full suite does not survive a single process on our own host either, which is why a merge is gated by the mapped subset the platform runs itself (row above) and not by this workflow. There is deliberately no CI badge in the header: a red badge tells a stranger "the project is broken", and the true statement is narrower than that |
 | Standing approval or an auto-queue of tasks | 🚫 | Every task is approved by hand (owner, 2026-08-27) so that nothing gets built that wasn't asked for |
 
 ### And how is this different from sub-agents?
 
 The honest answer is that it got less different during 2026: sub-agents gained their own context,
 messaging between agents, nesting, and opt-in worktrees. What did not change is who owns the
 lifecycle and where the vendor boundary runs. Quotes below are from the vendors' own docs,
 checked **2026-09-03**.
 
 | | **Orchestra** | **Claude Code sub-agents** | **Codex sub-agents** |
 |---|---|---|---|
 | Lifecycle belongs to | a row in our database — the worker survives restarts and hibernation | the parent conversation: "Each subagent invocation creates a new instance rather than continuing an earlier one" | the parent run: "Codex waits until all requested results are available, then returns a consolidated response" |
 | Repo isolation | a worktree per worker, always | opt-in `isolation: worktree`; by default "A subagent starts in the main conversation's current working directory" | "Subagents inherit your current sandbox policy" |
 | Model vendor | four runtimes: Anthropic, OpenAI, xAI, OpenRouter | `model`: "`sonnet`, `opus`, `haiku`, `fable`, a full model ID such as `claude-opus-5`, or `inherit`" | `gpt-5.6`, `gpt-5.6-terra`, `gpt-5.6-luna` |
 | Review | a different vendor's model, required by role prompt (see the 🚧 row above) | "Spawn a teammate using the security-reviewer agent type" | "Review this branch with parallel subagents" |
diff --git a/README.ru.md b/README.ru.md
index 87827e91f..399a69609 100644
--- a/README.ru.md
+++ b/README.ru.md
@@ -107,41 +107,41 @@ uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
 | Переживают рестарт платформы; простаивающие воркеры засыпают и отпускают дерево процессов | ✅ | сессии в SQLite + авто-резюм, `app/session_hibernate.py` |
 | Воркеры пишут друг другу напрямую, с надёжными квитанциями доставки | ✅ | `app/message_deliveries.py` |
 | Воркер поднимает своих воркеров | 🚧 | Запрещено ролевым промптом воркера, но не кодом: у `spawn_worker` нет ролевого гейта, поэтому воркер, проигнорировавший инструкцию, всё ещё может его вызвать. Правило существует потому, что ребёнок правит те же файлы на второй ветке — два диффа встречаются на мерже, и один из них проигрывает, плюс появляется задача, которую никто не заказывал |
 | Git worktree на воркера, squash-мерж в main | ✅ | `app/workspace.py` |
 | Два воркера не могут владеть одним каталогом | ✅ | спавн отказывает при пересечении, `dirs_overlap` в `app/manager.py:616` |
 | Потолок вставленных строк на мерже, с записываемым вейвером | ✅ | 2 000 строк, `MAX_DIFF_INSERTIONS` в `app/diff_budget.py:16` |
 | Тесты, решающие судьбу мержа, запускает платформа, а не агент | ✅ | Сопоставленное подмножество тестов гейтит каждый мерж и блокирует и на падении, и на неопределённости (`gate_blocks`, `app/merge_operations.py:2089`). Замороженный приёмочный оракул пиннится и исполняется, когда он у задачи есть (`evaluate_pinned_oracle`, `app/acceptance.py:349`); когда его нет, мерж, трогающий `app/` или `tests/` не в main, отбивается целиком (`nested_behavioral`, `app/merge_operations.py:1071`) |
 | Кросс-вендорное ревью как гейт мержа **на уровне кода** | ✅ | Принуждается на мерже с #462: раннер мержа блокируется по вердикту покрытия ревью (`review_coverage_policy_active`, `app/merge_operations.py:1934`) и отказывает с `RECORD_REVIEW_THEN_NEW_OPERATION`, когда под точный снимок нет квитанции (`app/merge_operations.py:635`). Политика включается маркером внутри скилла ревью и читается в рантайме (`policy_active`, `app/review_coverage.py:382`) — на 05.09.2026 включена. Известное ограничение: квитанция ищется по id сессии самого воркера, поэтому оркестратор не может заверить ревью за него |
 | Апрув человека как машинно-проверяемое состояние | 🚧 | Живёт в чате и в блоке промпта `<approval-gate>`. Квитанции апрува в базе нет, и мерж её не спрашивает |
 | Песочница вокруг команд, которые запускает агент | 🚧 | Worktree изолирует *файлы*, а не исполнение. Наш ревьюер работает с `-s danger-full-access -a never` (`app/mcp_stdio.py:4449`). Это то, с чем мы живём, а не ограничение машины: `cat /proc/sys/kernel/unprivileged_userns_clone` отвечает здесь `1`, просто бинарника песочницы под это не поставлено. Работы по изоляции не ведутся |
 | Модели нескольких вендоров под одним контрактом рантайма | ✅ | 4 рантайма: CLI Claude Code, Codex и Grok плюс собственный внутрипроцессный OpenRouter Harness — `BUILTIN_RUNTIMES` в `app/runtime_registry.py:330` |
 | Подключение нового CLI-агента конфигом | 🚫 | Каждый рантайм — написанный руками бэкенд, конфигом ничего не добавляется. У Orca, для сравнения, заявлен «any CLI agent» |
 | Пишет модель одного вендора, ревьюит модель другого | ✅ | `codex_review`, `app/mcp_stdio.py:4154` — ревью поднимает CLI другого вендора |
 | Квотный гейт, блокирующий воркеров у стены подписки | ✅ | `line_limit` в `app/quota_gate.py:115` |
 | Тот же гейт на оркестраторах | 🚫 | Исключены намеренно (решение владельца, 03.09.2026): замолчавший оркестратор хуже перерасходовавшего |
 | Платные маршруты во встроенном харнессе | 🚫 | Только точные `:free`, `app/harness/llm.py:167` |
 | Бесплатные модели как рабочая лошадь | 🚫 | Замерено: 2 закрытых тикета из 30 (6,67 %), и 53 прогона из 60 упали на недоступности маршрута, а не на качестве (#422) |
 | Grok поддерживается наравне с Claude и Codex | 🚫 | Заведён под одну узкую задачу и с тех пор не развивается. Он работает, но он не равный |
 | Лексическая память проекта, которую агент обязан прочитать до работы | ✅ | `.orchestra/kb/`, один факт в строке и команда, которая его доказывает |
 | Векторная / семантическая память | 🚫 | Сделали, замерили, убрали: на holdout из 18 вопросов по этому репозиторию у вектора **0 уникальных побед против 6 у обычного `rg`**. Реализация по-прежнему в коде и работает, если её включить (`--extra rag`, по умолчанию выключено) — просто мы на ней больше не строим |
-| Ограниченный общий стартовый контекст | ✅ | `AGENTS.md` и `CLAUDE.md` побайтно одинаковы. Оглавления KB в них нет: платформа вставляет его в системный промпт из `.orchestra/kb/README.md` проекта самого агента, поэтому новая тема видна на следующем ходе без рестарта. CI отвергает рассинхрон, пропущенные темы и превышение размера (`python3 scripts/check_instruction_contract.py`). Подробности тем и полный прежний гид читаются по необходимости |
+| Ограниченный общий стартовый контекст | ✅ | `AGENTS.md` — единственный корневой файл правил: его читают и Claude Code, и Codex, а копия `CLAUDE.md` запрещена, потому что агенту доезжают ОБА файла сразу и любое расхождение даёт ему два противоречащих набора правил. Оглавления KB в них нет: платформа вставляет его в системный промпт из `.orchestra/kb/README.md` проекта самого агента, поэтому новая тема видна на следующем ходе без рестарта. CI отвергает дубль, пропущенные темы и превышение размера (`python3 scripts/check_instruction_contract.py`). Подробности тем и полный прежний гид читаются по необходимости |
 | Дашборд (`dashboard.html` через `app/routes/system.py:77`) и управление из Telegram (`app/tg_bridge.py`) | ✅ | Голосовые расшифровываются Deepgram `nova-3`, `app/transcription.py:72` |
 | Терминальный клиент, десктопное или мобильное приложение | 🚫 | Не делали: рабочее место — дашборд плюс Telegram. С телефона работают через Telegram, а не через приложение |
 | Кеш истории чата на стороне браузера | 🚫 | Сделали и осознанно убрали: локальное зеркало не может доказать, что после его watermark ничего не появилось, поэтому оно способно показать устаревший кадр как свежий. `no-store` выставлен и на сервере (`app/routes/sessions.py:602`), и на клиенте (`app/static/js/app.js:1274`) |
 | Установка одной командой, готовые бинарники, Docker-образ | 🚧 | `git clone` + `uv sync` + свои вендорские CLI и подписки. Как релизный артефакт не публикуется ничего |
 | CI на каждый пуш, и зелёный | 🚧 | Workflow настоящий и запускается на каждый пуш и PR в `main` (`.github/workflows/ci.yml`), и он красный: на 05.09.2026 зелёным закончился меньше чем один прогон из ста. Причины две, и обе видны в логе последнего падения — он успел напечатать несколько десятков упавших тестов, после чего процесс убили по памяти с кодом 137 примерно на четырёх пятых пути. Полный сьют не переживает одного процесса и на нашей машине, поэтому судьбу мержа решает сопоставленное подмножество, которое платформа запускает сама (строка выше), а не этот workflow. Бейджа CI в шапке нет намеренно: красный бейдж говорит постороннему «проект сломан», а правда у́же |
 | Стоячее разрешение или автоочередь задач | 🚫 | Каждая задача апрувится руками (решение владельца, 27.08.2026), чтобы не строилось то, чего не просили |
 
 ### А чем это отличается от субагентов?
 
 Честный ответ: за 2026 год отличий стало меньше. Субагенты обзавелись своим контекстом, перепиской между собой, вложенностью и опциональным worktree. Не изменилось другое — кому принадлежит жизненный цикл и где проходит граница вендора. Цитаты ниже из документации самих вендоров, сверены **03.09.2026**.
 
 | | **Orchestra** | **Субагенты Claude Code** | **Субагенты Codex** |
 |---|---|---|---|
 | Жизненный цикл принадлежит | строке в нашей базе — воркер переживает рестарты и гибернацию | родительскому диалогу: «Each subagent invocation creates a new instance rather than continuing an earlier one» | родительскому прогону: «Codex waits until all requested results are available, then returns a consolidated response» |
 | Изоляция репозитория | worktree на воркера, всегда | опциональный `isolation: worktree`; по умолчанию «A subagent starts in the main conversation's current working directory» | «Subagents inherit your current sandbox policy» |
 | Вендор модели | четыре рантайма: Anthropic, OpenAI, xAI, OpenRouter | `model`: «`sonnet`, `opus`, `haiku`, `fable`, a full model ID such as `claude-opus-5`, or `inherit`» | `gpt-5.6`, `gpt-5.6-terra`, `gpt-5.6-luna` |
 | Ревью | модель другого вендора, гейт на мерже (строка ✅ выше) | «Spawn a teammate using the security-reviewer agent type» | «Review this branch with parallel subagents» |
 
 Замер по нашей же базе, 02.09.2026: субагенты обоих видов прожили в нашем контуре медиану **12,5 с** (p90 75,1 с), и дольше десяти минут не прожил **ни один (0,0 %)**; у сессий воркеров p90 — **130,6 ч**. Это разница в природе, а не в длительности, и она режет в обе стороны. Субагент — один вызов инструмента внутри работающего процесса; воркер здесь стоит строки в базе, ветки и worktree, поэтому под «сходи прочитай двадцать файлов и вернись» вся эта машинерия не даёт ничего. Ещё субагенты из коробки вкладываются «up to three layers below the main conversation», а мы это запрещаем правилом.
 
diff --git a/app/workspace.py b/app/workspace.py
index b09268a93..6f6d2fb02 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -9,41 +9,44 @@ import logging
 import os
 import re
 import subprocess
 import uuid
 from contextlib import contextmanager
 from dataclasses import dataclass
 from pathlib import Path
 from typing import TYPE_CHECKING, Callable, Literal, NotRequired, TypedDict
 
 if TYPE_CHECKING:
     # Только для аннотаций (строковые аннотации + from __future__ import annotations):
     # рантайм-импорт не нужен, объекты приходят готовыми от вызывающего. Так избегаем
     # циклической зависимости (pipeline ← workspace).
     from app.pipeline import Symlink, Worktree as WorktreeCfg
 
 logger = logging.getLogger(__name__)
 
 WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
 # Files copied into each new worktree so workers get project config without
 # being on the main branch (CLAUDE.md = project rules, .env = secrets, .mcp.json = tools)
-PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")
+# AGENTS.md читают оба CLI (Claude Code 2.1.263 и Codex), CLAUDE.md остаётся ради
+# проектов, где он ещё единственный источник правил. Копируем оба: отсутствующий
+# файл просто пропускается, а worktree без правил — это агент без правил.
+PROJECT_FILES = ("AGENTS.md", "CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")
 
 
 @dataclass
 class Worktree:
     path: str
     branch: str
     branch_created: bool = False
     initial_head: str = ""
 
 
 class MergeOutcome(TypedDict):
     ok: bool
     state: Literal["merged", "conflict", "failed", "partial"]
     commit_point: Literal["not_reached", "rolled_back", "target_committed", "unknown"]
     target_branch: str
     target_before: str
     target_after: str
     worker_branch: str
     worker_head: str
     conflicts: list[str]
diff --git a/scripts/check_instruction_contract.py b/scripts/check_instruction_contract.py
index 4dffc5bf8..5abbded38 100644
--- a/scripts/check_instruction_contract.py
+++ b/scripts/check_instruction_contract.py
@@ -1,98 +1,74 @@
-"""Check the shared root rules; --sync explicitly regenerates the Claude copy."""
+"""Check the shared root rules: one file, under budget, with a complete KB index."""
 import argparse
-import os
 from pathlib import Path
 import re
 import sys
-import tempfile
 
 _REPO_ROOT = Path(__file__).resolve().parents[1]
 if str(_REPO_ROOT) not in sys.path:
     sys.path.insert(0, str(_REPO_ROOT))
 
 from app.kb_index import kb_topic_files, kb_topic_index
 
 MAX_INSTRUCTION_BYTES = 16 * 1024
-FILES = ("AGENTS.md", "CLAUDE.md")
+SOURCE = "AGENTS.md"
+# Claude Code 2.1.263 читает CLAUDE.md И AGENTS.md ОБА сразу (проверено экспериментом
+# 19.09.2026: два файла с разными правилами — агент назвал оба и указал расхождение).
+# Пока копия существовала, она дважды разъезжалась с источником, и Claude-агенты
+# не видели части правил владельца. Поэтому дубль запрещён, а не синхронизируется.
+FORBIDDEN_DUPLICATE = "CLAUDE.md"
 
 
 def check_kb_index(root: Path) -> None:
     """Every topic file must be listed once, with a description, inside ``kb/``.
 
     The root rules no longer carry the list — the platform injects it from
     ``kb/README.md`` into the system prompt (:func:`app.kb_index.kb_index_block`). This is
     what still catches a topic nobody indexed, which no agent would ever be shown.
     """
     missing = kb_topic_files(root) - kb_topic_index(root).keys()
     if missing:
         raise ValueError(f"KB topics missing from README: {', '.join(sorted(missing))}")
 
 
 def _read(path: Path) -> bytes:
     if path.is_symlink():
         raise ValueError(f"{path.name}: expected a regular file, not a symlink")
     return path.read_bytes()
 
 
 def _validate(body: bytes, name: str) -> None:
     text = body.decode("utf-8")
     if not text.strip():
         raise ValueError(f"{name}: instructions must not be empty")
     if len(body) >= MAX_INSTRUCTION_BYTES:
         raise ValueError(f"{name}: {len(body)} bytes exceeds the <16 KiB budget")
     without_code = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", text)
     if re.search(r"(?<![\w\\])@(?=[\w./~])\S+", without_code):
         raise ValueError(f"{name}: root imports are not allowed; use on-demand links")
 
 
 def check(root: Path) -> None:
-    bodies = [_read(root / name) for name in FILES]
-    for name, body in zip(FILES, bodies):
-        _validate(body, name)
-    if bodies[0] != bodies[1]:
-        raise ValueError("AGENTS.md and CLAUDE.md differ; run --sync after editing AGENTS.md")
+    _validate(_read(root / SOURCE), SOURCE)
+    duplicate = root / FORBIDDEN_DUPLICATE
+    if duplicate.exists() or duplicate.is_symlink():
+        raise ValueError(
+            f"{FORBIDDEN_DUPLICATE} is back: both files reach the agent at once and a drift "
+            f"feeds it contradictory rules. Keep {SOURCE} only")
     check_kb_index(root)
 
 
-def sync(root: Path) -> None:
-    body = _read(root / "AGENTS.md")
-    _validate(body, "AGENTS.md")
-    check_kb_index(root)  # before any write: a bad index must leave both copies untouched
-    for name in FILES:
-        if (root / name).is_symlink():
-            raise ValueError(f"{name}: refusing to overwrite a symlink")
-    _write(root / "CLAUDE.md", body)
-    check(root)
-
-
-def _write(target: Path, body: bytes) -> None:
-    if target.exists() and target.read_bytes() == body:
-        return
-    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
-    try:
-        os.fchmod(fd, 0o644)
-        with os.fdopen(fd, "wb") as output:
-            output.write(body)
-        os.replace(temporary, target)
-    finally:
-        Path(temporary).unlink(missing_ok=True)
-
-
 def main() -> int:
     parser = argparse.ArgumentParser(description=__doc__)
     parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
-    parser.add_argument("--sync", action="store_true")
     args = parser.parse_args()
     try:
-        if args.sync:
-            sync(args.root)
-        else:
-            check(args.root)
+        check(args.root)
     except (OSError, ValueError) as error:
         parser.exit(1, f"Instruction contract: {error}\n")
-    print("Instruction contract OK: identical, non-empty UTF-8 root rules below 16 KiB each")
+    print(f"Instruction contract OK: {SOURCE} is the only root rules file, below 16 KiB")
     return 0
 
 
 if __name__ == "__main__":
     raise SystemExit(main())
diff --git a/tests/test_instruction_contract.py b/tests/test_instruction_contract.py
index d31349d28..744d87802 100644
--- a/tests/test_instruction_contract.py
+++ b/tests/test_instruction_contract.py
@@ -1,95 +1,80 @@
-from pathlib import Path
+"""Контракт корневых правил: один файл, под бюджетом, с полным оглавлением KB.
+
+Claude Code 2.1.263 читает CLAUDE.md И AGENTS.md ОБА (проверено экспериментом 19.09.2026:
+два файла с разными правилами — агент назвал оба и указал расхождение). Пока копия
+существовала, она дважды разъезжалась с источником, и Claude-агенты не видели части правил
+владельца. Поэтому тест сторожит ОТСУТСТВИЕ дубля, а не его синхронность.
+"""
+import shutil
 import subprocess
 import sys
+from pathlib import Path
 
 import pytest
 
-from scripts.check_instruction_contract import MAX_INSTRUCTION_BYTES, check, sync
+SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_instruction_contract.py"
+REPO = Path(__file__).resolve().parents[1]
 
 
 @pytest.fixture
 def root(tmp_path):
-    kb = tmp_path / ".orchestra/kb"
+    shutil.copy(REPO / "AGENTS.md", tmp_path / "AGENTS.md")
+    kb = tmp_path / ".orchestra" / "kb"
     kb.mkdir(parents=True)
-    (kb / "README.md").write_text("- [runtime](runtime.md) — Runtime: запуск и ошибки\n")
-    (kb / "runtime.md").write_text("# Runtime\nDetails remain on demand.\n")
-    (tmp_path / "AGENTS.md").write_text("# Rules\nNever restart without authority.\n")
-    (tmp_path / "CLAUDE.md").write_text("old copy")
-    sync(tmp_path)
+    shutil.copy(REPO / ".orchestra" / "kb" / "README.md", kb / "README.md")
+    for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
+        if topic.name != "README.md":
+            shutil.copy(topic, kb / topic.name)
     return tmp_path
 
 
-def test_sync_mirrors_the_source_without_inlining_the_topic_index(root):
-    check(root)
-    source = (root / "AGENTS.md").read_bytes()
-    assert (root / "CLAUDE.md").read_bytes() == source
-    assert b"Never restart without authority." in source
-    # The topic list is injected by the platform (app.kb_index), so neither the topic
-    # description nor its body may appear in the committed rules.
-    assert "Runtime: запуск и ошибки" not in source.decode()
-    assert b"Details remain on demand" not in source
-    before = [(root / name).stat().st_mtime_ns for name in ("AGENTS.md", "CLAUDE.md")]
-    sync(root)
-    assert before == [(root / name).stat().st_mtime_ns for name in ("AGENTS.md", "CLAUDE.md")]
-
-
-def test_one_sided_edit_is_rejected_without_repair(root):
-    target = root / "CLAUDE.md"
-    target.write_bytes(target.read_bytes() + b"\nOne-sided rule")
-    before = target.read_bytes()
-    with pytest.raises(ValueError, match="differ"):
-        check(root)
-    assert target.read_bytes() == before
-
-
-def test_unindexed_topic_is_rejected_but_needs_no_root_edit(root):
-    kb = root / ".orchestra/kb"
-    (kb / "network.md").write_text("# Network")
-    with pytest.raises(ValueError, match="missing from README"):
-        check(root)
-    before = (root / "AGENTS.md").read_bytes()
-    index = kb / "README.md"
-    index.write_text(index.read_text() + "- [network](network.md) — Сеть: диагностика\n")
-    check(root)
-    assert (root / "AGENTS.md").read_bytes() == before
-
-
-def test_equal_utf8_bloat_is_rejected_and_sync_does_not_touch_other_copy(root):
-    source = root / "AGENTS.md"
-    source.write_text(source.read_text() + "я" * (MAX_INSTRUCTION_BYTES // 2))
-    before = (root / "CLAUDE.md").read_bytes()
-    with pytest.raises(ValueError, match="budget"):
-        sync(root)
-    assert (root / "CLAUDE.md").read_bytes() == before
-    (root / "CLAUDE.md").write_bytes(source.read_bytes())
-    with pytest.raises(ValueError, match="budget"):
-        check(root)
-
-
-@pytest.mark.parametrize("mutation", ["empty", "import", "broken_link", "duplicate", "description"])
-def test_invalid_sources_fail_before_writes(root, mutation):
-    source = root / "AGENTS.md"
-    index = root / ".orchestra/kb/README.md"
-    (root / "CLAUDE.md").write_text("stale mirror")
-    if mutation == "empty":
-        source.write_text("")
-    elif mutation == "import":
-        source.write_text(source.read_text() + "\nRead @archive.md now.\n")
-    elif mutation == "broken_link":
-        index.write_text(index.read_text().replace("(runtime.md)", "(missing.md)"))
-    elif mutation == "duplicate":
-        index.write_text(index.read_text() * 2)
-    else:
-        index.write_text("- [runtime](runtime.md) —    \n")
-    before = (source.read_bytes(), (root / "CLAUDE.md").read_bytes())
-    with pytest.raises(ValueError):
-        sync(root)
-    assert before == (source.read_bytes(), (root / "CLAUDE.md").read_bytes())
-
-
-def test_ci_command_fails_on_drift(root):
-    (root / "CLAUDE.md").write_text("different")
-    script = Path(__file__).parents[1] / "scripts/check_instruction_contract.py"
-    result = subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)
+def _run(root: Path):
+    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
+                          capture_output=True, text=True)
+
+
+def test_single_source_passes(root):
+    assert _run(root).returncode == 0
+
+
+def test_claude_md_coming_back_is_rejected(root):
+    """Дубль не «чинится синхронизацией» — он запрещён: агенту доезжают оба файла."""
+    (root / "CLAUDE.md").write_text((root / "AGENTS.md").read_text(), encoding="utf-8")
+
+    result = _run(root)
+
+    assert result.returncode == 1
+    assert "CLAUDE.md" in result.stderr
+
+
+def test_duplicate_is_rejected_even_as_a_symlink(root):
+    (root / "CLAUDE.md").symlink_to(root / "AGENTS.md")
+
+    assert _run(root).returncode == 1
+
+
+def test_oversized_rules_are_rejected(root):
+    body = (root / "AGENTS.md").read_text(encoding="utf-8")
+    (root / "AGENTS.md").write_text(body + "x" * 17_000, encoding="utf-8")
+
+    result = _run(root)
+
+    assert result.returncode == 1
+    assert "16 KiB" in result.stderr
+
+
+def test_unindexed_kb_topic_is_rejected(root):
+    (root / ".orchestra" / "kb" / "brand-new-topic.md").write_text("# тема", encoding="utf-8")
+
+    result = _run(root)
+
     assert result.returncode == 1
-    assert "differ" in result.stderr
+    assert "brand-new-topic" in result.stderr
+
+
+def test_root_import_is_rejected(root):
+    """Импорт в корне вернул бы нас к скрытому второму источнику правил."""
+    body = (root / "AGENTS.md").read_text(encoding="utf-8")
+    (root / "AGENTS.md").write_text(body + "\n@./extra-rules.md\n", encoding="utf-8")
+
+    assert _run(root).returncode == 1
diff --git a/tests/test_knowledge_instruction_source.py b/tests/test_knowledge_instruction_source.py
index b4f255d54..570200de6 100644
--- a/tests/test_knowledge_instruction_source.py
+++ b/tests/test_knowledge_instruction_source.py
@@ -1,28 +1,32 @@
 """Instruction ownership and lossless historical evidence, not prose style checks."""
 from pathlib import Path
 import hashlib
 import subprocess
 
 
 ROOT = Path(__file__).parents[1]
 
 
 def test_original_rules_are_preserved_byte_for_byte():
     archive = ROOT / ".orchestra/archive/instructions/2026-09-05-CLAUDE.md"
     # Frozen from 74692c2c before moving the file; works in shallow CI clones too.
     assert hashlib.sha256(subprocess.check_output(["git", "show", "9a1735f1695519a445f393802c2154bd37337e38:.orchestra/archive/instructions/2026-09-05-CLAUDE.md"], cwd=ROOT)).hexdigest() == (
         "298e291c1866285592ca6236a833840fea332c082094d42e4a558faf5c8c1cc7"
     )
 
 
 def test_both_clients_get_the_same_bounded_rules_and_current_topic_index():
+    """Один файл на оба CLI: Claude Code 2.1.263 читает AGENTS.md сам (проверено 19.09.2026),
+    Codex читал его всегда. Отдельная копия CLAUDE.md не синхронизируется, а запрещена —
+    агенту доезжают ОБА файла, и разошедшиеся копии дают два противоречащих набора правил."""
     from scripts.check_instruction_contract import check
-    subprocess.run(["git", "ls-files", "--error-unmatch", "AGENTS.md", "CLAUDE.md"], cwd=ROOT, check=True)
+    subprocess.run(["git", "ls-files", "--error-unmatch", "AGENTS.md"], cwd=ROOT, check=True)
+    assert not (ROOT / "CLAUDE.md").exists()
     check(ROOT)
 
 
 def test_historical_source_snapshot_remains_reachable():
     subprocess.run(['git', 'merge-base', '--is-ancestor', '9a1735f1695519a445f393802c2154bd37337e38', 'HEAD'], cwd=ROOT, check=True)
     for path in ['.orchestra/workers/frontend.md', '.orchestra/tasks/239/report.md',
                  '.orchestra/archive/knowledge-20260909/manifest.json']:
         assert subprocess.check_output(['git', 'show', '9a1735f1695519a445f393802c2154bd37337e38:'+path], cwd=ROOT)


## Later history of the touched files on main (after this commit)

220 later commits touch these paths; the first 40 (oldest first):
75a8fbb36 2026-09-19 Revert "#V-600: корневые правила — один AGENTS.md, дубль CLAUDE.md запрещён"
19ded26ad 2026-09-19 #V-601: CLAUDE.md — симлинк на AGENTS.md вместо копии
74331413a 2026-09-19 #V-602: харнес берёт ступень рассуждения из манифеста, регулярка удалена
902e86597 2026-09-19 #V-603: отказ привязки задачи объясняет причину, описание spawn_worker — правила
008c51eff 2026-09-20 #V-604: правила проекта читаются из AGENTS.md модом agents-md, CLAUDE.md рядом запрещён
2bd067d76 2026-09-20 #V-597: вернуть CLAUDE.md симлинком — мод работает только в CLI, наши воркеры и бот Кеши ходят через SDK
f6d969c1c 2026-09-20 V-602: update MCP descriptions and parallelize agent listing
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
7f291ae99 2026-09-21 V-606: #V-606: compact idle sessions before cache expiry
d607f5fc7 2026-09-21 V-607: #V-607: add mutation test gate for worker merges
2dcbfba99 2026-09-22 V-609: #V-609: persist provider cost baseline across restart
425b83eeb 2026-09-22 V-611: repair-подсказка LAYOUT_MISSING указывает на базовый чекаут, а не на worktree
bbfd3641c 2026-09-22 V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели
a6fe16bfc 2026-09-22 V-614: тень-гейт «DONE без прошедшей проверки после последней правки»
8941811c9 2026-09-22 V-610: rewrite third-party code in app/ with own implementation
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
f20796d3e 2026-09-23 Каталог моделей: Opus 5.5, GPT-6 Luna и Sol; opus → 5.5
0f973de21 2026-09-23 V-620: switch_worker_branch releases a worker left bound after merge(continue)
628ac2058 2026-09-23 Маршрут по умолчанию: luna → GPT-6 Luna, sol → GPT-6 Sol (Sol закрыт для агентов)
f4470decc 2026-09-23 Opus 5.5 на medium; общее правило «продолжай сам, останавливайся перед необратимым»
9c5e64087 2026-09-23 V-621: WIP #V-621: каталог проектов — файл на каждый scope вместо одного общего
6cfb55e08 2026-09-23 Отчёт о сжатии: контекст одного обращения вместо суммы за ход
b3aae161b 2026-09-24 V-627: allow scheduled precompact with background jobs
759b3be64 2026-09-24 V-628: collapse incoming Telegram topic messages
413144544 2026-09-24 fix: clear chat upload error on agent switch
80ef49b10 2026-09-24 V-630: #V-630: bound SSE graceful shutdown
6d7b57934 2026-09-24 V-624: #V-624: полный pytest доходит до сводки — страж рестарта больше не убивает pytest, shutdown рендерера не ждёт чужой цикл
4950d8ccb 2026-09-24 V-629: #V-629: preserve project layout data
63fd7ac22 2026-09-24 V-631: #V-631: merge taskless adhoc work against explicit task
7ae410f8d 2026-09-24 V-621: разбить общий каталог проектов на файлы по scope
3cf265e4c 2026-09-24 V-634: #V-634: миграция каталога без продвижения не коммитит; scope другой машины не ошибка раскладки
16ebb5e15 2026-09-24 merge_worker: вывод git декодируется с errors=replace — обрезанный diffstat с кириллицей ронял squash-мерж seedon в UNKNOWN
9fa965ca9 2026-09-24 V-635: worktree воркера в старой раскладке мигрирует при подъёме воркера (только чистое дерево)
7107a052d 2026-09-25 CHANGELOG: порог автокомпакта Claude 30%
bbf9a0d58 2026-09-25 Автокомпакт Codex по простою тоже только от 30% контекста (решение владельца)
001dea015 2026-09-25 V-638: офлайн-комплект поставки и установка без uv и сети
4cc2e45c1 2026-09-25 V-642: #V-642: сигнал тишины воркера родителю и метка stalled для доставки без старта хода
8c3e56038 2026-09-25 V-640: #V-640: квотный гейт не блокирует сжатие и платформенные ходы
baa28b793 2026-09-25 V-637: сценарии и драйвер стенда
b0ef26aa5 2026-09-25 История чата дозагружается страницами по 100 до начала, а не один раз

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 75a8fbb36 Revert "#V-600: корневые правила — один AGENTS.md, дубль CLAUDE.md запрещён"

diff --git a/AGENTS.md b/AGENTS.md
index b626e2f78..f1c7af14d 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1,11 +1,10 @@
 # Orchestra — правила работы
 
-Единственный источник правил проекта — этот версионируемый AGENTS.md; его читают оба CLI.
-CLAUDE.md в корне быть не должно: Claude Code подхватывает ОБА файла сразу, и разошедшиеся
-копии дают агенту два противоречащих набора правил (проверено 19.09.2026 на 2.1.263).
-Проверка контракта: python scripts/check_instruction_contract.py.
+Общий источник правил проекта — этот версионируемый AGENTS.md.
+CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
+После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
 Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
 а этот файл регулирует работу над самой Orchestra.
 
 ## Границы полномочий
 
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 0390cd196..7c64a5170 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -28,28 +28,10 @@
   его надо звать руками после заметных правок интерфейса. Старый браузерный набор
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
-### Removed
-- 🪞 **Зеркало `CLAUDE.md` убрано: корневые правила проекта живут в одном `AGENTS.md`**
-  (удалён `CLAUDE.md`; `scripts/check_instruction_contract.py` больше не умеет `--sync`, а
-  ЗАПРЕЩАЕТ появление дубля; `app/workspace.py` — `PROJECT_FILES` копирует в worktree и
-  `AGENTS.md`). Claude Code 2.1.263 читает `AGENTS.md` сам — проверено экспериментом: в пустом
-  каталоге с одним `AGENTS.md` агент назвал записанное в нём кодовое слово. Проверен и случай
-  двух файлов: CLI подхватывает ОБА сразу и сообщает о расхождении, то есть копия — не
-  «совместимость», а второй источник правды.
-  *Triggered case:* пока зеркало существовало, оно дважды разъезжалось с источником; в одном
-  из случаев `CLAUDE.md` был на 671 байт короче и не содержал правил владельца про маскирование
-  секретов и про Codex — Claude-агенты их просто не видели.
-  *Known tradeoff:* проекты, где в корне лежит только `CLAUDE.md` (например `University`),
-  продолжают работать через `sync_agents_md`, который копирует их правила в `AGENTS.md` для
-  Codex; этот путь не тронут.
-  *Reasoning:* пользовательский уровень остаётся на `~/.claude/CLAUDE.md` — глобальный
-  `~/.claude/AGENTS.md` CLI НЕ читает (проверено там же), поэтому дубля наверху нет: у нас
-  `~/.codex/AGENTS.md` симлинком указывает на тот же файл.
-
 ### Fixed
 - 🧯 **Один кривой вызов инструмента больше не убивает остаток сессии воркера**
   (`app/harness/loop.py` — `_sanitize_tool_args`, вызывается после диспетча раунда).
   Ассистентский месседж с `tool_calls` уезжает в КАЖДЫЙ следующий запрос, а строгий
   провайдер отвергает весь запрос, если аргументы хоть одного вызова — не строка-объект
diff --git a/CLAUDE.md b/CLAUDE.md
new file mode 100644
index 000000000..f1c7af14d
--- /dev/null
+++ b/CLAUDE.md
@@ -0,0 +1,98 @@
+# Orchestra — правила работы
+
+Общий источник правил проекта — этот версионируемый AGENTS.md.
+CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
+После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
+Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
+а этот файл регулирует работу над самой Orchestra.
+
+## Границы полномочий
+
+- Не добавляй в корневые инструкции отчёты, логи аварий, текущие проценты квот,
+  длинные примеры и разовые обходы. В корне остаются только ограничения, нужные
+  практически любой задаче. Исследовательские выводы — в KB, результаты — в tasks.
+  Новое постоянное правило требует согласования владельца; существующее уточняй
+  у его владельца, не дописывай ещё одну версию в конец файла.
+  Каждый корневой файл должен быть меньше 16 KiB. Не повышай этот предел ради
+  очередного дополнения и не подключай подробности через автоматические импорты.
+
+- Выполняй согласованную задачу в её границах. Исследование не разрешает реализацию,
+  а разовое «делай» не создаёт постоянного разрешения на другие работы.
+- Рестарт Orchestra инициирует только владелец. Самостоятельно не перезапускай,
+  не останавливай и не запускай Orchestra или telegram-bot-api, даже ради аварии.
+  Если Python-правки требуют рестарта, сообщи об этом одной строкой и жди команды.
+  После состоявшегося рестарта проверь cut_names и восстанови срезанных воркеров;
+  не принимай потерянное продолжение за отказ работника выполнять задачу.
+- Не выкатывай код и не выполняй git pull на VPS самостоятельно.
+  Не обращайся к чужим оркестраторам ради инфраструктурной координации.
+- Git remote origin — наш публичный. Другие remotes (включая enterprise и vadim)
+  не трогай. Сверяй git remote -v; не делай force-push и не теряй чужие коммиты.
+- Существующие чужие правки сохраняй. Работай в отдельной ветке/worktree;
+  мерж и запуск сервисов не следуют автоматически из успешных тестов.
+  Не убивай full-cycle воркера только из-за завершённого merge: он может ждать
+  следующего этапа. Условия завершения принадлежат модулю worker-lifecycle.
+- Перед закрытием воркера сохрани результат в main либо выводы и причину отказа
+  в хронике со ссылкой на исходную ветку. Одна preserve/*-метка не заменяет
+  извлечение знаний; полномочия на мерж и удаление проверяются отдельно.
+- **Маскирование секретов снято с пути ОТОБРАЖЕНИЯ и живёт только на границе публикации (решение владельца 06.09.2026, дословно: «журнал наш бд по дефолту должен быть гит игнор и утечки быть не должно, а на фронте мне не ломай секреты отображение»).** `db.add_log`, `live_broker.publish` и копии доставок пишут и отдают содержимое ДОСЛОВНО: `data/` целиком под `.gitignore` (`git check-ignore -v data/orchestra.db` → `.gitignore:11`), в индексе её нет, наружу журнал не публикуется. Маскирование там не предотвращало утечку, а портило рабочие данные — ссылка-приглашение MTProto-прокси приходила изуродованной, потому что её ПУБЛИЧНЫЙ параметр `secret=` попадал под общее правило. `app/secret_mask.py` и его тесты сохранены и остаются владельцем правила: применять их надо к тому, что уезжает В GIT и наружу, а не к тому, что владелец читает у себя. Остаточный риск назван явно: агент, копирующий содержимое лога в трекаемый артефакт, по-прежнему может протащить секрет — поэтому сырые выгрузки проверяются фильтром ПО ФОРМЕ секрета перед коммитом, и это единственное место, где маска обязательна.
+- Не публикуй пароли, OAuth-токены, ключи, содержимое .env или секреты из логов.
+  Секрет в собственном локальном хранилище сам по себе не доказывает утечку.
+  Не ротируй его и не останавливай работу только из-за существования; публичную
+  утечку сообщай немедленно. Сырые выгрузки проверяй перед коммитом.
+- Ноутбук владельца — рабочая машина: тяжёлые проверки последовательно,
+  nice=15 и MemoryMax=2G. /tmp может быть tmpfs; большие временные данные — /mnt/data.
+  Не убивай процессы по широкому pkill/сохранённому PGID; работай с точным владельцем.
+- Никаких новых платных API-вызовов вместо подписки без разрешения.
+  OpenRouter Harness допускает только точные разрешённые :free маршруты.
+
+## Текущие владельцы и рабочие пути
+
+- FastAPI + SSE, SQLite, внешние CLI и stdio MCP; главный код — app/.
+  Локальный dashboard обычно на 127.0.0.1:8888. Состояние конкретного сервиса
+  проверяй read-only; исторический рассказ не подтверждает, что он сейчас запущен.
+- Модели, effort и допуск: текущий pipeline, model-routing и app/quota_gate.py.
+  Не меняй политику по историческим процентам. Денежные суммы dashboard —
+  API-equivalent, не счёт владельцу; цена API не доказывает размер подписочной квоты.
+- Чат показывает свежий сетевой snapshot последних сообщений, затем SSE.
+  Не возвращай зеркало истории в IndexedDB или stale-while-revalidate для чата.
+- База знаний — .orchestra/kb/, доказательства задач — .orchestra/tasks/,
+  память — .orchestra/workers/, история — в Git по kb/history.md.
+  Raw-отчёт не становится текущим правилом без проверки и принятия вывода.
+
+## Найти нужное, не прочитать всё
+
+Оглавление тем и порядок поиска по нему платформа вставляет в системный промпт сама
+(`app/kb_index.py`, модуль knowledge). Здесь остаётся только обязанность автора:
+новую тему заводи файлом в .orchestra/kb/ И строкой с кратким описанием в
+.orchestra/kb/README.md — тема без этой строки до агентов не доедет.
+Запись и поиск: .orchestra/pipelines/default/prompts/modules/knowledge.md.
+
+## Реализация и проверка
+
+- Перед починкой симптома сверь текущий код. Историю изменения символа изучай
+  при регрессии, неясном происхождении поведения или риске отменить прежнее решение.
+  Не меняй соседние системы, не расширяй задачу и не добавляй новую зависимость
+  в обязательный промпт раньше, чем её реальный путь проверен.
+- Один владелец правила и состояния; данные из API, конфигов и текущего кода
+  важнее исторического замера. Индекс/проекция не заменяет канонический источник.
+- Тестируй поведение: отрицательное и разрешающее плечо, границы, конкурентность,
+  восстановление. Зелёный тест должен краснеть при возвращении дефекта.
+  Таймауты тестов ограничивают зависание, а не подменяют замер производительности.
+- Тесты не используют боевую БД, токены TG, NOTIFY_SOCKET живого сервиса и настоящие
+  CLI провайдеров без отдельной цели прогона. Копия живой SQLite — backup(), не cp.
+- CLI-окружение проверяется по месту импорта: запускай тесты через python -m pytest,
+  а не консольный pytest; в отчёте укажи абсолютный путь импортированного app-модуля.
+- Прежние опыты замеров — .orchestra/kb/evidence-methods.md. Разделяй до/после и шум;
+  не объявляй улучшение по размеру файла, числу тестов или имени модели.
+- Не выдавай код на диске за работающий Python в живом процессе.
+  JS/CSS могут загрузиться без рестарта; Python/CLI-конфиги имеют свой жизненный цикл.
+- Ошибки платформы фиксируй через report_bug, если инструмент доступен;
+  результаты своей задачи сохраняй в .orchestra/tasks/<id>/.
### 19ded26ad #V-601: CLAUDE.md — симлинк на AGENTS.md вместо копии

diff --git a/AGENTS.md b/AGENTS.md
index f1c7af14d..399e52958 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1,10 +1,11 @@
 # Orchestra — правила работы
 
-Общий источник правил проекта — этот версионируемый AGENTS.md.
-CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
-После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
+Единственный источник правил проекта — этот версионируемый AGENTS.md, его читает Codex.
+CLAUDE.md рядом — СИМЛИНК на него, а не копия: Claude Code читает только CLAUDE.md, а копия
+дважды разъезжалась и один раз оставила Claude-агентов без правил владельца.
+Проверка контракта: python scripts/check_instruction_contract.py.
 Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
 а этот файл регулирует работу над самой Orchestra.
 
 ## Границы полномочий
 
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7c64a5170..329060724 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -28,10 +28,25 @@
   его надо звать руками после заметных правок интерфейса. Старый браузерный набор
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
+### Changed
+- 🔗 **`CLAUDE.md` теперь симлинк на `AGENTS.md`, а не его копия** (`scripts/check_instruction_contract.py`
+  требует симлинк и отвергает копию; режим `--sync` удалён за ненадобностью). Claude Code читает
+  только `CLAUDE.md`: поддержка `AGENTS.md` заявлена в ченжлоге 2.1.277 как fallback «если нет
+  CLAUDE.md», но на 2.1.278 у нас не включается — проверено с отключёнными файловыми инструментами
+  и положительным контролем, в пустом каталоге с одним `AGENTS.md` агент отвечает «НЕТ», тот же файл
+  под именем `CLAUDE.md` читается. Симлинк — обход, который рекомендует сама официальная
+  документация Anthropic по памяти.
+  *Triggered case:* пока рядом лежали две копии, они дважды разъехались; в одном случае `CLAUDE.md`
+  был на 671 байт короче и не содержал правил владельца про маскирование секретов и про Codex.
+  *Reasoning:* копия требует синхронизации и молча устаревает, симлинк не может разойтись физически;
+  Codex продолжает читать `AGENTS.md`, Claude — `CLAUDE.md`, содержимое у них одно и то же.
+  *Known tradeoff:* проверка контракта теперь ЗАВИСИТ от файловой системы с симлинками; на носителе
+  без них корень придётся собирать иначе.
+
 ### Fixed
 - 🧯 **Один кривой вызов инструмента больше не убивает остаток сессии воркера**
   (`app/harness/loop.py` — `_sanitize_tool_args`, вызывается после диспетча раунда).
   Ассистентский месседж с `tool_calls` уезжает в КАЖДЫЙ следующий запрос, а строгий
   провайдер отвергает весь запрос, если аргументы хоть одного вызова — не строка-объект
diff --git a/CLAUDE.md b/CLAUDE.md
deleted file mode 100644
index f1c7af14d..000000000
--- a/CLAUDE.md
+++ /dev/null
@@ -1,98 +0,0 @@
-# Orchestra — правила работы
-
-Общий источник правил проекта — этот версионируемый AGENTS.md.
-CLAUDE.md — побайтно одинаковое зеркало для Claude, а не независимый источник.
-После правки AGENTS.md выполняй python scripts/check_instruction_contract.py --sync.
-Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
-а этот файл регулирует работу над самой Orchestra.
-
-## Границы полномочий
-
-- Не добавляй в корневые инструкции отчёты, логи аварий, текущие проценты квот,
-  длинные примеры и разовые обходы. В корне остаются только ограничения, нужные
-  практически любой задаче. Исследовательские выводы — в KB, результаты — в tasks.
-  Новое постоянное правило требует согласования владельца; существующее уточняй
-  у его владельца, не дописывай ещё одну версию в конец файла.
-  Каждый корневой файл должен быть меньше 16 KiB. Не повышай этот предел ради
-  очередного дополнения и не подключай подробности через автоматические импорты.
-
-- Выполняй согласованную задачу в её границах. Исследование не разрешает реализацию,
-  а разовое «делай» не создаёт постоянного разрешения на другие работы.
-- Рестарт Orchestra инициирует только владелец. Самостоятельно не перезапускай,
-  не останавливай и не запускай Orchestra или telegram-bot-api, даже ради аварии.
-  Если Python-правки требуют рестарта, сообщи об этом одной строкой и жди команды.
-  После состоявшегося рестарта проверь cut_names и восстанови срезанных воркеров;
-  не принимай потерянное продолжение за отказ работника выполнять задачу.
-- Не выкатывай код и не выполняй git pull на VPS самостоятельно.
-  Не обращайся к чужим оркестраторам ради инфраструктурной координации.
-- Git remote origin — наш публичный. Другие remotes (включая enterprise и vadim)
-  не трогай. Сверяй git remote -v; не делай force-push и не теряй чужие коммиты.
-- Существующие чужие правки сохраняй. Работай в отдельной ветке/worktree;
-  мерж и запуск сервисов не следуют автоматически из успешных тестов.
-  Не убивай full-cycle воркера только из-за завершённого merge: он может ждать
-  следующего этапа. Условия завершения принадлежат модулю worker-lifecycle.
-- Перед закрытием воркера сохрани результат в main либо выводы и причину отказа
-  в хронике со ссылкой на исходную ветку. Одна preserve/*-метка не заменяет
-  извлечение знаний; полномочия на мерж и удаление проверяются отдельно.
-- **Маскирование секретов снято с пути ОТОБРАЖЕНИЯ и живёт только на границе публикации (решение владельца 06.09.2026, дословно: «журнал наш бд по дефолту должен быть гит игнор и утечки быть не должно, а на фронте мне не ломай секреты отображение»).** `db.add_log`, `live_broker.publish` и копии доставок пишут и отдают содержимое ДОСЛОВНО: `data/` целиком под `.gitignore` (`git check-ignore -v data/orchestra.db` → `.gitignore:11`), в индексе её нет, наружу журнал не публикуется. Маскирование там не предотвращало утечку, а портило рабочие данные — ссылка-приглашение MTProto-прокси приходила изуродованной, потому что её ПУБЛИЧНЫЙ параметр `secret=` попадал под общее правило. `app/secret_mask.py` и его тесты сохранены и остаются владельцем правила: применять их надо к тому, что уезжает В GIT и наружу, а не к тому, что владелец читает у себя. Остаточный риск назван явно: агент, копирующий содержимое лога в трекаемый артефакт, по-прежнему может протащить секрет — поэтому сырые выгрузки проверяются фильтром ПО ФОРМЕ секрета перед коммитом, и это единственное место, где маска обязательна.
-- Не публикуй пароли, OAuth-токены, ключи, содержимое .env или секреты из логов.
-  Секрет в собственном локальном хранилище сам по себе не доказывает утечку.
-  Не ротируй его и не останавливай работу только из-за существования; публичную
-  утечку сообщай немедленно. Сырые выгрузки проверяй перед коммитом.
-- Ноутбук владельца — рабочая машина: тяжёлые проверки последовательно,
-  nice=15 и MemoryMax=2G. /tmp может быть tmpfs; большие временные данные — /mnt/data.
-  Не убивай процессы по широкому pkill/сохранённому PGID; работай с точным владельцем.
-- Никаких новых платных API-вызовов вместо подписки без разрешения.
-  OpenRouter Harness допускает только точные разрешённые :free маршруты.
-
-## Текущие владельцы и рабочие пути
-
-- FastAPI + SSE, SQLite, внешние CLI и stdio MCP; главный код — app/.
-  Локальный dashboard обычно на 127.0.0.1:8888. Состояние конкретного сервиса
-  проверяй read-only; исторический рассказ не подтверждает, что он сейчас запущен.
-- Модели, effort и допуск: текущий pipeline, model-routing и app/quota_gate.py.
-  Не меняй политику по историческим процентам. Денежные суммы dashboard —
-  API-equivalent, не счёт владельцу; цена API не доказывает размер подписочной квоты.
-- Чат показывает свежий сетевой snapshot последних сообщений, затем SSE.
-  Не возвращай зеркало истории в IndexedDB или stale-while-revalidate для чата.
-- База знаний — .orchestra/kb/, доказательства задач — .orchestra/tasks/,
-  память — .orchestra/workers/, история — в Git по kb/history.md.
-  Raw-отчёт не становится текущим правилом без проверки и принятия вывода.
-
-## Найти нужное, не прочитать всё
-
-Оглавление тем и порядок поиска по нему платформа вставляет в системный промпт сама
-(`app/kb_index.py`, модуль knowledge). Здесь остаётся только обязанность автора:
-новую тему заводи файлом в .orchestra/kb/ И строкой с кратким описанием в
-.orchestra/kb/README.md — тема без этой строки до агентов не доедет.
-Запись и поиск: .orchestra/pipelines/default/prompts/modules/knowledge.md.
-
-## Реализация и проверка
-
-- Перед починкой симптома сверь текущий код. Историю изменения символа изучай
-  при регрессии, неясном происхождении поведения или риске отменить прежнее решение.
-  Не меняй соседние системы, не расширяй задачу и не добавляй новую зависимость
-  в обязательный промпт раньше, чем её реальный путь проверен.
-- Один владелец правила и состояния; данные из API, конфигов и текущего кода
-  важнее исторического замера. Индекс/проекция не заменяет канонический источник.
-- Тестируй поведение: отрицательное и разрешающее плечо, границы, конкурентность,
-  восстановление. Зелёный тест должен краснеть при возвращении дефекта.
-  Таймауты тестов ограничивают зависание, а не подменяют замер производительности.
-- Тесты не используют боевую БД, токены TG, NOTIFY_SOCKET живого сервиса и настоящие
-  CLI провайдеров без отдельной цели прогона. Копия живой SQLite — backup(), не cp.
-- CLI-окружение проверяется по месту импорта: запускай тесты через python -m pytest,
-  а не консольный pytest; в отчёте укажи абсолютный путь импортированного app-модуля.
-- Прежние опыты замеров — .orchestra/kb/evidence-methods.md. Разделяй до/после и шум;
-  не объявляй улучшение по размеру файла, числу тестов или имени модели.
-- Не выдавай код на диске за работающий Python в живом процессе.
-  JS/CSS могут загрузиться без рестарта; Python/CLI-конфиги имеют свой жизненный цикл.
-- Ошибки платформы фиксируй через report_bug, если инструмент доступен;
-  результаты своей задачи сохраняй в .orchestra/tasks/<id>/.
-- До закрытия работы: проверь diff, нужные тесты, отсутствие секретов и потерь
-  чужих правок. Сообщи результат, фактическую проверку и оставшийся риск.
-
### 74331413a #V-602: харнес берёт ступень рассуждения из манифеста, регулярка удалена

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 329060724..1bcbdf42d 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -28,10 +28,27 @@
   его надо звать руками после заметных правок интерфейса. Старый браузерный набор
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
+### Changed
+- 🎚 **Ступень рассуждения харнеса берётся из манифеста, а не угадывается по тексту сообщения**
+  (`app/backend_harness.py` — удалены `classify_effort`, `_HIGH_EFFORT_RE` и список тривиальных
+  фраз, 38 строк; `app/runtime_registry.py` передаёт `context.effort`; в карту
+  `effort_policy` добавлен ключ `harness: medium`). У Claude, Codex и Grok ступень всегда
+  приходила из карты `модель → effort` в `pipeline.yaml` с обоснованием замерами (#208, #373);
+  харнес был единственным местом, где она выводилась поиском слов вроде «почини» или «why».
+  *Triggered case:* на 12 подряд идущих реальных сообщениях пользователя эвристика вернула
+  `medium` одиннадцать раз — то есть решения не принимала, а её `high` срабатывал от слова
+  «почему» в любом вопросе.
+  *Known tradeoff:* `harness: medium` не измерен ни на одном бесплатном маршруте — это середина
+  и заодно выключатель гейта планирования (`todo_write` включается только на `high`). Появится
+  замер по конкретному маршруту — добавляется строка с его id, карта разрешает id раньше рантайма.
+  *Reasoning:* менять ступень посреди разговора нельзя — платформа при расхождении пересобирает
+  сессию (`app/session.py`, перечитывание манифеста), и это холодный старт с потерей кеша;
+  манифестное значение задаётся на спавне, то есть там, где старт и так холодный.
+
 ### Changed
 - 🔗 **`CLAUDE.md` теперь симлинк на `AGENTS.md`, а не его копия** (`scripts/check_instruction_contract.py`
   требует симлинк и отвергает копию; режим `--sync` удалён за ненадобностью). Claude Code читает
   только `CLAUDE.md`: поддержка `AGENTS.md` заявлена в ченжлоге 2.1.277 как fallback «если нет
   CLAUDE.md», но на 2.1.278 у нас не включается — проверено с отключёнными файловыми инструментами
### 902e86597 #V-603: отказ привязки задачи объясняет причину, описание spawn_worker — правила

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 1bcbdf42d..7017df002 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -28,10 +28,25 @@
   его надо звать руками после заметных правок интерфейса. Старый браузерный набор
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
+### Fixed
+- 🚧 **Отказ привязки задачи называет причину и действие вместо внутренней механики**
+  (`app/db.py` — `_task_binding_refusal`; описание `spawn_worker` в `app/mcp_stdio.py`).
+  Было: `task #27 binding compare-and-swap failed` — одно условие, две разные причины, ни
+  подсказки. Стало: «задача #27 уже закреплена за воркером 'X'; одна задача = один воркер,
+  для второго исполнителя заведите отдельную» либо «строка задачи изменилась во время
+  привязки, перечитайте и повторите». В описание тула добавлено, что `task_id` — номер
+  СУЩЕСТВУЮЩЕЙ задачи из ответа `task_create` и что одна задача держится одним воркером.
+  *Triggered case:* seedon-orchestrator получил два отказа подряд — придумал номер задачи
+  под имя каталога на диске, затем посадил второго воркера на занятую задачу. Оба правила
+  он узнал отказами, потому что в описании тула их не было.
+  *Reasoning:* неудачный спавн уносит весь текст задания (~1 500 токенов) и вместе с
+  ошибкой остаётся в истории сессии, пересылаясь в каждом следующем ходе, — непонятная
+  ошибка оплачивается многократно и провоцирует повтор тем же способом.
+
 ### Changed
 - 🎚 **Ступень рассуждения харнеса берётся из манифеста, а не угадывается по тексту сообщения**
   (`app/backend_harness.py` — удалены `classify_effort`, `_HIGH_EFFORT_RE` и список тривиальных
   фраз, 38 строк; `app/runtime_registry.py` передаёт `context.effort`; в карту
   `effort_policy` добавлен ключ `harness: medium`). У Claude, Codex и Grok ступень всегда
### 008c51eff #V-604: правила проекта читаются из AGENTS.md модом agents-md, CLAUDE.md рядом запрещён

diff --git a/AGENTS.md b/AGENTS.md
index 399e52958..0b062e1bf 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1,10 +1,11 @@
 # Orchestra — правила работы
 
-Единственный источник правил проекта — этот версионируемый AGENTS.md, его читает Codex.
-CLAUDE.md рядом — СИМЛИНК на него, а не копия: Claude Code читает только CLAUDE.md, а копия
-дважды разъезжалась и один раз оставила Claude-агентов без правил владельца.
+Единственный источник правил проекта — этот версионируемый AGENTS.md; CLAUDE.md рядом
+больше нет и заводить его нельзя, даже симлинком. Codex читает AGENTS.md сам, Claude Code —
+через мод agents-md (см. .orchestra/kb/agent-control.md: мод ставится один раз на машину).
+Копия рядом дважды разъезжалась и один раз оставила Claude-агентов без правил владельца.
 Проверка контракта: python scripts/check_instruction_contract.py.
 Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
 а этот файл регулирует работу над самой Orchestra.
 
 ## Границы полномочий
diff --git a/CLAUDE.md b/CLAUDE.md
deleted file mode 120000
index 47dc3e3d8..000000000
--- a/CLAUDE.md
+++ /dev/null
@@ -1 +0,0 @@
-AGENTS.md
\ No newline at end of file
diff --git a/scripts/check_instruction_contract.py b/scripts/check_instruction_contract.py
index 3857b37ba..d920d3209 100644
--- a/scripts/check_instruction_contract.py
+++ b/scripts/check_instruction_contract.py
@@ -1,6 +1,6 @@
-"""Check the shared root rules: one file, a symlink beside it, budget and KB index."""
+"""Check the shared root rules: ONE file, nothing beside it, budget and KB index."""
 import argparse
 import os
 from pathlib import Path
 import re
 import sys
@@ -11,15 +11,15 @@ if str(_REPO_ROOT) not in sys.path:
 
 from app.kb_index import kb_topic_files, kb_topic_index
 
 MAX_INSTRUCTION_BYTES = 16 * 1024
 SOURCE = "AGENTS.md"
-# `CLAUDE.md` — СИМЛИНК на источник, а не копия. Claude Code читает только `CLAUDE.md`
-# (поддержка `AGENTS.md` заявлена с 2.1.277, но на 2.1.278 у нас не включается), Codex
-# читает только `AGENTS.md`. Копия дважды разъезжалась с источником, и один раз
-# Claude-агенты не видели правил владельца; симлинк разойтись не может физически.
-LINK = "CLAUDE.md"
+# Второго корневого файла правил быть не должно ни в каком виде. Codex читает `AGENTS.md`
+# сам; Claude Code — модом `agents-md` (включён глобально на машине). Пока рядом лежала
+# копия, она дважды разъехалась с источником, и один раз Claude-агенты работали на
+# устаревших правилах владельца, ничего об этом не сообщив.
+FORBIDDEN = "CLAUDE.md"
 
 
 def check_kb_index(root: Path) -> None:
     """Every topic file must be listed once, with a description, inside ``kb/``.
 
@@ -47,18 +47,15 @@ def _validate(body: bytes, name: str) -> None:
         raise ValueError(f"{name}: root imports are not allowed; use on-demand links")
 
 
 def check(root: Path) -> None:
     _validate(_read(root / SOURCE), SOURCE)
-    link = root / LINK
-    if not link.is_symlink():
+    beside = root / FORBIDDEN
+    if beside.is_symlink() or beside.exists():
         raise ValueError(
-            f"{LINK} must be a symlink to {SOURCE}, not a copy: a copy drifts and then one "
-            f"client silently runs on stale rules")
-    target = os.readlink(link)
-    if target != SOURCE:
-        raise ValueError(f"{LINK} points at {target!r}, expected {SOURCE!r}")
+            f"{FORBIDDEN} must not exist beside {SOURCE}: a second root rules file is a second "
+            f"source of truth, and Claude Code reads {SOURCE} through the agents-md mod")
     check_kb_index(root)
 
 
 def main() -> int:
     parser = argparse.ArgumentParser(description=__doc__)
@@ -66,11 +63,11 @@ def main() -> int:
     args = parser.parse_args()
     try:
         check(args.root)
     except (OSError, ValueError) as error:
         parser.exit(1, f"Instruction contract: {error}\n")
-    print(f"Instruction contract OK: {SOURCE} below 16 KiB, {LINK} is a symlink to it")
+    print(f"Instruction contract OK: {SOURCE} below 16 KiB, no {FORBIDDEN} beside it")
     return 0
 
 
 if __name__ == "__main__":
     raise SystemExit(main())
diff --git a/tests/test_instruction_contract.py b/tests/test_instruction_contract.py
index 6bbfc8700..a9c2d1246 100644
--- a/tests/test_instruction_contract.py
+++ b/tests/test_instruction_contract.py
@@ -1,12 +1,12 @@
-"""Контракт корневых правил: один файл, симлинк рядом, бюджет и полное оглавление KB.
+"""Контракт корневых правил: ровно один корневой файл, бюджет и полное оглавление KB.
 
-Claude Code читает только `CLAUDE.md` (поддержка `AGENTS.md` заявлена с 2.1.277, но на
-2.1.278 у нас не включается — проверено с отключёнными файловыми инструментами и
-положительным контролем). Codex читает только `AGENTS.md`. Пока рядом лежали две КОПИИ,
-они дважды разъехались, и один раз Claude-агенты не видели правил владельца. Симлинк
-разойтись не может физически — тест сторожит именно его, а не равенство байтов.
+Codex читает `AGENTS.md` сам, Claude Code — модом `agents-md`, включённым на машине
+(`~/.claude/mods`, `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`); проверено прогоном с
+отключёнными файловыми инструментами и положительным контролем. Пока рядом лежал второй
+корневой файл, он дважды разъехался с источником, и один раз Claude-агенты работали на
+устаревших правилах владельца. Тест сторожит отсутствие второго файла, а не равенство байтов.
 """
 import os
 import shutil
 import subprocess
 import sys
@@ -19,11 +19,10 @@ REPO = Path(__file__).resolve().parents[1]
 
 
 @pytest.fixture
 def root(tmp_path):
     shutil.copy(REPO / "AGENTS.md", tmp_path / "AGENTS.md")
-    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
     kb = tmp_path / ".orchestra" / "kb"
     kb.mkdir(parents=True)
     for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
         shutil.copy(topic, kb / topic.name)
     return tmp_path
@@ -32,42 +31,36 @@ def root(tmp_path):
 def _run(root: Path):
     return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                           capture_output=True, text=True)
 
 
-def test_symlink_beside_the_source_passes(root):
+def test_single_root_file_passes(root):
     assert _run(root).returncode == 0
 
 
-def test_copy_instead_of_symlink_is_rejected(root):
+def test_copy_beside_the_source_is_rejected(root):
     """Копия — это второй источник правды: он разъедется, и никто не заметит."""
-    link = root / "CLAUDE.md"
-    link.unlink()
-    link.write_text((root / "AGENTS.md").read_text(encoding="utf-8"), encoding="utf-8")
### 2bd067d76 #V-597: вернуть CLAUDE.md симлинком — мод работает только в CLI, наши воркеры и бот Кеши ходят через SDK

diff --git a/AGENTS.md b/AGENTS.md
index 0b062e1bf..5fccc9e09 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1,11 +1,11 @@
 # Orchestra — правила работы
 
-Единственный источник правил проекта — этот версионируемый AGENTS.md; CLAUDE.md рядом
-больше нет и заводить его нельзя, даже симлинком. Codex читает AGENTS.md сам, Claude Code —
-через мод agents-md (см. .orchestra/kb/agent-control.md: мод ставится один раз на машину).
-Копия рядом дважды разъезжалась и один раз оставила Claude-агентов без правил владельца.
+Единственный источник правил проекта — этот версионируемый AGENTS.md, его читает Codex.
+CLAUDE.md рядом — СИМЛИНК на него, а не копия, и убирать его нельзя: мод agents-md научил
+читать AGENTS.md только CLI, а наши Claude-сессии идут через Agent SDK, который грузит
+ровно CLAUDE.md (проверено 20.09.2026; подробности — .orchestra/kb/agent-control.md).
 Проверка контракта: python scripts/check_instruction_contract.py.
 Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
 а этот файл регулирует работу над самой Orchestra.
 
 ## Границы полномочий
diff --git a/CLAUDE.md b/CLAUDE.md
new file mode 120000
index 000000000..47dc3e3d8
--- /dev/null
+++ b/CLAUDE.md
@@ -0,0 +1 @@
+AGENTS.md
\ No newline at end of file
diff --git a/scripts/check_instruction_contract.py b/scripts/check_instruction_contract.py
index d920d3209..383104cc6 100644
--- a/scripts/check_instruction_contract.py
+++ b/scripts/check_instruction_contract.py
@@ -1,6 +1,6 @@
-"""Check the shared root rules: ONE file, nothing beside it, budget and KB index."""
+"""Check the shared root rules: one file, a symlink beside it, budget and KB index."""
 import argparse
 import os
 from pathlib import Path
 import re
 import sys
@@ -11,15 +11,17 @@ if str(_REPO_ROOT) not in sys.path:
 
 from app.kb_index import kb_topic_files, kb_topic_index
 
 MAX_INSTRUCTION_BYTES = 16 * 1024
 SOURCE = "AGENTS.md"
-# Второго корневого файла правил быть не должно ни в каком виде. Codex читает `AGENTS.md`
-# сам; Claude Code — модом `agents-md` (включён глобально на машине). Пока рядом лежала
-# копия, она дважды разъехалась с источником, и один раз Claude-агенты работали на
-# устаревших правилах владельца, ничего об этом не сообщив.
-FORBIDDEN = "CLAUDE.md"
+# `CLAUDE.md` — СИМЛИНК на источник, а не копия, и убирать его нельзя. Мод `agents-md`
+# (20.09.2026) научил читать `AGENTS.md` только CLI Claude Code; НАШИ сессии идут через
+# Agent SDK — и воркеры Orchestra (`app/backend_claude.py`), и бот Кеши, — а SDK грузит
+# ровно `CLAUDE.md` и мод не подхватывает ни через `setting_sources`, ни через `plugins`
+# (проверено прогоном 20.09). Без симлинка Claude-воркер молча теряет правила проекта:
+# ровно это случилось дважды — 19.09 (#V-600, откачено) и 20.09.
+LINK = "CLAUDE.md"
 
 
 def check_kb_index(root: Path) -> None:
     """Every topic file must be listed once, with a description, inside ``kb/``.
 
@@ -47,15 +49,18 @@ def _validate(body: bytes, name: str) -> None:
         raise ValueError(f"{name}: root imports are not allowed; use on-demand links")
 
 
 def check(root: Path) -> None:
     _validate(_read(root / SOURCE), SOURCE)
-    beside = root / FORBIDDEN
-    if beside.is_symlink() or beside.exists():
+    link = root / LINK
+    if not link.is_symlink():
         raise ValueError(
-            f"{FORBIDDEN} must not exist beside {SOURCE}: a second root rules file is a second "
-            f"source of truth, and Claude Code reads {SOURCE} through the agents-md mod")
+            f"{LINK} must be a symlink to {SOURCE}, not a copy: a copy drifts and then one "
+            f"client silently runs on stale rules")
+    target = os.readlink(link)
+    if target != SOURCE:
+        raise ValueError(f"{LINK} points at {target!r}, expected {SOURCE!r}")
     check_kb_index(root)
 
 
 def main() -> int:
     parser = argparse.ArgumentParser(description=__doc__)
@@ -63,11 +68,11 @@ def main() -> int:
     args = parser.parse_args()
     try:
         check(args.root)
     except (OSError, ValueError) as error:
         parser.exit(1, f"Instruction contract: {error}\n")
-    print(f"Instruction contract OK: {SOURCE} below 16 KiB, no {FORBIDDEN} beside it")
+    print(f"Instruction contract OK: {SOURCE} below 16 KiB, {LINK} is a symlink to it")
     return 0
 
 
 if __name__ == "__main__":
     raise SystemExit(main())
diff --git a/tests/test_instruction_contract.py b/tests/test_instruction_contract.py
index a9c2d1246..053b1bbe9 100644
--- a/tests/test_instruction_contract.py
+++ b/tests/test_instruction_contract.py
@@ -1,12 +1,13 @@
-"""Контракт корневых правил: ровно один корневой файл, бюджет и полное оглавление KB.
-
-Codex читает `AGENTS.md` сам, Claude Code — модом `agents-md`, включённым на машине
-(`~/.claude/mods`, `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`); проверено прогоном с
-отключёнными файловыми инструментами и положительным контролем. Пока рядом лежал второй
-корневой файл, он дважды разъехался с источником, и один раз Claude-агенты работали на
-устаревших правилах владельца. Тест сторожит отсутствие второго файла, а не равенство байтов.
+"""Контракт корневых правил: один файл, симлинк рядом, бюджет и полное оглавление KB.
+
+Claude Code CLI с модом `agents-md` читает `AGENTS.md` сам, но наши Claude-сессии идут не
+через CLI, а через Agent SDK (воркеры Orchestra и бот Кеши), и SDK грузит только `CLAUDE.md`:
+ни `setting_sources`, ни `plugins` мод туда не приносят (прогон 20.09.2026). Codex читает
+только `AGENTS.md`. Пока рядом лежали две КОПИИ, они дважды разъехались, и один раз
+Claude-агенты не видели правил владельца. Симлинк разойтись не может физически — тест
+сторожит именно его, а не равенство байтов.
 """
 import os
 import shutil
 import subprocess
 import sys
@@ -19,10 +20,11 @@ REPO = Path(__file__).resolve().parents[1]
 
 
 @pytest.fixture
 def root(tmp_path):
     shutil.copy(REPO / "AGENTS.md", tmp_path / "AGENTS.md")
+    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
     kb = tmp_path / ".orchestra" / "kb"
     kb.mkdir(parents=True)
     for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
         shutil.copy(topic, kb / topic.name)
     return tmp_path
@@ -31,36 +33,42 @@ def root(tmp_path):
 def _run(root: Path):
     return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                           capture_output=True, text=True)
 
 
-def test_single_root_file_passes(root):
+def test_symlink_beside_the_source_passes(root):
     assert _run(root).returncode == 0
 
 
-def test_copy_beside_the_source_is_rejected(root):
### f6d969c1c V-602: update MCP descriptions and parallelize agent listing

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7017df002..738202e2d 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -29,10 +29,23 @@
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
 ### Fixed
+- 🧭 **Описания MCP-инструментов приведены в соответствие с действующим контрактом**
+  (`app/mcp_stdio.py`: `spawn_worker`, `send_message`, `send_file`, `send_files`,
+  `send_chart`, `notify_user`, `merge_worker`, `report_bug`, `set_worker_owned_dirs`,
+  `bg_create`). Восстановлены в компактном виде recovery-пути, лимиты, запреты и
+  условия применения; у `set_worker_owned_dirs` убран ложный запрет пересечения
+  областей: он вводил в заблуждение, поскольку пересечение допустимо, а отказ бывает
+  только для running/waiting воркера, при атомарном обновлении dirs и prompt.
+  `list_agents` теперь запускает независимые чтения сессий, задач и иконок конкурентно,
+  сохраняя прежнее форматирование и необязательность задач/иконок.
+  *Triggered case:* описание ownership советовало убить живого воркера при пересечении,
+  хотя `validate_owned_dirs_transition` и миграционный тест закрепляют допустимость
+  пересекающихся рабочих областей.
+
 - 🚧 **Отказ привязки задачи называет причину и действие вместо внутренней механики**
   (`app/db.py` — `_task_binding_refusal`; описание `spawn_worker` в `app/mcp_stdio.py`).
   Было: `task #27 binding compare-and-swap failed` — одно условие, две разные причины, ни
   подсказки. Стало: «задача #27 уже закреплена за воркером 'X'; одна задача = один воркер,
   для второго исполнителя заведите отдельную» либо «строка задачи изменилась во время
### 4bd1a5365 V-603: clarify worker refusals and background receipts

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 738202e2d..ec3f06b4b 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -29,10 +29,16 @@
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
 ### Fixed
+- 🧭 **Отказы операций над воркером различают область и отсутствие имени** (`app/routes/sessions.py` — `compact`, `session-history`, `rollback-session`, `restart-cli`, `clear-session`, `change-model`). Вместо голого `not found` ответ сообщает, что воркер с таким именем живёт в другой области и называет только её, либо что имени нет нигде и нужно проверить `list_agents`; статусы и успешные пути не изменены.
+  *Triggered case:* `change_worker_model("globe-astra", "luna")` из `/home/kesha/orchestra` скрывал существование сессии в `/home/kesha/projects/comfy-image-pipeline`, и вызывающий тратил ход на догадки.
+
+- 🧾 **Квитанция `bg_create` сразу содержит эффективную постановку задания** (`app/bg_jobs.py`, `app/mcp_stdio.py`). В ответ добавлены вычисленный конфиг, адресат, эффективный timeout, срок действия, trigger и текущее состояние; второй вызов `bg_list` для этих полей больше не нужен.
+  *Triggered case:* агенты последовательно создавали джобу и тут же вызывали `bg_list`, чтобы увидеть значения, подставленные сервером.
+
 - 🧭 **Описания MCP-инструментов приведены в соответствие с действующим контрактом**
   (`app/mcp_stdio.py`: `spawn_worker`, `send_message`, `send_file`, `send_files`,
   `send_chart`, `notify_user`, `merge_worker`, `report_bug`, `set_worker_owned_dirs`,
   `bg_create`). Восстановлены в компактном виде recovery-пути, лимиты, запреты и
   условия применения; у `set_worker_owned_dirs` убран ложный запрет пересечения