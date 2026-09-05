# #507 — Anthropic commerce agents как blueprint production-агента

Дата среза: 2026-09-03. Внешний репозиторий зафиксирован на
`fd4d59224ab96b43c6dc6888207c67b3bd5a24cf` (2026-08-31); Orchestra — на
`bc86dfcda19ab5d1096f07955ee0b8e41e1ddda1` (2026-09-02). Коммерческие сценарии
не оцениваются; предмет — устройство агента, guardrails и проверка результата. Никаких
предложений по внедрению в этом документе нет.

## Question

- **Context:** production-agent blueprint Anthropic и текущий production-контур Orchestra.
- **Change under test:** паттерны, которые Anthropic рекомендует и/или реализует в reference code.
- **Baseline:** текущие кодовые и prompt-owned механизмы Orchestra.
- **Outcome:** для каждого названного паттерна установлено: точная опора у Anthropic; назначение;
  точный аналог у нас либо проверенное отсутствие; вердикт `совпадает` / `у нас иначе и почему` /
  `пробел`.

## Hypotheses considered

1. **H1:** общие production-паттерны Anthropic в основном уже присутствуют в Orchestra, потому что
   обе системы отделяют модель от необратимой мутации. **Фальсификатор:** у Anthropic есть несколько
   code-enforced предохранителей того же класса, которые у нас существуют лишь как текстовые правила.
2. **H2:** главный новый для нас паттерн — provenance/fencing на границе tool result, потому что
   commerce-код не доверяет ни одному ID и ни одному внешнему тексту. **Фальсификатор:** общий
   Orchestra executor уже санитизирует и помечает все live tool results до попадания модели.
3. **H3 (альтернатива):** статья описывает aspirational production practice шире открытого кода.
   **Фальсификатор:** все заявленные eval, memory и deployment-паттерны имеют работающий путь и
   runnable fixture в репозитории.

## Полная матрица паттернов статьи вне guardrails

В строках `CONFIRMED` статья сверена с кодом/документацией репозитория (два primary-source плеча).
`LIKELY` означает проверенное отсутствие по текущему дереву, но не утверждение о закрытом коде
production-клиентов Anthropic.

