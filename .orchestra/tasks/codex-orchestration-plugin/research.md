# Исследование Codex-Orchestration plugin

Дата проверки: 2026-07-18
Версия плагина: `0.5.1`, commit `df1e3da61fcca1b6134fdc1ac1a1f3100d403757`

## Вопрос

- **Контекст:** Orchestra запускает отдельные Claude/Codex-сессии в изолированных worktree; сейчас orchestrator — Claude Opus 4.6, обычный worker и full-cycle — GPT-5.6 Sol.
- **Изменение под проверкой:** установить Codex-Orchestration внутрь Codex-воркеров и/или перенести его механику Planner/Advisor/Executor в Orchestra.
- **Baseline:** текущая межсессионная схема Orchestra без внутренней делегации Codex-воркера.
- **Результат:** подтверждённая механика маршрутизации, совместимость с `CodexBackend`, измеренные ограничения и практическое решение «внедрять / пилотировать / не внедрять».

## Гипотезы и фальсификаторы

### H1 — плагин является политикой поверх native Codex subagents, а не отдельным оркестратором

Плагин направляет same-provider роли через model-visible routing hints и аргументы native `spawn_agent`; Fable вызывает через отдельный MCP→Claude CLI bridge. Он не перехватывает каждый model call и не реализует собственный scheduler.

**Что опровергнет:** собственный runtime loop, proxy каждого Codex model call или механическое принудительное выполнение Planner→Advisor→Executor независимо от решения root-модели.

### H2 — Fable Advisor технически можно вызвать из Codex-воркера Orchestra, но установка плагина «как есть» не является бесплатной интеграцией

`codex exec` способен загрузить plugin/MCP и вызвать Fable через установленный `claude` CLI, однако глобальная Codex-конфигурация, отсутствие caller identity и пересечение с Orchestra MCP/agent policy создают дополнительные риски.

**Что опровергнет:** `codex exec` не загружает plugins/subagents, `CodexBackend` несовместим с нужной конфигурацией либо Fable bridge нельзя подтвердить на текущем CLI без глобальной мутации.

### H3 — повышение effort для всех обычных Sol workers не оправдано одним лишь увеличением подписного лимита

`medium` остаётся разумным baseline для чётких задач; `xhigh` сохраняется для full-cycle. Более высокий allowance снимает квотный запрет, но не устраняет рост latency и токенов.

**Что опровергнет:** сопоставимый benchmark Orchestra-задач покажет устойчивый рост качества/успешности при `high` или `xhigh` без неприемлемого роста latency/usage.

## Экспериментальный протокол (зафиксирован до запуска)

Эксперименты выполняются только в clone под `/tmp` и изолированном `CODEX_HOME`; пользовательская конфигурация не меняется.

1. **Контракт и lifecycle:** запустить upstream unit/lifecycle/release checks. **Pass:** все тесты завершаются успешно на Python ≥3.11 и Codex CLI `0.144.5`.
2. **Native configuration surface:** применить setup в одноразовый `CODEX_HOME`. **Pass:** plugin устанавливается, App Server принимает четыре routing-поля, status видит effective policy; исходный `~/.codex` не меняется.
3. **Fable bridge:** в той же изоляции проверить `status` без model call и выполнить один короткий `review_plan`. **Pass:** bridge подтверждает first-party login, возвращает `PLAN_APPROVED|PLAN_REVISE`, effective effort и runtime `used_models`, содержащий `claude-fable-5`; неизвестные модели/ошибки должны fail closed.
4. **Exploratory effort benchmark:** дать Sol один и тот же набор из двух коротких code-review задач на `medium`, `high` и `xhigh` (по одному прогону; `--ephemeral`, без repo/config/tools). Шесть заранее заданных критериев: (A) prefix-collision, symlink escape, canonical containment fix; (B) stderr-pipe deadlock, слишком поздний memory cap, cleanup дочернего процесса при cancellation. Для каждого уровня записать score `/6`, wall time и reported input/cached/output tokens. **Рекомендовать blanket-повышение worker effort только если более высокий уровень прибавит ≥2 корректных критерия и не увеличит одновременно latency или output usage более чем в 2 раза.** Один прогон на комбинацию — ориентир, не статистическое доказательство.

