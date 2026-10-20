# Orchestra TODO

Только актуальные дефекты и пункты, где требуется решение владельца. Полная таблица по всем исходным пунктам: [.orchestra/tasks/V-698/triage.md](.orchestra/tasks/V-698/triage.md). Источник исходных номеров — `TODO.md` в `main` SHA `71a008fe`.

## CI и dashboard
- Перед следующим перезапуском сверить loaded unit Orchestra с файлом на диске: `systemctl show` сообщил `TimeoutStartUSec=15min`, а `systemctl cat` предупредил, что загруженная версия устарела; фрагмент на диске содержит другие `ExecStart`/`TimeoutStartSec` (read-only проверка V-779, 08.10.2026). Решить, нужен ли `daemon-reload`, только вместе с владельцем запуска.
- Разобрать непадающее предупреждение `BaseSubprocessTransport.__del__: RuntimeError: Event loop is closed` после pytest и определить владельца очистки subprocess transports. Оно появилось после `tests/test_tg_bridge.py::TestTurnFoldStream::test_progress_edit_is_throttled_and_skips_identical_text` в проверке V-753 и независимо возникало в полном наборе на main и ветке в V-701; отчёты: `.orchestra/tasks/V-753/tests.log`, `.orchestra/tasks/V-701/report.md`.
- Обновить actions/checkout@v4 и setup-uv@v4: их action.yml ещё указывает Node 20. — OPEN-DEFECT, [T001](.orchestra/tasks/V-698/triage.md#t001). Доказательство: `evidence/node20_runtime_probe.txt; evidence/node20_deprecation.txt; .github/workflows/ci.yml:36,39`.
- Подпись полосы гейта квот не переводится: в английском интерфейсе пилюля гейта чит… — OPEN-DEFECT, [T002](.orchestra/tasks/V-698/triage.md#t002). Доказательство: `app/quota_gate.py:272-280`.
- Даты и деньги в английском интерфейсе форматируются по-русски: «вт, 6 окт., 19:15»… — OPEN-DEFECT, [T003](.orchestra/tasks/V-698/triage.md#t003). Доказательство: `app/static/js/analytics.js:652-663; app/static/js/usage.js:46`.
- test_i18n_dashboard::test_dictionary_reaches_marked_attributes шаткий в полном про… — OPEN-DEFECT, [T054](.orchestra/tasks/V-698/triage.md#t054). Доказательство: `evidence/test_i18n_marked_attributes.txt — 1 passed alone; ordering interaction remains untested`.
- tests/test_frontend.py — OPEN-DEFECT, [T114](.orchestra/tasks/V-698/triage.md#t114). Доказательство: `tests/test_frontend.py: (assertion named at 71a008fe:TODO.md:L162)`.
- Панель «Context» справа застывает на значении момента выбора агента — OPEN-DEFECT, [T115](.orchestra/tasks/V-698/triage.md#t115). Доказательство: `app/static/js/app.js:2603,2862-2918,3216`.

## Запуск и layout
- На ноутбуке при последнем рестарте bootstrap не смог создать настроенный `WORKSPACE_DIR=/workspace/project` (ошибка permission denied) и пропустил его, продолжив запуск с существующим orchestrator; сервис стал active, HTTP 200, TG bridge ready. Проверить, кому принадлежит создание этого каталога и влияет ли отказ на spawn новых laptop agents. Увидено 19.10.2026, root cause не исследован.
- `scripts/sparse_convert.py` падает `FileNotFoundError` (`app/workspace.py` `convert_worktree_to_sparse`, `_git_cmd` с cwd) на worktree, который исчез между списком и проверкой (wf-* у dynamic_workflow): весь прогон обрывается вместо `refused` по этой копии. Замечено 17.10.
- Главный процесс Orchestra 17.10 трижды за 26 минут убит глобальным OOM (07:20, 07:35, 07:46 UTC; `oom_score_adj 800`, пик юнита 14 ГБ + 12 ГБ swap): это и были утренние «рестарты», а не зависший shutdown. Найти, что раздуло память юнита. — [V-919](.orchestra/tasks/V-919/report.md)
- Уточнить написание scope в task-management: текст называет `.orchestra/projects.yaml` Orchestra единственным каталогом, но рабочий код валидирует каталог своего project scope. — [V-972 C01](.orchestra/tasks/V-972/report.md)
- Уточнить `update_worker_prompt`: tool description говорит custom prompt, тогда как вызов заменяет полное текущее тело и сбрасывает prompt overlay. Передать вызывающим, что это replacement, чтобы короткое обновление не стирало роль и базовые ограничения. — [V-972 C02](.orchestra/tasks/V-972/report.md)
- Согласовать направление для one-shot batch между `dynamic_workflow` и подсказкой `open_fan`, которая советует собственный `wf_run.py` для любых новых параллельных задач. — [V-972 C08](.orchestra/tasks/V-972/report.md)
- Исправить ссылки в html-artifacts: scaffold физически лежит в `references/animation.md`, а awk-пример читает entrypoint skill и успешно создаёт пустой файл. — [V-972 C11](.orchestra/tasks/V-972/report.md)
- Уточнить lifecycle для финального RESEARCH DONE: исследовательская роль называет findings конечным результатом, а kill gate трактует RESEARCH DONE без последующего DONE как незавершённую фазу. — [V-972 C07](.orchestra/tasks/V-972/report.md)
- Миграция раскладки проекта при старте прячет незакоммиченные файлы проекта в stash… — OPEN-DEFECT, [T004](.orchestra/tasks/V-698/triage.md#t004). Доказательство: `app/orchestra_layout.py:1162 onward (stash precedes migration; restore follows success)`.
- bg_create(type="run") исполняет команду в cwd сервиса /home/kesha/orchestra, а не… — OPEN-DEFECT, [T014, T169](.orchestra/tasks/V-698/triage.md#t014). Доказательство: `app/bg_jobs.py:1054-1058 (local subprocess call has no cwd)`.
- migrate_orchestra_layout.py --repair НЕ чинит смешанное состояние, а отсылает сам… — OPEN-DEFECT, [T146](.orchestra/tasks/V-698/triage.md#t146). Доказательство: `scripts/migrate_orchestra_layout.py; 71a008fe:TODO.md:L210`.
- check_orchestra_paths.py падает на контуре с чужой историей и не даёт третий крите… — OPEN-DEFECT, [T147](.orchestra/tasks/V-698/triage.md#t147). Доказательство: `scripts/check_orchestra_paths.py; 71a008fe:TODO.md:L211`.
- Общий стек git stash уносит работу воркеров. — OPEN-DEFECT, [T052](.orchestra/tasks/V-698/triage.md#t052). Доказательство: `71a008fe:TODO.md:L82 (preserved incident and shared-stash observation)`.
- __pycache__ под .orchestra/ не игнорируется: правило-исключение перебивает общий ш… — OPEN-DEFECT, [T075](.orchestra/tasks/V-698/triage.md#t075). Доказательство: `evidence/orchestra_pycache_ignored.txt — .gitignore:26 excludes .orchestra/**`; отчёт: `.orchestra/tasks/V-583/__pycache__/probe.pyc`.
- Устаревшие копии скиллов в Claude-worktree — OPEN-DEFECT, [T108](.orchestra/tasks/V-698/triage.md#t108). Доказательство: `71a008fe:TODO.md:L156 (worktree copy behavior; stale skill report)`.

## Merge gate и операции
- worker_wip и kill_worker падают «cannot resolve git common dir for /home/kesha/archive», если worktree воркера прицеплен к bare-репозиторию (comfy, `/home/kesha/archive/comfy-monorepo.git`, перецеплено 19.09): платформа берёт родительский каталог bare-репо вместо него самого. Обход 05.10 у comfy-image-orchestrator-vps: `git worktree remove` руками, затем `kill_worker(force)`.
- Гейт мутации при мерже (app/merge_test_gate.py) передаёт pytest УДАЛЁННЫЕ тест-фай… — OPEN-DEFECT, [T012](.orchestra/tasks/V-698/triage.md#t012). Доказательство: `app/merge_test_gate.py:225,574-577`; отчёт: `.orchestra/tasks/...`.
- Два правила гейта мержа противоречат друг другу: «домержи main, если ветка отстала… — OPEN-DEFECT, [T020](.orchestra/tasks/V-698/triage.md#t020). Доказательство: `71a008fe:TODO.md:L38; current prompt pair to reconcile`.
- merge_worker в состоянии PENDING читается агентами как провал, потому что объяснен… — OPEN-DEFECT, [T072](.orchestra/tasks/V-698/triage.md#t072). Доказательство: `71a008fe:TODO.md:L112 (PENDING result rendering incident)`.
- merge_worker рапортует SUCCEEDED при мерже ветки В САМУ СЕБЯ и нулевом переносе ко… — OPEN-DEFECT, [T095](.orchestra/tasks/V-698/triage.md#t095). Доказательство: `71a008fe:TODO.md:L139; merge_worker target/commit outcome reproduction`.
- switch_worker_branch не атомарен: ветку переключает, привязку теряет — OPEN-DEFECT, [T096](.orchestra/tasks/V-698/triage.md#t096). Доказательство: `71a008fe:TODO.md:L140; switch_worker_branch failure case`.
- ConcurrentTaskUpdateError при параллельной записи канона НЕ чинится в #426 — план… — OPEN-DEFECT, [T138, T153](.orchestra/tasks/V-698/triage.md#t138). Доказательство: `71a008fe:TODO.md:L197 (ConcurrentTaskUpdateError evidence)`.

## Worker/task lifecycle
- Решить, нужно ли менять бюджет merge для исследовательских улик: `app/diff_budget.py` намеренно считает все вставки, включая `.orchestra/tasks/**`; в openrouter-lab V-10/V-11 сработал лимит, оба мержа разрешены оркестратором через `waive_diff_budget=True`. Это работающий проверяемый override, не потеря данных; исключение каталогов требует решения о новой границе проверки. Bug inbox: `20261019T091719.914242Z-ad185fa8f63a497aa6e52e63b1fe3322.md`.
- Рассмотреть хранение разрешений платных OpenRouter-маршрутов в данных с источником авторизации вместо `PAID_HARNESS_ROUTES` в Python. Сейчас точный allowlist — действующая защита расходов; перевод в конфиг/таблицу меняет контроль допуска и требует отдельного решения, а не снятия проверки под видом багфикса. Bug inbox: `20261019T091719.842778Z-bb97ab608935405588130c6ae66e7fea.md`.
- Доставки send_message к Codex-воркеру встают намертво: голова очереди в `WAITING_NEXT_TURN` (восстановленное влитие, лежит в mailbox до следующего хода) блокирует все `QUEUED` позади, а ход сам не начинается. 05.10: fix-codex и feat-kesha-alert 3+ часа без доставок после прерванного shutdown; рестарт сервиса и `restart-cli` не помогли. Обход: сообщение через дашбордный канал `/send` (channel=dashboard) запускает ход, и очередь трогается. Баг заведён report_bug 05.10.
- ОТКРЫТО: Codex CLI обновлён до 0.156.1 (23.09, ради GPT-6), а импорт истории закре… — OPEN-DEFECT, [T057](.orchestra/tasks/V-698/triage.md#t057). Доказательство: `evidence/red_codex_history_pin.txt; evidence/codex_history_runtime_version.txt`.
- Codex usage fetch failed: с пустым текстом — 15 раз за 01–04.10 (error_watch V-647). — OPEN-DEFECT, [T066](.orchestra/tasks/V-698/triage.md#t066). Доказательство: `app/routes/system.py:872; historical report in 71a008fe:TODO.md:L106`.
- P1. Сообщение, влитое в идущий ход Codex, НЕ переживает обрыв этого хода — и теряе… — OPEN-DEFECT, [T067](.orchestra/tasks/V-698/triage.md#t067). Доказательство: `71a008fe:TODO.md:L107 (incident record; Codex active-turn message path)`.
- Привязка задачи не встаёт при спавне роли sub-orchestrator, и мерж потом отбивается. — OPEN-DEFECT, [T069](.orchestra/tasks/V-698/triage.md#t069). Доказательство: `71a008fe:TODO.md:L109 (spawn_worker task-binding incident)`.
- merge_worker(task_outcome="continue") — ловушка: прогон задачи остаётся открытым,… — OPEN-DEFECT, [T080, T154](.orchestra/tasks/V-698/triage.md#t080). Доказательство: `71a008fe:TODO.md:L121; repeated as item 154 at L225`.
- P1 (остаток от #V-544). PHOTO_INVALID_DIMENSIONS размером не ловится. — OPEN-DEFECT, [T090](.orchestra/tasks/V-698/triage.md#t090). Доказательство: `71a008fe:TODO.md:L131; current file-delivery path noted there`.
- stop_worker рапортует «interrupted and set to idle», не остановив ход — OPEN-DEFECT, [T097](.orchestra/tasks/V-698/triage.md#t097). Доказательство: `71a008fe:TODO.md:L141; stop_worker completion case`.
- Рестарт оставляет Codex-тред с открытым писателем и сессию в RUNNING, которого нет… — OPEN-DEFECT, [[T098, T171, T174](.orchestra/tasks/V-698/triage.md#t098). Доказательство: `app/backend_codex.py:376; app/session.py:1994`.
- Отказ session has no bound task не различает две ситуации. — OPEN-DEFECT, [T099](.orchestra/tasks/V-698/triage.md#t099). Доказательство: `app/tm.py:1432`.
- У воркера, упёршегося в потолок диффа, нет легального выхода — OPEN-DEFECT, [T101](.orchestra/tasks/V-698/triage.md#t101). Доказательство: `app/diff_budget.py:16; 71a008fe:TODO.md:L145`.
- Исчерпанная квота Codex даёт пустое падение вместо внятной ошибки — OPEN-DEFECT, [T103](.orchestra/tasks/V-698/triage.md#t103). Доказательство: `app/backend_codex.py:1379,1963; 71a008fe:TODO.md:L147`.
- Штатный путь «смержил → просто напиши воркеру новую задачу» ведёт прямо в отказ 40… — OPEN-DEFECT, [T159](.orchestra/tasks/V-698/triage.md#t159). Доказательство: `app/routes/sessions.py:2338; 71a008fe:TODO.md:L241`.
- Провал send_message ГЛУШИТ авто-репорт: результат воркера лежит в логах и не доход… — OPEN-DEFECT, [T176](.orchestra/tasks/V-698/triage.md#t176). Доказательство: `71a008fe:TODO.md:L275 (send_message failure and missing recipient)`.

## Usage и quota
- Мелкие замечания ревью аудита 01.09, не закрытые в трёх раундах — OPEN-DEFECT, [T104](.orchestra/tasks/V-698/triage.md#t104). Доказательство: `app/routes/system.py:2414; app/limit_wake.py:44; app/message_deliveries.py:70`; отчёт: `.orchestra/tasks/audit-0901/review-round1.json`.
- График usage: ~161 законный ноль не рисуется — OPEN-DEFECT, [T113](.orchestra/tasks/V-698/triage.md#t113). Доказательство: `71a008fe:TODO.md:L161; .orchestra/tasks/150/report.md`; отчёт: `.orchestra/tasks/150/report.md`.

## Telegram
- TG media buffer race — OPEN-DEFECT, [T109](.orchestra/tasks/V-698/triage.md#t109). Доказательство: `app/tg_bridge.py:625; tests/test_audit0901_tg.py:99-125`.
- TG дубли expandable+image — OPEN-DEFECT, [T110](.orchestra/tasks/V-698/triage.md#t110). Доказательство: `71a008fe:TODO.md:L158 (duplicate renderer paths)`.
- Мост МОЛЧА глотает сообщения из темы, не привязанной ни к одному агенту — владелец… — OPEN-DEFECT, [T150](.orchestra/tasks/V-698/triage.md#t150). Доказательство: `app/tg_bridge.py; 71a008fe:TODO.md:L217 (five-message incident)`.
- Значок темы в Telegram залипает на «выполняет ход» после рестарта: агент простаива… — OPEN-DEFECT, [T185](.orchestra/tasks/V-698/triage.md#t185). Доказательство: `app/tg_bridge.py:3025-3036; 71a008fe:TODO.md:L293`.

## Данные и интеграции
- Pending tm_sync_log без fire в CLI-контексте — OPEN-DEFECT, [T111](.orchestra/tasks/V-698/triage.md#t111). Доказательство: `71a008fe:TODO.md:L159 (_fire_sync pending-write case)`.
- Права в /api/sessions/{name}/message включаются полем ТЕЛА запроса, поэтому отключ… — OPEN-DEFECT, [T179](.orchestra/tasks/V-698/triage.md#t179). Доказательство: `app/routes/sessions.py:1010-1013`.
- Снимок истории чата грузится целиком при каждом переключении, потому что у /api/se… — OPEN-DEFECT, [T184](.orchestra/tasks/V-698/triage.md#t184). Доказательство: `app/routes/sessions.py:713-720 (GET logs sets Cache-Control: no-store)`; отчёт: `.orchestra/tasks/V-583/research.md`.

## Модель проектов и задач
- Строка tm_projects с id orchestra указывает НЕ на тот проект, который имеет в виду… — OPEN-DEFECT, [T182](.orchestra/tasks/V-698/triage.md#t182). Доказательство: `.orchestra/tasks/V-576/namespace-map.md (recorded in 71a008fe:TODO.md:L287)`; отчёт: `.orchestra/tasks/V-576/namespace-map.md`, `.orchestra/tasks/V-576/research.md`.

## Хранилище Codex

## Решение владельца
- Пробный bug-hunter на нашем коде (один агент против этапов «искать по частям → убрать дубли → проверить → свести» на коммите с известными багами, равный бюджет, Luna). Владелец 10.10 15:50: «лимитов мало потом баг хантер» — отложено до свободных лимитов. Основание: [V-806](.orchestra/tasks/V-806/report.md).
- Контракт «замороженные acceptance-тесты не ослаблять» ведётся двумя независимыми к… — NEEDS-OWNER, [T008](.orchestra/tasks/V-698/triage.md#t008). Доказательство: `71a008fe:TODO.md:L15 (original detailed record)`.
- Починить два checkout'а, на которых падает миграция layout. — NEEDS-OWNER, [T017](.orchestra/tasks/V-698/triage.md#t017). Доказательство: `71a008fe:TODO.md:L32 (original detailed record)`.
- Ноутбук: добавить --timeout-graceful-shutdown 5 в ExecStart юнита orchestra — NEEDS-OWNER, [T046](.orchestra/tasks/V-698/triage.md#t046). Доказательство: `71a008fe:TODO.md:L76 (original detailed record)`. Проверено 05.10: флага в ExecStart нет, StartLimitIntervalUSec=10s — нужен sudo владельца на ноутбуке (связано с V-708).
- На ноутбуке юзера Hermes v0.20.1 пишет навыки и память БЕЗ апрува, и это его насто… — NEEDS-OWNER, [T060](.orchestra/tasks/V-698/triage.md#t060). Доказательство: `71a008fe:TODO.md:L94 (original detailed record)`.
- Ловить rate_limit_event и сохранять неокруглённую utilization (Claude), проверить аналог у Codex: владелец 05.10 «конечно делай». В работе V-707. [T062](.orchestra/tasks/V-698/triage.md#t062).
- Нет единого события приёмки, поэтому спор «какая модель лучше» решается памятью, а… — NEEDS-OWNER, [T068](.orchestra/tasks/V-698/triage.md#t068). Доказательство: `71a008fe:TODO.md:L109 (original detailed record)`.
- Потолок MAX_DIFF_INSERTIONS = 2000 (app/diff_budget.py:16) не различает код и ресё… — NEEDS-OWNER, [T100](.orchestra/tasks/V-698/triage.md#t100). Доказательство: `71a008fe:TODO.md:L144 (original detailed record)`.
- Прямые коммиты оркестратора в main не привязываются к задачам. — NEEDS-OWNER, [T102](.orchestra/tasks/V-698/triage.md#t102). Доказательство: `71a008fe:TODO.md:L146 (original detailed record)`.
- Наш компакт физически не может опередить клишный: он запрещён во время хода, а кон… — NEEDS-OWNER, [T105](.orchestra/tasks/V-698/triage.md#t105). Доказательство: `71a008fe:TODO.md:L151 (original detailed record)`.
- 32 коммита VPS не публиковались в origin — NEEDS-OWNER, [T117](.orchestra/tasks/V-698/triage.md#t117). Доказательство: `71a008fe:TODO.md:L167 (original detailed record)`.
- 21 задача на паузе у спящих воркеров — NEEDS-OWNER, [T118](.orchestra/tasks/V-698/triage.md#t118). Доказательство: `71a008fe:TODO.md:L168 (original detailed record)`.
- Личные скиллы из ~/.claude/skills в пайплайн — NEEDS-OWNER, [T119](.orchestra/tasks/V-698/triage.md#t119). Доказательство: `71a008fe:TODO.md:L169 (original detailed record)`.
- Grok: включать ли в pipeline.yaml роль. — NEEDS-OWNER, [T120](.orchestra/tasks/V-698/triage.md#t120). Доказательство: `71a008fe:TODO.md:L170 (original detailed record)`.
- Озвучка роликов через ElevenLabs: отложено, «как дойдут руки, чтобы качественно бы… — NEEDS-OWNER, [T130](.orchestra/tasks/V-698/triage.md#t130). Доказательство: `.orchestra/tasks/V-694/report.md (recorded in 71a008fe:TODO.md:L184)`; отчёт: `.orchestra/tasks/V-694/report.md`, `.orchestra/tasks/V-694/probe_phrases.json`.
- Оставшиеся вопросы из #507 требуют отдельного обсуждения: — NEEDS-OWNER, [T141](.orchestra/tasks/V-698/triage.md#t141). Доказательство: `commit 20260909 (recorded in 71a008fe:TODO.md:L202)`.
- Общего фильтра live tool results у нас нет (#507). — NEEDS-OWNER, [T142](.orchestra/tasks/V-698/triage.md#t142). Доказательство: `71a008fe:TODO.md:L203 (original detailed record)`.
- Миграция раскладки docs/ → .orchestra/ (03.09) сломала замороженные тесты, которые… — NEEDS-OWNER, [T152](.orchestra/tasks/V-698/triage.md#t152). Доказательство: `.orchestra/tasks/2/ (recorded in 71a008fe:TODO.md:L221)`; отчёт: `.orchestra/tasks/2/`, `.orchestra/tasks/11/report.md`.
- Миграция раскладки 03.09 осиротила ~18 веток: у каждой внутри СВОЯ копия переезда… — NEEDS-OWNER, [T161](.orchestra/tasks/V-698/triage.md#t161). Доказательство: `.orchestra/tasks/450/codex-review-impl.md (recorded in 71a008fe:TODO.md:L245)`; отчёт: `.orchestra/tasks/450/codex-review-impl.md`.
- Гейт kill_worker считает КОММИТЫ, а не содержимое, и поэтому требует force там, гд… — NEEDS-OWNER, [T165](.orchestra/tasks/V-698/triage.md#t165). Доказательство: `71a008fe:TODO.md:L253 (original detailed record)`.
- Развилка #504 T4 ждёт владельца: классификатор «НЕ ВЫПОЛНЕНО» по XML-подобной проз… — NEEDS-OWNER, [T172](.orchestra/tasks/V-698/triage.md#t172). Доказательство: `.orchestra/tasks/504/review-implementation.md (recorded in 71a008fe:TODO.md:L267)`; отчёт: `.orchestra/tasks/504/review-implementation.md`.
- Наша телеметрия квот выбрасывает всё, кроме двух старых полей, — поэтому отдельног… — NEEDS-OWNER, [T181](.orchestra/tasks/V-698/triage.md#t181). Доказательство: `71a008fe:TODO.md:L285 (original detailed record)`.
- `tests/test_t344_quota_lines_browser.py:686` при каждом прогоне перезаписывает отслеживаемый `.orchestra/tasks/V-862/quota-override-form.png` (так же голосовые тесты `tests/test_frontend.py` — `.orchestra/tasks/V-860/screenshots/*.png`) — рабочее дерево грязнеет после тестов; снимок надо писать во временный каталог (V-876).
- Аналитика: подпись пула Codex «Sol · воркеры» (`_PROVIDER_META.codex.runtime` в `app/static/js/utils.js`) устарела — рабочий воркер по умолчанию Luna (V-876).
- Дизайн-система: оставшиеся hex в объектах JS (`_orchSimple` карточек инструментов чата, опции Chart.js) и в голосовом блоке `chat.js`/`.voice-*` перевести на токены при следующей правке этих мест (V-876, `docs/design-system.md` «Что осталось на hex»).

## При обновлении Claude CLI до ≥2.1.299 (V-908)
- Явно выключить встроенный idle compaction (`"idleCompaction": false` в настройках профиля агентов или env подпроцесса в `backend_claude._make_client`), `autoCompactEnabled` не трогать. Иначе он сработает раньше нашего precompact (54 мин / 200K против 55 мин / 30%) и сожмёт хуже нашего AUDIT+FINAL.
- После апгрейда проверить: на сессии, простоявшей 54+ мин, нет `compact_boundary` с `trigger:"auto"` и `preTokens` < 700K; повторить стрим-замер V-831.

## Правила: хвосты чистки (V-932, из V-931 п.5, п.14)
- Сравнение effort оркестраторов `high` после 03.10, обещанное в комментарии `pipeline.yaml` через `.orchestra/tasks/V-683/complaint_rate.py`, так и не сделано; запустить сравнение или снять комментарий-обещание.
- В `/home/kesha/projects/comfy-image-pipeline/AGENTS.md` (строки 100 и 168) мёртвые ссылки на старые каталоги задач и базы знаний (файлы `selected-pipeline.md` и `working-with-machines.md` переехали в `.orchestra/tasks/31/` и `.orchestra/kb/`); корень `dnd-game-master/AGENTS.md:203` и корень Orchestra описывали платформенный факт о чтении CLAUDE.md по-разному — у знания нет владельца. Чужие проекты, не правились.

## Ролики
- Сверить описанный в `.codex/skills/video-artifact/SKILL.md` Deepgram Nova-2 с текущим `app/transcription.py` (Nova-3, учёт `$0.0052/мин`) и решить, какие проверки роликов должны использовать какой endpoint. Несогласованность найдена в V-987; `.orchestra/tasks/V-987/report.md`.
- Скилл video-artifact указывает PLAYWRIGHT_BROWSERS_PATH в /mnt/data, а на VPS этого каталога нет; браузеры лежат в ~/.cache/ms-playwright (V-938). Поправить указание в скилле.
- `scripts/video_artifact/tts_worker_en.py`: четыре потока Kokoro читают один `voices-v1.0.bin` (NpzFile делит один zip-дескриптор), и сборка английского ролика падает с `zipfile.BadZipFile: Overlapped entries: 'af_heart.npy'`. Найдено 18.10.2026 при пересборке сцены V-824 в V-944 (английская сцена не собралась, русская собралась). Лечится загрузкой голоса один раз до пула потоков или блокировкой вокруг `get_voice_style`.

- V-964: 12 deliveries stuck in QUEUED (wake=1, oldest 2026-10-05): 7 to archived sessions, 5 to idle session decision-cost; no failure notice, no sweeper. Diagnose cause; consider age-based sweeper + transition table in message_deliveries._update_state (see .orchestra/tasks/V-964/report.md).