| Их паттерн (точная ссылка) | Зачем он у них | Есть ли аналог у нас | Вердикт |
|---|---|---|---|
| **Один model loop без intent-router; один агент владеет разговором.** [`commerce-architecture`:12-20][R-arch] | Не терять cart/history/preferences на межагентных handoff и не платить повторным контекстом. | `pipelines/default/pipeline.yaml:35-109` разделяет root-orchestrator и долгоживущие worker-сессии; `app/session.py:1921-2028` сохраняет native session между ходами. | **CONFIRMED — у нас иначе и осознанно:** разговор с юзером остаётся у orchestrator, а закрытая работа уходит в отдельный persistent worker; задача не является одной tightly-coupled корзиной. |
| **Skills вместо domain-subagents; delegate только для узкой автономной задачи.** [`commerce-architecture`:32-39,66-72][R-arch] | Модульность без state-lossy handoff; отдельное окно только там, где результат самодостаточен. | Роли и skills задаёт `pipeline.yaml:35-109`; `roles/full-cycle.md:124-138` делегирует целый закрытый ticket одному executor; `model-routing.md:21-24` требует готовый oracle. | **CONFIRMED — совпадает по границе, не по топологии:** мы тоже не дробим один ticket между агентами, но сама Orchestra является multi-agent системой. |
| **Правило кладётся в tool description / static prompt / skill по частоте применения.** [`commerce-architecture`:22-30][R-arch] | Не раздувать prompt редкими процедурами и не тратить turn на частое правило. | `app/pipeline.py:568-601` собирает role prompt + modules; skills доставляются через `app/manager.py:851-872`. Метрики traffic-frequency или порога в коде нет. | **CONFIRMED — пробел:** слои есть, но placement выбирается вручную; их эвристика «частое вниз, редкое в skill» и проверка по реальному traffic mix у нас не формализованы. |
| **Предсказуемый по внешнему сигналу skill инжектируется harness-ом до первого model call.** [статья, раздел System prompt or skill][B] | Убрать отдельный turn загрузки skill. | Skills ставятся в worktree при spawn (`app/manager.py:851-872`), но request/task signal не выбирает конкретное тело до model call. | **LIKELY — пробел:** найден delivery всего набора skills, но не preloading одного skill по сигналу запроса. В reference repo этот совет тоже не реализован: `SkillRegistry.index_block` + `load_skill` остаются model-driven [`commerce-architecture`:34-39][R-arch]. |
| **Agent tools вызывают существующую core-логику, не переписывают её.** [`commerce-architecture`:41-64][R-arch] | Держать business rules и credentials в серверных системах, а модели оставить выбор/композицию. | MCP-обёртка зовёт HTTP owner через `_api` (`app/mcp_stdio.py:503-531`); операции сессий, задач и merge живут в `app/routes/`, `app/tm.py`, `app/workspace.py`. | **CONFIRMED — совпадает.** |
| **Tool result — это context: оставить reasoning fields, удалить шум, вернуть actionable error.** [`commerce-architecture`:41-64][R-arch]; `BaseToolExecutor.execute` [`execution.py`:98-103,214-223][R-exec] | Сократить токены и дать модели следующий корректный шаг вместо голого статуса. | `_api` нормализует retryability/outcome-unknown и server error (`app/mcp_stdio.py:430-475`), но успешный payload общего ограничения/reshape не проходит. | **CONFIRMED — частично совпадает; пробел:** ошибки actionable, но единого output-budget/проектора для live tool results нет. |
| **UI component — typed tool; server валидирует и обогащает, frontend только рендерит.** [`commerce-ui-tools`:11-27][R-ui] | Не парсить model markup, не доверять model-authored values, хранить UI-native history. | Agent не проектирует dashboard UI. Orchestra передаёт типизированные log events по SSE (`app/session.py:2296-2320`, `app/routes/sessions.py:512-577`) и клиент санитизирует DOM, но обычный ответ остаётся model text. | **CONFIRMED — у нас иначе по продукту:** generative UI не нужен; структурированные события совпадают с transport-частью паттерна. |
| **Load likely context up front.** [статья, Fewer turns][B] | Уменьшить число round-trips. | Role prompt, ownership overlay, worker memory и project rules собираются до backend connect (`app/manager.py:574-590`, `app/session.py:1921-1952`); task message идёт первым turn. | **CONFIRMED — совпадает для task context.** У нас нет page-level consumer signal, потому что нет commerce UI. |
| **Более сильная модель может выиграть total latency за счёт меньшего числа turns.** [статья, Fewer turns][B] | Оптимизировать completion, а не скорость токена. | `pipeline.yaml:17-34` хранит измеренные effort knees; `model-routing.md:21-24` выбирает класс по сложности. Сам выбор Luna/Sol/Opus остаётся prompt-only, что подтверждено `docs/kb/model-routing-selection.md`. | **CONFIRMED — совпадает как политика, но не code-router.** |
| **Независимые tools вызываются параллельно в одном turn.** [статья, Fewer turns][B]; concurrent calls в [`commerce-architecture`:14-20][R-arch] | Не платить отдельным turn за независимые запросы. | `orchestration.md:116-123` задаёт `run_fan` для независимых workers; общий developer contract разрешает compose parallel tool calls. | **CONFIRMED — совпадает.** Для workers это крупнее, чем их parallel tool calls: durable fan с одним wake-up. |
| **Tool не должен склеивать отсутствующий backend; нужен один upstream endpoint.** [статья, Faster tools][B] | Не размазывать domain logic по agent boundary. | MCP tools в основном тонкие HTTP-клиенты (`app/mcp_stdio.py:503-531`), а lifecycle/merge owners находятся на сервере. | **CONFIRMED — совпадает.** |
| **Eager tool dispatch по мере завершения аргументов; медленный call первым.** [`commerce-ui-tools`:54-65][R-ui] | Перекрыть model streaming и backend latency. | У Orchestra tool call исполняет vendor CLI после готового вызова; общего раннего dispatch partial JSON нет. | **LIKELY — пробел:** точный поиск `eager_input_streaming`/partial tool arguments в `app/` аналога не нашёл. |
| **Progressive rendering и streaming components.** [`commerce-ui-tools`:42-65][R-ui] | Уменьшить perceived latency без изменения total latency. | Claude partial text превращается в `stream` events (`app/backend_claude.py:1233-1253`), затем live broker/SSE (`app/session.py:2298-2304`, `app/routes/sessions.py:554-570`). | **CONFIRMED — совпадает на уровне потока**, хотя нет component partial enrichment. |
| **Показывать человеку короткую status line из tool arguments.** [`commerce-ui-tools`:44-52][R-ui] | Сделать ожидание наблюдаемым и понятным. | Tool/thinking/status события видны в live stream; агенты обязаны давать commentary updates. Отдельного sanitized model-supplied `status` аргумента у каждого tool нет. | **CONFIRMED — у нас иначе:** прогресс берётся из runtime events и агента, не из отдельного schema field. |
| **Cache-stable request: fixed tools → static system → session → volatile; три rolling breakpoints.** [`commerce-prompt-caching`:11-40][R-cache] | Сохранять общий prefix byte-identical и переиспользовать длинную историю/tool results. | Persistent backend/session и cache counters есть (`app/session.py:1921-2028`, `app/backend_claude.py:1409-1456`), prompt собирается детерминированно (`app/pipeline.py:568-601`). Явных cache breakpoint и разделения session/volatile нет. | **CONFIRMED — частично совпадает; пробел:** наблюдаем cache, но не управляем его тремя сегментами в своём harness. |
| **Skill body загружается как tool result; rolling marker двигается по истории.** [`commerce-prompt-caching`:42-58][R-cache] | Skill и длинные tool results становятся частью cacheable conversation prefix. | Native Claude/Codex skills доставляются runtime-у (`app/manager.py:851-872`, `app/session.py:1941-1949`); детали cache-mark принадлежат vendor runtime и у нас не верифицируются. | **LIKELY — совпадает по Skill tool, не доказано по cache marker.** |
| **Model + effort выбираются полным eval sweep; metric floor и cost per completed task.** [`commerce-evals`:80-90][R-evals]; model fields [`commerce-architecture`:74-78][R-arch] | Не принять дешёвый call за дешёвую выполненную задачу. | Есть измеренные routing rules (`model-routing.md:19-24`) и cost/turn telemetry, но нет единой task-eval suite, автоматически sweeping все model/effort. | **CONFIRMED — пробел:** политика основана на отдельных замерах, не на воспроизводимом sweep каждого task mix. |
| **Memory вне модели: typed records в deployment store.** [`commerce-trust-safety`:63-75][R-safety-skill] | Переживать сессии, искать/валидировать факты и применять deterministic behavior. | Project memory хранится вне модели в git-canonical `docs/kb/`; format/links валидирует `scripts/check_kb_contract.py:13-30,100-110`; читается по `memory-search.md:4-39`. | **CONFIRMED — совпадает по принципу, иначе по данным:** у нас project knowledge, а не personal profile; Markdown — намеренный canonical owner, SQLite/FTS лишь projection. |
| **Merchant memory key by person, permissions per operator.** [статья, Storing memories][B] | Не смешивать факты людей с общим merchant login. | Orchestra — один оператор; данные разделены project `scope`, не человеком. | **CONFIRMED — сейчас неприменимо у нас. Важное расхождение у них:** open code возвращает `merchant_id`, а не `operator` ([`merchant_agent/executor.py`:133-135][R-merchant-exec]; [`types.py`:444-452][R-merchant-types]). |
| **Отдельный asynchronous extractor после turn.** [статья, Writing memory][B]; repo host [`host.py`:77-85,185-203][R-host] | Не добавлять latency/attention в пользовательский turn. | Тот же research-agent вручную пишет task artifact и promoted fact; отдельного extractor нет. Индексация — projection, не извлечение смысла. | **CONFIRMED — пробел по разделению автора и памяти. У них код слабее формулировки:** demo запускает `asyncio.create_task` в том же процессе, не отдельный thread/process. |
| **Extractor читает только user/assistant text, не tool results.** [`commerce-common/turn.py`:87-107][R-turn] | Не превратить listing/review/tool injection в факт о пользователе. | У нас promotion делает тот же агент из всех прочитанных источников по prompt-contract; content provenance не фильтрует tool result code-enforced. | **CONFIRMED — пробел:** poisoned source может попасть в KB до reviewer/ручной проверки. |
| **Memory reads в три слоя: fixed context, signal-prefetch, lookup tool.** [статья, Reading memory][B] | Баланс recall, context cost и latency. | `memory-search.md:4-39` даёт hot prompt + targeted KB grep; `search_memory` — optional fallback (`app/mcp_stdio.py:3390-3425`). | **CONFIRMED — концептуально совпадает у нас. В reference code реализовано только два слоя:** `tier_one` + `recall_memories` (`memory.py:229-245,601-637`)[R-memory]; signal-based relevant prefetch отсутствует. |
| **Eval snapshot, а не полный разговор.** [`commerce-evals`:13-42][R-evals] | Детерминированно построить failure preconditions без второй недетерминированной стороны. | Unit/acceptance tests строят fixture state; platform запускает pinned oracle и mapped test subset (`app/acceptance.py:349-378`, `app/merge_operations.py:1661-1740`). | **CONFIRMED — совпадает для исполняемого результата.** |
| **Судить final state/rendered output, не путь.** [`commerce-evals`:44-67][R-evals] | Не приколотить тест к допустимому внутреннему маршруту. | Phase 2/3 связывает AC с frozen RED oracle (`roles/full-cycle.md:73-99,118-138`); merge проверяет его вне worker (`app/acceptance.py:1,349-378`). | **CONFIRMED — совпадает и у нас сильнее code-enforced на merge.** |
| **Simulated-user для discovery/vibe; rubric оценивает отдельный pinned LLM judge.** [`commerce-evals`:68-78][R-evals] | Снизить variance/cost и отделить agent failure от judge failure. | Reviewer у нас — отдельный sensor code/document review, не semantic grader и не oracle (`.codex/skills/codex-debate/SKILL.md:13-39`); deterministic test остаётся oracle. | **CONFIRMED — совпадает по запрету self-judgment, но механизм другой:** общего semantic-judge harness у нас нет. |
| **Tough injected state; positive ↔ negative counterparts.** [`commerce-evals`:44-67,92-100][R-evals] | Ловить поведение после messy history и одновременно over-refusal. | Incident-derived tests и mutation checks есть, но обязательная парность positive/negative живёт в prompt/research method, не в test schema. | **CONFIRMED — частично совпадает; пробел:** нет машинного требования пары для каждого behavioral rule. |
| **Пять eval-классов: core, context/memory, safety/injection, interface, cross-capability.** [`commerce-evals`:17-36,44-67][R-evals] | Не получить локально зелёные capability suites с провалом на стыке. | Тесты и pre-mortem проверяют соседних consumers, но общего taxonomy/coverage report для поведения агентов нет. | **CONFIRMED — пробел:** suite богата, но не измеряет полноту по этой матрице. |
| **Cases вместе с SMEs и real incidents.** [статья, Write evals with SMEs][B] | Фиксировать реальные costly failures, а не синтетический happy path. | `CLAUDE.md`, `docs/kb/evidence-methods.md`, `test-oracles.md` построены из инцидентов; пользователь/оркестратор задаёт AC. | **CONFIRMED — совпадает.** |
| **Ownership follows systems; один owner у skill/tool и shared prompt.** [статья, Shipping with a large organization][B] | Не дать нескольким командам менять один context без владельца. | `app/pipeline.py:1-9,552-601` задаёт одного owner prompt pipeline; KB — one topic/one file owner; `owned_dirs` collision проверяется кодом (`app/manager.py:533-572`). | **CONFIRMED — совпадает для prompt/KB/worktree; code-module ownership не формализован.** |
| **Change ships with cases; targeted CI + every safety case; full suite nightly/release.** [статья, Shipping with a large organization][B] | Ловить local и cross-team regressions при приемлемой цене. | RED oracle обязателен процессом; merge запускает pinned acceptance и mapped subset (`app/merge_operations.py:1661-1740`); CI запускает весь pytest на каждый push/PR (`.github/workflows/ci.yml:8-19`). | **CONFIRMED — совпадает, у нас full suite чаще.** Но RED-authoring и review остаются prompt-owned до merge. |
| **Canary rollout, per-skill kill switch, release freeze.** [статья, Shipping with a large organization][B] | Ограничить blast radius недетерминированного изменения. | Pipeline/config выбираются для сессии, но cohort rollout, runtime per-skill switch и release calendar не найдены. | **LIKELY — пробел:** точные владельцы canary/freeze отсутствуют в `app/`, `pipelines/`, `.github/`. |