Эти проверки доказывают работоспособность механизма, но **не** claims `2×` и `−40%`: для них заранее требуются опубликованный corpus задач, baseline, число прогонов, wall-clock/usage raw data и разброс. Без этого verdict — `UNVERIFIABLE`.

## Findings

### 1. Что это за плагин

**CONFIRMED — исходники плагина + официальная документация + локальный runtime test.**

Codex-Orchestration — не новый scheduler и не proxy вокруг каждого model call. Это устанавливаемый Codex plugin, который упаковывает:

- skill с протоколом Planner → Advisor → Executor;
- конфигуратор native Codex multi-agent v2;
- custom-agent TOML для provider-pinned ролей;
- локальный MCP bridge для Claude Fable 5 [P1][P2][P3][P4].

Официальная модель Codex plugin совпадает с этой структурой: обязательный `.codex-plugin/plugin.json`, рядом могут лежать `skills/`, `.mcp.json`, hooks и assets; workflow задаёт skill, live tools — MCP [A1]. Native Codex subagents являются отдельными agent threads, могут иметь собственные model/effort settings и потребляют дополнительные токены [A2].

#### Same-provider Planner/Advisor/Executor: prompt-guided tool routing

Для моделей текущего Codex provider конфигуратор записывает четыре поля в user config через Codex App Server:

1. `hide_spawn_agent_metadata = false` — раскрывает `model`, `reasoning_effort`, `agent_type` у spawn tool;
2. `tool_namespace = "agents"` — делает расширенный spawn schema вызываемым на протестированном v2 client;
3. `multi_agent_mode_hint_text` — добавляет root/child policy;
4. `usage_hint_text` — кладёт точные маршруты ролей прямо в описание spawn tool [P3][P5].

Root Codex затем **сам решает**, создавать ли child. Если создаёт, он передаёт механические аргументы вроде `model="gpt-5.6-luna"`, `reasoning_effort="xhigh"`, `fork_turns="none"`. Поэтому это сильнее обычного prompt preference: текущий tool валидирует точный model/effort route. Но это не engine-level `executor_model`: root может не делегировать, а setup не доказывает effective child identity будущего запуска [P2][P5].

Итого: **маршрутизация одновременно prompt- и tool-based**. Политика выбора/цикл ролей — prompt routing; выбранный same-provider child — native tool routing с явными аргументами.

#### Claude Fable 5: MCP tool → headless Claude CLI

Fable не маскируется под OpenAI model и не запускается через `spawn_agent`. Root вызывает один из MCP tools `create_plan`, `revise_plan`, `review_plan`; Python server запускает:

```text
claude -p --model claude-fable-5 --effort <saved> --safe-mode
       --tools "" --permission-mode dontAsk --no-session-persistence
       --output-format json
```

Bridge удаляет API-key/provider override variables, требует first-party `claude.ai` login, проверяет первый сигнал (`PLAN_DRAFT`, `PLAN_REVISION`, `PLAN_APPROVED|PLAN_REVISE`) и fail-closed сверяет `modelUsage`: primary должен быть `claude-fable-5`, допустим только явно allowlisted helper [P4]. Это **MCP tool routing + subprocess bridge**, а не Codex subagent.

Пятираундовый Advisor loop, plan version и findings ledger держит root по инструкции. MCP механически ограничивает поверхность операции и формат ответа, но не реализует сам orchestration loop [P2][P4].

### 2. Насколько это похоже на Orchestra

**CONFIRMED — локальный код Orchestra и plugin source.**

Идея одинаковая: дорогая/сильная модель принимает решения, специализированная модель делает ограниченную работу. Уровень реализации разный:

| Свойство | Codex-Orchestration | Orchestra сейчас |
| --- | --- | --- |
| Root | model текущего Codex task | отдельная Opus orchestrator session |
| Child | native Codex agent thread или MCP-вызов Fable | отдельный CLI process/session |
| Изоляция записи | общий workspace/sandbox parent; границы в packet/prompt | отдельный git worktree и branch |
| Маршрут | policy hint + spawn model/effort args | `manager.py` фиксирует model/runtime/effort при создании session |
| Состояние | Codex thread + user config | SQLite, Task Manager, inbox, dashboard/TG, resumable worker |
| Контроль результата | root Codex интегрирует handoff | Opus принимает отчёт/артефакты и merge |