## Guardrails: что запрещено и чем принуждается

Эта таблица идёт по **всем 20 строкам** официального `docs/safety.md`, а не по выбранным примерам.
Источник сам отделяет `Enforced in code` от `Still asked of the model` [`docs/safety.md`:12-59][R-safety].

| Их guardrail (точная ссылка) | Зачем он у них | Есть ли аналог у нас | Вердикт |
|---|---|---|---|
| **G1 Fencing:** sanitize + fixed fence + cap всех third-party/tool payloads [`docs/safety.md`:21][R-safety]; реализация [`fencing.py`:99-149][R-fencing] | Prompt-injection, forged roles/tool tags, bidi/control chars, context stuffing. | Только импортированная история помечается `transcript_untrusted` и payload bodies опускаются (`app/runtime_history.py:27-31,320-345,460-495`). Общего фильтра live tool results нет. | **CONFIRMED — пробел:** у них code, у нас live-source дисциплина в prompt. Это прямое подтверждение H2. |
| **G2 Loop/size limits:** clamp result count, max tool iterations, compaction [`docs/safety.md`:22][R-safety] | Ограничить runaway loop/context. | `ClaudeAgentOptions(max_turns=200)` (`app/backend_claude.py:923-929`), auto-continue cap 5 (`app/session_turns.py:394-405`), context compaction. | **CONFIRMED — совпадает**, но наш auto-continue расширяет один logical request до пяти vendor turns вместо forced tool-free closure. |
| **G3 Cart provenance + resulting-state caps + per-session lock** [`docs/safety.md`:23][R-safety]; [`shopping/gates.py`:40-44,86-125][R-shop-gates] | Не принять hallucinated ID и не обойти cap повтором/parallel calls. | Аналог класса: task/session/branch identity, repository mutation lock, diff budget, acceptance/test gate (`app/routes/sessions.py:1847-1909,1966-2009`; `app/workspace.py:1290-1388`). | **CONFIRMED — совпадает по инженерному классу**, commerce cap неприменим. |
| **G4 No payment:** backend interface вообще не имеет charge/order method [`docs/safety.md`:24][R-safety]; [`backend.py`:44-54][R-shop-backend] | Сделать самый опасный вызов структурно невозможным. | У worker main отделён worktree; но Bash и MCP mutation tools доступны, а merge структурно существует. | **CONFIRMED — у нас слабее структурная граница:** prod/main mutation не удалена из общей capability surface, она разделена ролями и prompt rules. |
| **G5 Disclosures server-authored** [`docs/safety.md`:25][R-safety] | Не дать модели сочинить regulated text/figures. | Regulated copy нет; server формирует ошибки/статусы операций, но пользовательский отчёт пишет модель. | **CONFIRMED — неприменимо напрямую; общего server-authored factual response нет.** |
| **G6 UI payload schema + server join + drop unknown IDs** [`docs/safety.md`:26][R-safety] | Не отрендерить model-authored цену/record. | Структурированные log events и DOM sanitization есть; agent-generated business cards нет. | **CONFIRMED — у нас иначе по продукту.** |
| **G7 Grounding forced in code (`tool_choice`/prefetch)** [`docs/safety.md`:27][R-safety]; [`commerce-trust-safety`:44-52][R-safety-skill] | Перед ответом о figure/term гарантировать read, даже если model забудет. | `memory-search.md:4-39` и `research-method.md:194-210` требуют read/retrieve, но backend не форсирует первый tool call. | **CONFIRMED — пробел:** у них code на Messages API и часть SDK; у нас prompt-only. У них самих Managed Agents path также остаётся prompt-only. |
| **G8 Staging provenance:** stage/apply принимает только IDs, виденные в session [`docs/safety.md`:28][R-safety] | Не менять объект из user text/hallucination. | Merge schema требует bound task; candidate refs и branch/head повторно проверяются под lock (`app/routes/sessions.py:1862-1909`; `app/workspace.py:1437-1468`). | **CONFIRMED — совпадает.** |
| **G9 Guardrails rechecked at stage и apply по текущему config** [`docs/safety.md`:29][R-safety]; [`changes.py`:31-108][R-changes] | Закрыть TOCTOU и изменения лимитов после preview. | Merge admission pin + execution-time pinned oracle/mapped tests + target-head recheck (`app/merge_operations.py:1613-1740`; `app/workspace.py:1414-1435,1583-1597`). | **CONFIRMED — совпадает по принципу re-check-at-commit.** |
| **G10 Host approval:** apply только после mark от real surface; chat approval не считается [`docs/safety.md`:30][R-safety]; [`merchant/gates.py`:192-215][R-merchant-gates] | Maker-checker для live mutation. | User approval gates описаны в `orchestration.md:6-38` и `roles/full-cycle.md:43-47,110-112`, но task schema имеет только `new/in_progress/done` (`app/tm.py:32,319-390`) и не хранит user approval receipt. Merge вызывается orchestrator-agent. | **CONFIRMED — пробел:** human approval у нас prompt-enforced, не code-enforced. Merge код проверяет задачу/тесты, но не факт человеческого согласия на архитектуру/реализацию. |
| **G11 Analysis delegate:** read-only tools, schema result, query/call/time/size budgets [`docs/safety.md`:31][R-safety] | Ограничить отдельный model context без write/present authority. | Reviewer/worker изолированы worktree и oracle, но `codex_review` явно запускается с `-s danger-full-access -a never` (`app/mcp_stdio.py:3611,3627,3658,3668`); read-only tool surface для исследователя кодом не выдана. | **CONFIRMED — пробел:** scope — prompt/role convention; их delegate capability урезана конструкцией. |
| **G12 Memory write validator на обоих write paths** [`docs/safety.md`:32][R-safety]; [`memory.py`:183-208][R-memory] | Не хранить identifiers/запрещённые категории и ограничить размер. | `check_kb_contract.py` валидирует форму/stable keys/links, но не допустимость содержания; promotion решение принимает модель по `research-method.md:133-169`. | **CONFIRMED — пробел:** schema code-enforced, semantic eligibility prompt-only. |
| **G13 Extraction только из последнего user/assistant exchange + purge-generation CAS** [`docs/safety.md`:33][R-safety] | Не запомнить tool injection и не воскресить удалённые данные гонкой. | Автоматического extractor нет; KB пишет текущий agent после чтения tool outputs. | **CONFIRMED — пробел / другая модель памяти.** |
| **G14 Memory retention/delete/purge/enable switch** [`docs/safety.md`:34][R-safety] | Privacy lifecycle и regional disable. | KB forward-only и append/retract (`research-method.md:133-169`); RAG/search может выключаться, но canonical facts сохраняются намеренно. | **CONFIRMED — у нас иначе и осознанно:** project audit knowledge не personal data; retention противоположен цели. |
| **G15 Tool errors/blocked outcomes возвращаются модели; exception не завершает turn** [`docs/safety.md`:35][R-safety]; [`execution.py`:214-223][R-exec] | Дать модели исправить аргументы/план без падения loop. | MCP errors сохраняют precise cause/retryability/outcome unknown (`app/mcp_stdio.py:430-531`); tool result помечается `is_error` (`app/backend_claude.py:1284-1316`) и логируется (`app/session.py:2330-2391`). | **CONFIRMED — совпадает.** |
| **G16 Model status line отделяется до validation/gates, sanitizes/caps, идёт только host** [`docs/safety.md`:36][R-safety] | Не смешать model prose с business arguments и не показать control chars. | Status/tool events имеют отдельные типы, но schema-wide sanitized `status` аргумента нет. | **CONFIRMED — частичное совпадение на event boundary.** |
| **G17 Tool surface — функция deployment config; executor rejects other names; SDK allowlist** [`docs/safety.md`:37][R-safety] | Least privilege и неизменный surface. | Runtime удаляет/запрещает tool names в коде (`app/backend_claude.py:61-69,447-455`); pipeline задаёт `skills`/`mcp_servers` (`pipeline.yaml:4-15,35-109`). | **CONFIRMED — совпадает.** Но обычные tools auto-approved кроме deny-list (`app/backend_claude.py:157-164`). |
| **G18 Identity server-held; tool args не называют principal** [`docs/safety.md`:38][R-safety] | Не дать модели/user подменить tenant. | Session/task/scope берутся из process/session metadata; `search_memory` берёт `SCOPE` из env, не аргумента (`app/mcp_stdio.py:3390-3401`); merge повторно сверяет identity. | **CONFIRMED — совпадает.** |
| **G19 Versioned session state; racing write не перезаписывает новое** [`docs/safety.md`:39][R-safety] | Сохранить provenance между process/turn и закрыть lost update. | Durable SQLite session/task state, lifecycle locks и pinned head/target rechecks (`app/routes/sessions.py:1808-1846,1974-2009`). | **CONFIRMED — совпадает.** |
| **G20 MCP loopback unless authenticating gateway declared** [`docs/safety.md`:40][R-safety] | Не открыть unauthenticated tools наружу. | Agent MCP — stdio; HTTP hop условно добавляет Bearer только при непустом `_INTERNAL_TOKEN` (`app/mcp_stdio.py:336-344,503-529`). На live production 2026-09-03 `.env` и `/proc/2354602/environ` оба дали `INTERNAL_TOKEN_nonempty=True`. | **CONFIRMED для текущего production; код fail-open при пустом token**, поэтому это не безусловная гарантия deployment config. |
| **Prompt-only остаток:** fenced text не инструкция; figures только из tool; confirm после success; IDs для UI; referral на safety questions [`docs/safety.md`:42-59][R-safety] | Ошибка ограничена словами и не требует отката действия. | У нас prompt-only остались также human approval, source-first grounding, file ownership и часть destructive-action discipline; последствия забывания могут быть mutation/data loss. | **CONFIRMED — пробел относительно нашего собственного критерия:** Anthropic оставляет в prompt только правила, чьё нарушение не обходит code gates; у нас ряд consequential правил остаётся текстом. |

### Где Anthropic принуждает кодом то, что у нас живёт в промпте

| Действие | Anthropic | Orchestra | Итог |
|---|---|---|---|
| Получить grounding read до factual ответа | `tool_choice`/prefetch [`commerce-trust-safety`:44-52][R-safety-skill] | mandatory memory/source order в `memory-search.md` и `research-method.md` | **Пробел:** наш агент может ответить, не вызвав read. |
| Не исполнять instruction из tool/third-party data | sanitizer + fence + cap в `Fence.fence_payload` [`fencing.py`:99-149][R-fencing] | Live `ToolResultBlock` передаётся в event как извлечённый text без общего sanitizer (`app/backend_claude.py:1284-1316`); только historical handoff помечен untrusted. | **Пробел:** prompt injection может влиять на решение до любого reviewer. |
| Дать delegate только read authority | fixed `DelegationContext`/read tools [`commerce-architecture`:66-72][R-arch] | worker/reviewer boundaries задаются ролью/prompt; filesystem sandbox отсутствует | **Пробел:** capability не урезана конструкцией. |
| Не менять live state без human mark | `apply_change` читает host-only `approved_change_ids` [`merchant/gates.py`:192-215][R-merchant-gates] | user approval — prompt gate; task record approval receipt не содержит | **Пробел:** наиболее прямое несоответствие нашему правилу «опасный запрет — только код». |
| Не писать неподходящий факт в долговременную память | единый `validate_fact`/`MemoryWriteFilter` на обоих путях [`memory.py`:183-208][R-memory] | code валидирует форму KB, а semantic eligibility решает пишущий agent | **Пробел:** poisonous/неуместный факт может стать canonical. |
| Не выйти за file ownership | Не прямой аналог; их executor вообще не выдаёт запрещённые tools/IDs | overlap reservations кодом, фактический edit boundary — injected prompt (`app/manager.py:516-524,533-572`) | **Пробел:** reservation предотвращает конфликт двух workers, но не запрещает одному писать за границей. |