`manager.py` берёт effort из role config, а `runtime_registry.py` передаёт его в `CodexBackend`; backend запускает `codex exec -m <model> -c model_reasoning_effort=<effort>` и отдельно инжектит Orchestra MCP per worker [O1][O2][O3][O3a]. Это уже более жёсткий outer-level routing, чем plugin policy.

Следовательно, Executor-часть плагина в основном дублирует Orchestra. Потенциально новое для нас — **узкий cross-model Advisor внутри Sol turn**, когда нужен второй взгляд без отдельного долгоживущего worker/worktree.

### 3. Можно ли использовать внутри Codex-воркера Orchestra

**Технически да; включать весь plugin глобально сейчас не следует.**

Подтверждённый путь:

- текущий Codex CLI `0.144.5` принимает native policy;
- `CodexBackend` наследует process environment/global Codex config и умеет передавать дополнительные STDIO MCP server definitions через `-c mcp_servers.*` [O1];
- реальный headless Fable call с теми же flags успешно сработал; затем именно `fable_advisor_mcp.py.review_plan()` прочитал isolated saved route и вернул подтверждённый runtime identity [M1].

Но установка «как в README» пишет personal user config и должна загружаться в новом task [P1][P2]. У Orchestra сейчас нет per-role plugin home/config: все новые Codex workers на машине разделят эту policy. Существующие resumable threads не получат уже скомпилированные plugin instructions задним числом: `CodexBackend` добавляет system/MCP `-c` overrides только в свежий `codex exec`, а `exec resume` их не повторяет [O1]. Project-scoped `.codex/agents` теоретически могли бы дать более узкую route pin, но текущий worktree config их не копирует и это отдельная реализация, а не готовая возможность [O3]. Поэтому full-plugin setup не является локальным переключателем одного Sol worker.

Есть четыре интеграционных конфликта:

1. `pipelines/default/prompts/base.md` критически запрещает built-in Agent, потому что он обходит Orchestra, тогда как `full-cycle.md` ниже рекомендует built-in Agent для ephemeral fan-out [O4][O5]. Это уже внутреннее противоречие prompt architecture; Executor routing плагина добавит третий маршрут.
2. Plugin меняет native spawn namespace на `agents`; Orchestra prompt и текущий backend рассчитаны на Orchestra MCP `spawn_worker`, а не на plugin-owned internal executors [P3][O1][O4].
3. Codex subagents наследуют permission mode parent [A2]. `CodexBackend` запускает root с `--dangerously-bypass-approvals-and-sandbox`; внутренний executor получил бы ту же широкую live policy в том же worktree [O1].
4. **LIKELY:** `CodexBackend.events()` не имеет явной ветки для native subagent lifecycle items, поэтому dashboard/DB могут не получить ожидаемую child telemetry. Это вывод из event parser, не live-verified факт; cost aggregation также требует отдельной проверки. Fable-as-MCP — другой случай: обычный `mcp_tool_call` parser уже отображает его tool call [O1].

### 4. Проверка заявлений `2× быстрее` и `40% меньше лимитов`

#### Claim: «до 2× быстрее»

**Verdict: ❓ UNVERIFIABLE.** README прямо называет число target, а не guarantee, и ограничивает его задачами с независимыми параллельными slices [P1]. Во всём repository, history и tests нет benchmark corpus, baseline, числа прогонов, wall-clock raw data или variance [M2]. Официальная документация подтверждает лишь качественный механизм: независимые subagents могут экономить wall time, но каждый делает собственную model/tool работу и увеличивает token usage [A2].

#### Claim: «примерно на 40% реже упираться в premium limits»

**Verdict: ❓ UNVERIFIABLE.** Нет published allowance measurements. Внутри skill есть отдельная арифметическая иллюстрация: если 20% сопоставимого token mix остаётся на Sol, а 80% идёт в Luna с условным весом 20% от Sol, weighted credits равны `0.20 + 0.80×0.20 = 0.36`, то есть около 64% меньше **до overhead** [P2][P5]. Это не доказывает 40% raw-token, five-hour или weekly-limit saving; сам плагин запрещает так интерпретировать число.