## Граница необратимых действий

| Система | Что модель делает сама | Где человек/политика | Что code-enforced | Остаточный риск |
|---|---|---|---|---|
| Anthropic shopping | Ищет, выбирает ID, меняет cart, вызывает checkout presentation. | Человек размещает/оплачивает заказ в host checkout. | Backend interface не содержит payment/order method; checkout URL модель не видит [`backend.py`:44-54,120-128][R-shop-backend]. | Текст модели может ошибаться, но money path недоступен. |
| Anthropic merchant | Создаёт server-ID staged change и preview. | Portal/CLI/Managed Agents ставит approval mark; затем apply. | Provenance, current guardrails и host approval повторно проверяются в `check_apply_change` [`merchant/gates.py`:192-215][R-merchant-gates]. | `require_host_approval=False` снимает локальный mark; Managed path тогда полагается на external `always_ask` (`agent.yaml:103-110`)[R-agent-yaml]. |
| Orchestra worker | Исследует/редактирует/коммитит в isolated worktree. | Orchestrator принимает результат и вызывает merge; пользователь по процессу апрувит начало и архитектуру. | Worktree identity, bound task, target HEAD, clean tree, diff budget, pinned oracle и mapped tests проверяются merge path (`app/routes/sessions.py:1847-2009`; `app/merge_operations.py:1613-1740`; `app/workspace.py:1290-1435`). | Человеческий approval и фактическая file-boundary не имеют server receipt/enforcement; orchestrator — тоже модель и может вызвать merge после ошибочного вывода. |

**Вывод:** класс задачи один, но граница разная. У Anthropic опасная capability отсутствует у
основного агента или требует host-only bit. У нас worker отделён от main, а merge transaction
сильнее по проверке git/test состояния; однако решение «человек разрешил эту реализацию» хранится
в prompt/history, не в состоянии, которое merge обязан проверить. **CONFIRMED** — primary code с
обеих сторон.

## Проверка результата и self-judgment

| Вопрос | Anthropic blueprint | Orchestra | Вердикт |
|---|---|---|---|
| Есть ли deterministic oracle? | Да для code gates: unit tests с `FakeClient`; safety code не требует model. Собственный eval skill прямо говорит: «repo ships no eval harness» [`commerce-evals`:6-11][R-evals]. | Да: frozen acceptance command + immutable manifest проверяет platform (`app/acceptance.py:349-378`), затем mapped tests (`app/merge_operations.py:1661-1740`). | **CONFIRMED — у нас сильнее как delivery gate.** |
| Что судят? | Final tool args/state/rendered response; путь только когда он сам behavior [`commerce-evals`:44-67][R-evals]. | AC/final artifact; Phase 3 запрещает принимать child green report как acceptance (`roles/full-cycle.md:132-138`). | **CONFIRMED — совпадает.** |
| Кто судит semantic output? | В предлагаемом deployment-harness: code graders для structured fields; отдельный pinned LLM judge для rubric, parse failure отделён от agent failure [`commerce-evals`:68-78][R-evals]. | Общего semantic grader нет. Codex reviewer проверяет research/code artifact как sensor, не оценивает пользовательские ответы и не является oracle (`codex-debate/SKILL.md:13-39,209-225`). | **CONFIRMED — self-judgment не является oracle, но у нас отсутствует их отдельный semantic-judge слой.** |
| Что реально поставляется? | CI запускает pytest/repo checks, но behavioral eval datasets/runner отсутствуют; единственный файл с `*eval*` — authoring command. `.github/workflows/ci.yml:23-32` запускает только unit suite. | Acceptance runner, merge test gate и full pytest CI существуют в коде. | **CONFIRMED — «strong eval suite» статьи не является частью open blueprint.** |
| Может ли ошибочный текст пройти? | Да: `docs/safety.md:53-59` прямо ограничивает prompt-rule failure misstatement-ом, который надо исправить; до последствия его ловит только будущий eval/человек. | Да: factual/research text не имеет универсального semantic oracle; review может быть недоступен и prompt допускает `Review: none` (`codex-debate/SKILL.md:49-64`). | **CONFIRMED — общий незакрытый класс.** |