### 5. Effort levels после перехода на Codex Pro $100

**CONFIRMED для документации; LIKELY для решения по Orchestra из-за малого benchmark.**

OpenAI описывает Pro from $100 как tier с 5× или 20× usage против Plus. Это увеличение allowance, не обещание 5× качества reasoning одного turn [A3]. Официальная рекомендация: использовать минимальный effort, который даёт нужный результат; `medium` — balanced default, `high/xhigh` — сложные многошаговые задачи, причём higher effort увеличивает latency и token usage [A2][A4].

Текущая policy Orchestra уже соответствует этому разделению: `worker=medium`, `full-cycle=xhigh` [O3]. Малый exploratory benchmark не дал оснований поднимать обычного worker; он **не проверял** сложные full-cycle задачи и поэтому не доказывает оптимальность `xhigh` для них:

| Кейс | Effort | Score | Wall | Usage из `turn.completed` | Результат |
| --- | --- | ---: | ---: | --- | --- |
| Path containment | medium | 3/3 | ≤60 s | input 18,636; output 664; reasoning 300 | все критерии + полезный TOCTOU counterpoint |
| Path containment | high | 3/3 | ≤90 s | input 16,517; cached 9,984; output 2,476; reasoning 2,070 | тот же score; output 3.7×, reasoning 6.9× |
| Path containment | xhigh | n/a | >300 s | output потерян при reconnect | practical latency threshold уже нарушен; run исключён из quality comparison |
| Async subprocess | medium | 3/3 | 134.2 s | input 19,199; cached 18,176; output 1,600; reasoning 992 | все критерии |
| Async subprocess | high | n/a | 203.5 s | `exit 1`, usage/result отсутствуют | не даёт evidence улучшения |

Один прогон и два synthetic cases не оценивают качество на больших реальных refactor. Они показывают только отсутствие причины менять default вслепую. Новый тариф позволяет запускать больше сложных turns, но не отменяет latency/overthinking tax.

## Экспериментальные результаты

### M1 — compatibility и Fable bridge

- Upstream: `189 tests`, `24.854 s`, `OK`; lifecycle smoke установил `0.5.0`, обновил до `0.5.1`, проверил cache, native/custom setup/status/cleanup; release metadata check прошёл.
- Isolated native setup (`/tmp`, реальный Codex CLI `0.144.5`): `Executor: gpt-5.6-sol@xhigh`, `Planner: root`, `Advisor: Claude Fable 5 high`; `--status --require-effective` → `installed and effective`; затем `disable --apply` восстановил policy.
- Claude auth probe: `loggedIn=true`, `authMethod=claude.ai`, `apiProvider=firstParty` (account metadata не записывались).
- Прямой no-tools Fable call: `PLAN_APPROVED`; `used_models=[claude-fable-5, claude-haiku-4-5-20251001]`; `duration_ms=13,820`; `num_turns=1`; reported `total_cost_usd=0.042307` (справочное поле CLI, не фактический расход subscription).
- Вызов через upstream `review_plan()` с isolated saved state: `PLAN_APPROVED`, `model=claude-fable-5`, `effort=high`, тот же exact `used_models` allowlist.

### M2 — maturity и claims audit

- Repository создан `2026-07-10`; на `2026-07-18` GitHub API показывал 384 stars, 29 forks и 8 open issues/PRs; default branch HEAD — `df1e3da...`, manifest version `0.5.1`.
- Git tags и GitHub Releases отсутствовали, хотя собственный production-readiness audit требует signed `v0.5.1` tag/release [P7].
- Open issue #9 воспроизводит ещё одну шероховатость `0.5.1`: README пишет `/codex-orchestration`, но CLI `0.144.4` не регистрирует такой slash command; работал explicit skill label `$codex-orchestration:codex-orchestration` [P6].
- Поиск `benchmark|2x|40%|measurement|wall-clock` нашёл marketing copy и contract tests на наличие этой copy, но не исходные измерения.

## Counter-evidence