## Работа с ошибками модели

| Ошибка | Их реакция | Наша реакция | Ловится до последствий? |
|---|---|---|---|
| Невалидные tool args / JSON | Pydantic/schema failure превращается в actionable error и loop просит повторить; streamed JSON не исполняется [`execution.py`:54-61,98-103,214-223][R-exec]; [`turn.py`:247-257][R-turn]. | Tool result получает `is_error`; precise API error, retryability и unknown outcome сохраняются (`app/mcp_stdio.py:430-531`, `app/backend_claude.py:1284-1316`). | **Да**, call не выполняется; затем model может исправиться. |
| Tool/backend exception | `execute` никогда не raises в loop, возвращает unavailable/error [`execution.py`:214-223][R-exec]. | Ошибка логируется; transient provider `server_error` получает fresh-backend retry с cap 3 (`app/session_turns.py:444-487`). | **Да** для незавершённого call; нет для side effect с unknown outcome, у нас он специально помечается `outcome_unknown`. |
| Hallucinated/подложный target ID | Provenance gate блокирует до backend [`shopping/gates.py`:40-44][R-shop-gates]; [`merchant/gates.py`:192-215][R-merchant-gates]. | Merge/task refs и session identity проверяются до git mutation. | **Да** в обеих системах. |
| Превышение cap повтором/parallel call | Resulting state вычисляется под session lock [`shopping/gates.py`:86-125][R-shop-gates]. | Repo mutation lock, current target recheck, current acceptance/tests. | **Да** в обеих системах для этих seams. |
| Prompt injection из tool data | Общий sanitizer/fence/cap до модели [`fencing.py`:99-149][R-fencing]. | Для live tool results общего барьера нет; instruction просит оценивать источники. | **Нет у нас до model decision; пробел.** |
| Семантически неверный, но syntactically valid ответ | Predeploy eval/LLM judge по проектной suite; после запуска — исправление misstatement. Open repo runner не поставляет. | Frozen tests защищают кодовые эффекты; independent review защищает часть выводов; обычный текст может уйти пользователю. | **Не гарантируется** ни у них, ни у нас; у нас delivery gate сильнее для кода, у них заявлена более системная behavioral-eval дисциплина. |

## Заявлено в статье, но отсутствует или расходится с open code

| Заявление/паттерн | Проверка репозитория | Статус |
|---|---|---|
| Production agents имеют strong eval suite; статья задаёт snapshot/rubric/CI process. | [`commerce-evals`:8-11][R-evals] прямо: repo не поставляет eval harness; `find` нашёл только `plugins/commerce-builder/commands/author-commerce-evals.md`; CI — unit pytest/checks. | **CONFIRMED — aspirational/deployment-owned, не implementation code.** |
| Merchant memory нужно key by person, не account. | `MerchantSessionContext` содержит `merchant_id` и `operator`, но `memory_subject` возвращает `merchant_id` [`merchant_agent/executor.py`:133-135][R-merchant-exec]. | **CONFIRMED — прямое расхождение статьи и кода.** |
| Memory читается в три слоя. | Runtime prefetch вызывает только `tier_one`; остальное доступно через `recall_memories`. Вызова signal-relevant `search_facts` до model turn нет [`memory.py`:229-245,601-637][R-memory]. | **CONFIRMED — реализовано 2/3 слоёв.** |
| Extractor работает в separate thread/process. | Demo host делает `asyncio.create_task` в текущем event loop [`host.py`:77-85,185-203][R-host]. | **CONFIRMED — асинхронность есть, изоляции thread/process нет.** |
| Safety/grounding единообразна по runtimes. | `docs/safety.md:27,31,33` перечисляет исключения: Managed Agents без forced grounding; SDK analysis без query budgets; Managed memory без post-turn extraction. | **CONFIRMED — shared executor унифицирует tool-call gates, но не turn-level rules.** |
| Production identity/auth. | Reference сам признаёт: examples без auth, deployment обязан добавить auth/rate limits/business rules [`docs/safety.md`:61-86][R-safety]. | **CONFIRMED — честно обозначенная deployment boundary, не готовый production guardrail.** |

## Findings и confidence

1. **Самая важная дельта — code-enforced provenance/fencing/host approval. CONFIRMED:** статья и
   reference implementation сходятся, а локальный source scan показывает у нас code-equivalent
   только для merge/test/session state; live tool-content, human approval receipt, read-only delegate
   и source-first grounding остаются prompt-owned.
2. **Их общий принцип совпадает с нашим выстраданным критерием. CONFIRMED:** consequential failure
   отсекается executor/backend-ом; prompt-only оставлены правила, нарушение которых даёт misstatement,
   а не live mutation (`docs/safety.md:42-59`).
3. **Orchestra сильнее blueprint в delivery verification. CONFIRMED:** platform, не worker, запускает
   frozen oracle и mapped tests до merge; open blueprint поставляет unit tests, но не behavioral eval
   harness/dataset.
4. **Blueprint нельзя читать как полностью реализованный эталон. CONFIRMED:** 5 конкретных
   article↔code расхождений приведены выше; это не умаляет архитектурных паттернов, но меняет степень
   доказанности.
5. **Большая часть non-safety архитектуры совпадает по смыслу. CONFIRMED:** persistent context,
   skills, server-owned state, thin tools, streaming, result-oriented tests и incident-derived cases
   уже есть; различия single-agent/multi-agent объясняются разным типом разговора.

## Review outcome