- Плагин существенно аккуратнее типичного prompt-only proof of concept: App Server writes, rollback/restore state, compatibility probes, exact runtime-model allowlist и 189 passing tests снижают риск конфиг-порчи [P3][P4][M1]. Это аргумент **за** ограниченный pilot.
- Native model/effort args означают, что same-provider route не сводится к «попросили модель притвориться Luna». Tool acceptance механически валидирует route. Но root всё ещё решает, делегировать ли, а setup не подтверждает future effective child identity [P5].
- Fable Advisor действительно даёт cross-family critique и механически не имеет file/shell tools. Это полезнее внутреннего Sol→Sol review. Однако Claude Max теперь более дефицитен, а Orchestra уже имеет Opus root и обязательный `codex-debate`; польза третьего review layer пока не измерена.
- Внешний Orchestra worker тяжелее внутреннего subagent: process/worktree/Task Manager overhead реален. Для короткого read-only анализа MCP Advisor может быть быстрее и чище по контексту. Это не оправдывает перенос executor ownership внутрь Codex.
- Effort benchmark мал и частично пострадал от reconnect/одного `exit 1`; он не доказывает превосходство `medium`, только не находит evidence для blanket-повышения.
- Fresh GPT-5.5 adversarial review не опроверг основной вывод, но нашёл два blocker в первой версии pilot: MCP нельзя hot-add на `exec resume`, а read-only обеспечивается bridge, не произвольным STDIO MCP/Orchestra sandbox. Оба исправлены в рекомендациях; полный разбор — `codex-review-research.md`.

## Рекомендации

### Внедрять сейчас

1. **Оставить `worker=medium`.** `full-cycle=xhigh` пока сохранить как существующую policy, а не как доказанный результат этого benchmark. Новый Pro allowance использовать для большего числа сложных задач, а не для автоматического увеличения effort каждого turn.
2. **Сделать отдельный A/B audit effort на реальных задачах**, прежде чем менять pipeline: минимум 20 сопоставимых worker tasks (`medium` vs `high`) и отдельно full-cycle (`high` vs `xhigh`); измерять first-pass AC, test failures, Codex blockers, rework turns, wall time и output/reasoning tokens.
3. **Исправить внутреннее противоречие `base.md` vs `full-cycle.md` про built-in Agent** независимо от решения по plugin. Один task должен иметь один маршрут делегирования.

### Пилотировать, но не включать по умолчанию

4. **Пилот только Fable Advisor, без Planner/Executor routing.** Preload MCP bridge при создании нового `full-cycle` thread; mid-thread добавление на `exec resume` сейчас не работает. «Read-only» должен механически обеспечивать именно audited bridge (`--tools ""`, no persistence, bounded schema), потому что произвольный STDIO MCP и Orchestra sandbox сами этого не гарантируют.
5. Лучше не ставить plugin policy глобально. Взять MIT-licensed bridge/protocol как reference, провести security review и подать server через существующий per-worker `_mcp_config_args()` при spawn; так Orchestra сохранит свой scheduler, worktree ownership и telemetry. Можно добавить Orchestra worker identity в server env — отсутствие caller identity является границей upstream bridge, а не обязательной границей нашей реализации.
6. Pilot gate: 15–20 реальных plans; Fable должен **заменять/конкурировать с**, а не добавляться поверх текущего `codex-debate`. Успех — меньше blocking findings на implementation review/test failures при приемлемых +latency и расходе Claude allowance.

### Не внедрять

7. **Не включать plugin Executor/Planner policy внутри всех Sol workers.** Она дублирует outer Orchestra, конфликтует с tool-routing prompts и размывает ownership/telemetry.
8. **Не менять `tool_namespace` глобально на `agents`** до отдельного end-to-end теста `CodexBackend` JSONL, usage accounting, interrupt/reconnect и dashboard subagent visibility.
9. **Не использовать `2×` и `−40%` для решения или документации Orchestra.** До опубликованного/собственного benchmark это targets, не evidence.

## Итоговое решение

**Не интегрировать Codex-Orchestration целиком.** Архитектурно Orchestra уже реализует ту же идею на более управляемом уровне. Единственная перспективная часть — Fable как короткий Advisor внутри заранее подготовленного нового Sol full-cycle thread; её expected value ещё не доказан и должен пройти security review плюс A/B против `codex-debate`.

## Затрагиваемые файлы Orchestra, риски и edge cases

- `app/backend_codex.py` — потенциальный per-worker MCP bridge, JSONL subagent telemetry и usage accounting; production change сейчас не делался.
- `app/runtime_registry.py` — место сборки Codex backend/skills; его `ORCHESTRA_RUNTIME_PLUGINS` относится к backend runtimes, а не к Codex plugins.
- `app/manager.py` — role → effort/session routing и MCP config.
- `pipelines/default/pipeline.yaml` — текущие `medium/xhigh`; менять только после A/B.
- `pipelines/default/prompts/base.md`, `roles/full-cycle.md` — конфликт built-in Agent policy.

Риски pilot: Fable helper model ID изменится и bridge fail-closed остановит review; first-party Claude login/limit недоступен; global proxy должен наследоваться; caller identity нужно добавить нашей обёрткой; prompt injection из plan packet; input bound; extra latency; duplicate reviewer loops; existing Codex threads не hot-load новые skills/config; native internal-subagent usage может не попасть в текущую Orchestra telemetry.

## Источники

### Primary external

- [P1] [Codex-Orchestration README, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/README.md) — product claims, setup, boundaries. Evidence tier: primary source (author repository).
- [P2] [Codex-Orchestration skill contract, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/plugins/codex-orchestration/skills/codex-orchestration/SKILL.md) — routing protocol, role loop, truthful savings language. Tier: primary source.
- [P3] [Native routing configurator, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/plugins/codex-orchestration/skills/codex-orchestration/scripts/configure_native_routing.py) — exact fields/App Server writes. Tier: executable primary source.
- [P4] [Fable Advisor MCP bridge, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/plugins/codex-orchestration/skills/codex-orchestration/scripts/fable_advisor_mcp.py) — exact subprocess and validation. Tier: executable primary source + reproduced live.
- [P5] [Provider/model routing boundaries, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/plugins/codex-orchestration/skills/codex-orchestration/references/providers-and-models.md) — author capability matrix and limitations. Tier: primary author documentation, runtime-specific claims treated cautiously.
- [P6] [Issue #9: slash command not registered](https://github.com/Cjbuilds/Codex-Orchestration/issues/9) — independent reproduction on CLI `0.144.4`. Tier: single external report; not reproduced here.
- [P7] [Production-readiness audit, commit `df1e3da`](https://github.com/Cjbuilds/Codex-Orchestration/blob/df1e3da61fcca1b6134fdc1ac1a1f3100d403757/docs/production-readiness-audit.md) — known limitations/release requirements. Tier: primary self-audit.
- [A1] [OpenAI: Build plugins](https://learn.chatgpt.com/docs/build-plugins) — official plugin structure and distribution. Tier: authoritative primary documentation, fetched in current Codex manual.
- [A2] [OpenAI: Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) — native subagent model, custom agents, permissions, token/latency caveats. Tier: authoritative primary documentation.
- [A3] [OpenAI: Codex pricing](https://learn.chatgpt.com/docs/pricing) — Pro allowance tiers. Tier: authoritative primary documentation.
- [A4] [OpenAI: Models](https://learn.chatgpt.com/docs/models) — model/effort selection guidance, included in fetched Codex manual. Tier: authoritative primary documentation.

### Local Orchestra sources

- [O1] `app/backend_codex.py:130-352, 427-458` — subprocess flags, resume boundary, effort, per-worker MCP and event parser.
- [O2] `app/runtime_registry.py:200-264` — skills/MCP/backend construction and Codex capabilities.
- [O3] `pipelines/default/pipeline.yaml:48-76` — `worker=medium`, `full-cycle=xhigh`.
- [O3a] `app/manager.py:503-516` — role effort сохраняется в session; default worktree copies заданы в `pipeline.yaml:9-13`.
- [O4] `pipelines/default/prompts/base.md:43-49` — critical ban on built-in Agent.
- [O5] `pipelines/default/prompts/roles/full-cycle.md:157-188` — conflicting built-in Agent recommendation.

### Direct measurements

- [M1] Current host: Codex CLI `0.144.5`, Claude Code `2.1.197`, Python `3.13.7`; isolated plugin tests and live Fable calls recorded above. Tier: direct reproducible measurement.
- [M2] Git clone/GitHub API/repository-wide search on 2026-07-18; commit and maturity data recorded above. Tier: direct measurement of current repository state.