- Route: Luna completeness/falsification, 2 prose rounds (`review-research-luna.md`).
- Round 1 состоялся: reviewer привёл точную строку из артефакта и вердикт `Needs work — 1 blocking,
  4 suggestions`. Blocking по безусловному internal-auth claim исправлен после code check и live
  measurement; четыре suggestions также внесены.
- Round 2 текстом объявил все 5 findings `FIXED` и `APPROVED`, но его доказательная цитата заменила
  `;` из артефакта на `.`, поэтому по canonical `codex-debate` evidence contract финальный verdict
  не засчитывается. Третий раунд запрещён потолком для прозы. Итоговая честная формулировка:
  **review состоялся, открытых findings reviewer не назвал, но доказанного финального verdict нет**.

## Counter-evidence и границы вывода

- Reference repo прямо называет себя blueprint и перекладывает auth, business rules, rate limits,
  credentials и approval surface на deployment [`docs/safety.md`:61-86][R-safety]. Поэтому отсутствие
  готового auth/eval/canary кода не доказывает, что production deployments Anthropic этого не имеют.
- Их open code действительно закрывает tool-call guardrails на трёх runtime paths через один executor
  [`docs/safety.md`:12-15][R-safety]; исключения относятся к turn-level grounding/extraction/analysis,
  а не опровергают provenance/caps/approval.
- Orchestra ownership/approval/review rules имеют многократную incident evidence в KB и prompt tests;
  «prompt-only» не означает «никогда не работает». Оно означает отсутствие механической гарантии при
  одном bad sample — именно такой стандарт задаёт статья для необратимых действий.
- Нет эксперимента на живой модели: задача заказана как source/code research, поэтому claims о quality,
  latency и их внутренних процентах не перепроверялись. Числа статьи здесь не используются для выбора.
- Срез привязан к двум SHA/датам выше; новый commit Anthropic или Orchestra может изменить отдельную
  ячейку.

## Affected files, risks, edge cases

- Изменены только `docs/tasks/507/research.md`, `docs/tasks/507/review-research-luna.md` и
  `docs/kb/agent-guardrails.md`; `app/`, tests, prompts и чужие KB topics не трогаются.
- Риск неправильного обобщения: commerce UI/payment guardrails не следует автоматически считать
  нужными Orchestra; сравнивался инженерный класс необратимого действия, не предметная сущность.
- Риск ложного «нет»: absence-claims ограничены текущим public tree и текущим Orchestra checkout;
  они помечены `LIKELY`, когда нет прямого self-declaration источника.
- Открытый вопрос для возможной будущей фазы — какие из четырёх consequential prompt-only seams
  пользователь вообще захочет обсуждать; этот документ внедрение не предлагает.

## Mechanical completeness checks

- Article body получен raw `curl`, затем локально преобразован `pandoc`; перечень сверён по всем
  headings и bullet groups частей Architecture / Latency & cost / Production.
- Canonical author-side inventory дополнительно сверён по 12 строкам
  `plugins/commerce-builder/commands/review-commerce-agent.md:20-32,49-62` [R-review-command].
- Guardrail inventory: 20/20 строк `docs/safety.md:19-40` присутствуют в таблице G1–G20.
- Eval absence: `find <repo> -type f ( -iname '*eval*' -o -iname '*rubric*' -o -iname '*judge*' )`
  вернул только `plugins/commerce-builder/commands/author-commerce-evals.md`.
- Article/code contradictions проверены по вызывающим, а не по README: merchant `memory_subject`,
  `tier_one`/`recall_memories`, `spawn_background`, runtime exception rows.
- Reviewer proof проверен нормализованным exact-match: Round 1 quote `True`, Round 2 quote `False`.

## Sources

1. [Claude blog: “A guide to the anatomy of effective commerce agents”][B] — primary source,
   raw HTML fetched 2026-09-03; published 2026-09-02.
2. [anthropics/commerce-agents at `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf`][R-root] — primary
   implementation source, fetched with `gh api` 2026-09-03.
3. Current Orchestra source at `bc86dfcda19ab5d1096f07955ee0b8e41e1ddda1` — primary local source;
   exact paths/lines are inline.

[B]: https://claude.com/blog/the-anatomy-of-effective-commerce-agents
[R-root]: https://github.com/anthropics/commerce-agents/tree/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf
[R-arch]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/skills/commerce-architecture/SKILL.md
[R-evals]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/skills/commerce-evals/SKILL.md
[R-safety-skill]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/skills/commerce-trust-safety/SKILL.md
[R-cache]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/skills/commerce-prompt-caching/SKILL.md
[R-ui]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/skills/commerce-ui-tools/SKILL.md
[R-safety]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/docs/safety.md
[R-exec]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/commerce-common/commerce_common/execution.py
[R-fencing]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/commerce-common/commerce_common/fencing.py
[R-turn]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/commerce-common/commerce_common/turn.py
[R-memory]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/commerce-common/commerce_common/memory.py
[R-shop-gates]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/shopping-agent/core/shopping_agent/gates.py
[R-shop-backend]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/shopping-agent/core/shopping_agent/backend.py
[R-merchant-gates]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/merchant-agent/core/merchant_agent/gates.py
[R-changes]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/merchant-agent/core/merchant_agent/changes.py
[R-merchant-exec]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/merchant-agent/core/merchant_agent/executor.py
[R-merchant-types]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/merchant-agent/core/merchant_agent/types.py
[R-host]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/examples/demo_common/host.py
[R-agent-yaml]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/merchant-agent/managed-agents/merchant-agent/agent.yaml
[R-review-command]: https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/plugins/commerce-builder/commands/review-commerce-agent.md
