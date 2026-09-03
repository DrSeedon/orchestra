# #308 — DeepSeek Harness: проверка подлинности и применимости для Orchestra

Дата среза: **17 августа 2026 года**. Исследование остановлено на Phase 1; изменений продукта и интеграции не делалось.

## Вопрос

- **Контекст:** DeepSeek опубликовал DeepSeek Harness (DSH) с тезисом «Everything is a Plugin»; на присланном скриншоте репозиторий показывает примерно 141 тыс. stars.
- **Изменение под проверкой:** взять DSH целиком, подключить sidecar либо перенести отдельные механизмы в Orchestra.
- **База сравнения:** текущая Orchestra на коммите `27a83859dcc10292ae5d287a6e8da73f01b928a3` — Python/FastAPI, persistent CLI workers, SQLite control plane, Telegram, worktrees, subscriptions и semantic memory.
- **Решающие исходы:** подлинность и зрелость; воспроизводимый запуск; реальные auth/provider paths; устойчивость persistence/orchestration; security boundary; функциональный паритет; стоимость интеграции. Итоговая шкала: `FULL` / `SLICE` / `REJECT`.

## Гипотезы и фальсификаторы

1. **H1 — SLICE:** DSH содержит зрелые архитектурные идеи, но целиковая интеграция не окупается из-за несовпадения control plane, auth и persistence. Неверно, если DSH уже закрывает consumer subscriptions, persistent workers, durable jobs, remote auth, Telegram/worktrees/memory и стабильно устанавливается заявленной командой.
2. **H2 — FULL:** DSH — готовая более сильная основа для замены Orchestra. Неверно, если релиз preview/RC, обязательные функции Orchestra отсутствуют или миграция требует переписать control plane.
3. **H3 — REJECT:** это маркетинговый/поддельный проект без работающего продукта. Неверно, если официальный org/repo/npm совпадают, код содержателен, архитектурные claims подтверждаются исходниками, а опубликованный Web UI реально стартует.

Результат: **H1 выдержала проверку; H2 и H3 опровергнуты.**

## Метод и границы

Проверены GitHub REST API, npm registry, официальный исходный код на SHA `47f943859bef60e4160492346772ded9b24f765a`, Cordis и paper, опубликованный npm tarball, сгенерированная реальная конфигурация Web profile и текущий исходный код Orchestra. README использовался только как заявка; ключевые утверждения перепроверялись кодом или probe.

Установка выполнялась только в disposable ext4-каталоге `/var/tmp/dsh308.ayJak0` с очищенным `env -i`, отдельными `HOME`, `DSH_HOME`, npm/pnpm cache и prefix. Глобальная установка, пользовательские credentials, Orchestra `.venv`, конфиги и сервисы не затрагивались. Нормализованная машинно-читаемая сводка чисел, критериев, команд и hashes: [evidence.json](evidence.json). Это не полный raw-log archive: disposable logs перечислены с hashes и могут исчезнуть после reboot.

## Вердикт

> **SLICE — средняя уверенность именно в ROI slices; высокая уверенность в отказе от FULL и REJECT. Не принимать DSH/Cordis целиком и не подключать Web sidecar. Три идеи допускаются только как измерительные пилоты, а не как уже одобренные интеграции.**

DSH подлинный, большой и технически содержательный; `REJECT` был бы ошибкой. Но на дату среза это опубликованный четыре дня назад developer preview: только RC-пакеты, ноль GitHub Releases и tags и явное предупреждение о breaking changes. Точная README-команда всё же подняла Web UI через 509 секунд; более ранние отличавшиеся pinned/help probes дали смешанные cold-install outcomes, а не опровергли quick start. Главный model route требует API key. Pi-ai catalog содержит subscription-oriented protocols, но DSH не предоставляет встроенный OAuth login/store для них; persistent Claude.ai/ChatGPT/DeepSeek subscription worker route не найден. Отдельные Codex/Claude Code bridges используют native host auth, отсутствуют в default composition и остаются one-shot. Это не замена persistent subscription workers Orchestra.[1][2][3][M1][M2][M4][M5][M6]

## 1. Подлинность, возраст, популярность и maintainers

### Скриншот и официальный источник

Присланный файл — JPEG/JFIF 1280×1120, SHA-256 `676563e14f792cf42b326bd3124e8b67370b0d0822f5ab1f7d14af9f440aec76`. На нём видны GitHub organization DeepSeek, 36 repos, 102k followers, pinned `deepseek-harness`, 141k stars и 14.3k forks. Live API в момент среза дал 36 repos, 101,764 followers, 141,869 stars и 14,400 forks; roundings совпадают.[2][3][M1]

Это **сильное подтверждение**, что изображён реальный официальный репозиторий, но не криптографическая экспертиза пикселей: скриншот сам по себе не доказывает происхождение и может быть отредактирован. Отдельного текста «поста» на изображении нет — это экран organization/repository.

| Факт на 17.08.2026 | Проверено |
|---|---:|
| GitHub owner | `deepseek-ai`, type `Organization` |
| Repo создан | 2026-08-13 11:56:32 UTC |
| Stars / forks / watchers | 141,869 / 14,400 / 586 |
| Public repos / org followers | 36 / 101,764 |
| Default branch / archived | `master` / no |
| License | MIT, DeepSeek © 2026 |
| GitHub Releases / tags | 0 / 0 |
| Issues | выключены; Discussions включены |

**CONFIRMED — tier 2 primary:** GitHub API и файл LICENSE в официальном snapshot.[2][3][4]

### Возраст и реальная activity

GitHub repo object был публично создан 13 августа, но достижимая импортированная история начинается коммитом `b67e81ac...` от 10 июня — примерно за 64 дня до публикации. Commit pagination показывает 12,293 reachable commits, из них 3,638 с 1 августа; последний default-branch commit на момент среза — `47f943...` от 13 августа, merge публикации DSH family. Weekly API сообщает 11,792 commits за недели 7 июня — 9 августа; это другая статистическая агрегация и она не обязана равняться pagination count.[5][M1]

Top contributors: `tianyicui` 5,235; `LegGasai` 1,361; `imccyu` 1,168; далее `Chinesezjc` 587, `turtle1999` 585, `hypatiamay` 490, `CreatixChu` 481 и `kermanx` 477.[6]

**CONFIRMED — tier 2 primary:** это не пустой freshly generated repo; активность и авторы получены из GitHub API. При этом «возраст продукта» нельзя приравнивать к возрасту public repo: код разрабатывался до публичного открытия.

### npm и maintainers

`@deepseek-ai/dsh` создан 10 августа. В registry шесть версий, и все pre-release: `0.0.1-rc.1`, `.2`, `.5`, `0.1.0-rc.2`, `.3`, `.6`; `latest=next=0.1.0-rc.6`. Maintainer handles: `imccyu`, `tianyicui-deepseek`. В published manifest: MIT, 61 direct dependencies, 20 файлов, 116,711 unpacked bytes. Поля `engines` нет, хотя source root требует Node `^22.19 || >=24` и pin'ит pnpm 11.7.0.[7][M2]

**CONFIRMED — tier 2 primary.** Отсутствие `engines` — объяснение, почему unsupported Node не отсекается package manager'ом, но не доказанная причина npm hang.

## 2. Cordis и тезис «Everything is a Plugin»

Cordis — не фиктивная ссылка: официальный `cordiverse/cordis` существует с мая 2022 года, имеет 5,236 stars, 281 forks, 550 commits и MIT license. Репозиторий paper создан 13 августа 2026 года, имеет только два commits и не содержит repo license metadata; сам paper — свежий preprint, а не устоявшийся стандарт.[8][9]

DSH действительно реализует plugin model глубоко, а не только в README:

- plugin предоставляет services, typed events и reversible effects через общий `ctx`;
- model adapter, tool registry, session log и agent loop являются заменяемыми plugins;
- session events — durable facts; agent events — live lifecycle; capability events — policy/adapters;
- tool path проходит `pre-execute → monotonic guards → execute → post-execute`;
- profile собирается слоями bundles и patch overlays;
- session log — источник model history, fork/resume/transcript/telemetry/persistence;
- явный invariant: всё видимое модели должно восстанавливаться из log.[10][11][M3]

Из опубликованного package сгенерирована реальная Web composition: **129 plugin rows**. В source base bundle 78 rows, Web bundle 51, headless bundle 3. Snapshot содержит 7,412 tracked files, 2,578 TS/TSX files, 564,122 строк TS/TSX, из них 259,876 production по зафиксированному path filter; 248 `package.json`, 44 manifest'а с полем `dsh`, 811 строгих `*.spec|*.test` files и 12,543 `it(`/`test(` call sites.[M3]

**CONFIRMED — tier 1 measurement + tier 2 primary:** «Everything is a Plugin» технически соответствует коду. Но фраза «no privileged core» описывает extension model, а не отсутствие сложного ядра: 129-row composition и ~260k production TS — это крупная платформа.

Существенная оговорка: DSH использует vendored/rescoped Cordis. `vendor/README.md` фиксирует upstream 4.0.0-rc.7 и перечисляет 18 групп локальных изменений — loader transactions, HMR, lifecycle hardening, config reconciliation и другие. В опубликованном graph уже встречается 4.0.1. Значит, Cordis нельзя считать готовой независимой библиотекой, которую Orchestra безболезненно подключит как dependency.[M3]

## 3. Практическая установка: заявленный `npx` против фактического запуска

### Предрегистрация

Pass/fail был установлен до запуска: команда должна дать пригодный вывод, а `web` — HTTP 200 не позднее 15 минут; любые записи только внутри disposable temp; credentials отсутствуют.

| Команда | Runtime | Результат |
|---|---|---|
| `npx ... --help` | Node 20.20.2 / npm 10.8.2 | FAIL: 10 мин, 0 stdout, зависание при dependency placement |
| `npx ... --help` | Node 24.19.0 / npm 11.17.0 | FAIL: 16.7 мин, 0 stdout, тот же класс зависания |
| `npx --yes @...@rc.6 web` | Node 24.19.0 / npm 11.17.0 | INCONCLUSIVE: bounded 120 с при заранее заявленном лимите 15 мин |
| **`npx @deepseek-ai/dsh web`** | Node 24.19.0 / npm 11.17.0 | **PASS:** HTTP 200 через 509 с; точная внутренняя README-команда |
| `corepack pnpm@11.7.0 dlx ... --help` | Node 24.19.0 | PASS за 3:21; 582 resolved / 527 downloaded / 525 added |
| `corepack pnpm@11.7.0 dlx ... web` | Node 24.19.0 | PASS: HTTP 200 через 46 с, 12,109 bytes, title `DeepSeek Harness` |
| `--profile web --dump-default-config` | тот же published package | PASS: 15,329 bytes, 490 строк, 129 plugin rows |

Node 24.19.0 tarball сверялся по SHA-256 с nodejs.org. После каждого bounded probe точная process group очищалась; порт закрыт; вне temp изменений не найдено. У точной README-пробы raw log — 225 bytes, SHA-256 `83e8e7...f6c`, HTML — 12,109 bytes, SHA-256 `7dcd32...16fc`. Pnpm store занял около 439 MB disk (341,904,606 apparent bytes), corepack — ещё около 20 MB.[12][M4]

**CONFIRMED — tier 1 direct measurement:** опубликованный DSH работает, Web UI настоящий, точная README-команда воспроизводится на supported Node 24/npm 11. Две долгие pinned `--help` пробы зависли, но последующий fresh-home exact command прошёл за 509 секунд; это наблюдавшиеся смешанные cold-install outcomes, а не измеренная variance distribution и не evidence сломанного quick start. В нашем прогоне `pnpm dlx` был быстрее.

## 4. Модели, providers и authentication

### Default route

Published config выбирает `deepseek-official/deepseek-v4-flash`; официальный catalog содержит также `deepseek-v4-pro`. Adapter отправляет `POST {baseURL}/chat/completions`, default `https://api.deepseek.com`, и ищет `DEEPSEEK_API_KEY` через credential service или environment.[13][M5]

**CONFIRMED:** прямого consumer subscription route DeepSeek в primary adapter нет; это API billing/auth.

### Дополнительные providers

`llm-pi-ai` монтируется в default composition, но routes появляются только после settings. Мы извлекли именно опубликованную зависимость `@earendil-works/pi-ai@0.82.1`: catalog от 25.07.2026 содержит **37 provider files, 48 protocol groups и 1,109 model entries**. Среди них Anthropic, OpenAI, OpenAI Codex, DeepSeek, Bedrock, Vertex, Azure, OpenRouter, GitHub Copilot, Groq, xAI, Mistral, Qwen, Moonshot, ZAI и другие.[M5]

Реальная auth matrix требует разделить catalog capability и достижимый DSH login path:

- большинство routes — API keys;
- Bedrock, Vertex и Azure могут использовать свои ambient/native credentials;
- custom OpenAI-compatible endpoint допускает локальный model server без key, если сервер сам его не требует; DSH не устанавливает и не управляет local model runtime;
- pi-ai catalog содержит subscription-oriented providers: GitHub Copilot OAuth, Kimi Code subscription, Qwen/Xiaomi Token Plan и другие;
- DSH `llm-pi-ai` adapter при этом не передаёт pi-ai credential store и не запускает interactive OAuth login; OAuth-only `openai-codex` скрывается как unconfigured, а вручную переданный token/key может создать route без refresh;
- persistent primary Claude.ai/ChatGPT/DeepSeek subscription routes в коде не найдены.[14][M5]

**CONFIRMED — tier 1 published-tarball inspection + tier 2 source.** Provider surface шире API keys, но catalog OAuth capability, вручную переданный subscription token, встроенный login flow и persistent product session — четыре разные вещи. У проверенного DSH нет собственного interactive OAuth/store path для catalog routes.

## 5. Claim про Claude Code и Codex subagents

Пакеты реальны и отдельно опубликованы: `@deepseek-ai/dsh-subagent-codex` и `@deepseek-ai/dsh-subagent-claude-code`. Оба могут использовать native product auth host'а, то есть **косвенно** consumer subscription, если соответствующий CLI уже установлен и залогинен.[15][M6]

Однако published `@deepseek-ai/dsh@0.1.0-rc.6` не зависит от этих packages, а сгенерированная default Web composition не содержит provider rows `subagent-codex`/`subagent-claude-code`. Full presets содержат disabled tool templates; examples добавляют packages явными overlays. Это противоречит буквальному README packages «Shipped profiles load this provider once»: для проверенного published default это не так.[M4][M6]

| Adapter | Реальное поведение | Ограничения |
|---|---|---|
| Codex | `codex app-server --stdio`, fresh process + ephemeral thread + один turn; host config/auth/model/sandbox | standalone text + cwd; final answer only; нет continuation/resume/pool/progress/persistence/human approval/timeout/rollback |
| Claude Code | official Agent SDK, fresh native `claude` query, `persistSession:false` | standalone text + cwd; final answer only; `AskUserQuestion` disabled; те же lifecycle ограничения |

Codex baseline — 0.147.0; Claude baseline — SDK 0.3.220/CLI 2.1.220. Credential-shaped env scrubbed, но обычные `HOME`/`PATH` сохраняются; explicit env может вернуть key.[15]

**CONFIRMED:** product subagent claim технически правдив как opt-in one-shot bridge, но неверен как «из коробки persistent Claude/Codex workers». У DSH отдельно есть сильные native in-process subagents: one-shot/continuable child sessions, durable descriptors, depth, follow-up, interrupt и UI. Их нельзя смешивать с ограничениями product adapters.[M6]

## 6. Persistence, memory, tools и orchestration

### Что есть

- Default session persistence — append-only JSONL с zstd frames, fsync/checkpoints, recovery torn tail, durable header/lineage, fork/resume и projections.[10][M7]
- MCP client поддерживает stdio/HTTP, discovery, HMR и автоматический reconnect с exponential backoff, default budget 10 attempts.[M7]
- Native subagent core поддерживает continuable children и cold resume через durable session data.[M6]
- Tool surface большой: filesystem/read/write/edit, Bash/PTY/LSP, plans/goals, subagents, workflows, jobs, schedule, Web search, MCP и code mode; tool policy pipeline централизован.[10][11]
- Browser UI не муляж: conversation/history/workspace/settings/models/plugin inventory/presets/permissions/plans/goals/workflows/subagents/jobs/files/questions/trajectory/downloads подтверждены packages и published composition.[M8]

### Чего нет или default слабее Orchestra

- `jobs-local` прямо документирован как process-local: records умирают с process; это не durable background scheduler.[M7]
- Schedule state durable в session log, но reminder вовремя доставляется только пока исходная session live; cold session обработает overdue только после resume.[M7]
- Default query index — SQLite `:memory:` с `openAt: never`, то есть content search фактически выключен.[M4]
- В shipped composition нет semantic long-term memory server. Есть только opt-in MCP examples Memorix/reference-memory/Engram, установка и storage остаются внешними.[M7]
- Git worktree isolation как runtime option пока deferred; DSH workspace — cwd, а не Orchestra-managed отдельный git worktree на worker.[M8]
- Telegram, task/payment manager, YouGile и multi-project authenticated control plane targeted search не нашёл.[M8]

**CONFIRMED — tier 2 source + tier 1 config dump.** DSH силён как composable single-host agent harness; Orchestra сильнее как долговременный multi-agent operations control plane.

## 7. Безопасность

### Сильная сторона с узкой гарантией: shell confinement и общий policy vocabulary

DSH имеет три permission modes: `read-only`, `workspace-write`, `danger-full-access`. Для **shell child processes** local provider выбирает Linux bubblewrap с Landlock fallback, macOS Seatbelt и Windows ACL/restricted token; невозможность enforcement должна давать structured `SANDBOX_UNAVAILABLE`, partial enforcement видимо оператору. Published default — `workspace-write`.[M4][M9]

Для **in-process filesystem tools** действует другой механизм: trusted-code fence только на `writeText/editText`; reads разрешены во всех modes. Он прямо не является kernel boundary, сохраняет resolve-to-syscall TOCTOU и не защищает от adversarial host processes. Значит, у DSH нет единой cross-platform OS boundary для всех filesystem effects.[M9]

Сравнительно DSH имеет более оформленные policy/enforcement contracts для shell и штатных FS mutations, чем текущая Orchestra worktree isolation. Но ни worktree, ни FS fence не являются общей OS security boundary; в Orchestra некоторые runtime/review paths также сознательно работают без sandbox.[O1]

### Границы, которые нельзя скрывать

- Shell confinement регулирует только **filesystem effects**; network и process visibility не входят в vocabulary.[M9]
- `workspace-write` ограничивает mutations, но не широкое чтение. Local credential store честно создаёт POSIX directory 0700/file 0600 и проверяет modes, однако docs прямо говорят: это не защищает secret от model/tools под тем же UID; OS keychain deferred.[M9]
- Model-written workflow выполняется в worker thread + `node:vm`. Проект сам пишет, что это не security boundary: escape возвращает Node capabilities с host-process privileges.[M9]
- External plugins и MCP stdio commands — trusted host code; npm/pnpm installation расширяет supply chain.[11][M9]
- Telemetry по умолчанию `DISABLED`; при включении default exporter направляет session-log telemetry на `harness-telemetry.deepseeksvc.com`.[M4]
- В snapshot не найден `SECURITY.md` на глубине до 4; это отсутствие файла, не доказательство отсутствия закрытого security process.[M3]

### Web exposure

По умолчанию Web слушает `127.0.0.1:3080`. В source configuration есть `0.0.0.0` и allowed authorities, но application auth/TLS layer targeted search не нашёл; часть settings RPC намеренно loopback-only. Поэтому это local UI, не готовая замена authenticated remote dashboard Orchestra.[M8][O1]

### Сильное counter-evidence против доверия к coverage

Собственный postmortem DSH фиксирует, что ACP bridge не мог создать или загрузить ни одной session в production, хотя было **178 green unit tests и 100% line coverage**: ручной mounting обошёл real Loader и реальную service topology. Дефект исправлен и добавлен real-loader e2e, но это прямое доказательство, что объём тестов нельзя читать как зрелость integration path.[M10]

**LIKELY/MEDIUM:** policy architecture DSH лучше разделяет mode, provider и enforcement status, но общая security guarantee не сильнее автоматически: kernel boundary относится к shell, FS tools имеют trusted-code fence, а process/network/runtime plugins не контейнеризированы.

## 8. Сравнение с текущей Orchestra

Orchestra baseline измерен по текущему checkout: 78 Python app files, 46,471 строк, 39 MCP tools в `app/mcp_stdio.py`. Код подтверждает четыре runtime families (Claude, Codex, Grok, OpenCode), persistent/mid-turn lifecycle, SQLite sessions/logs/jobs/tasks/payments, restart restore jobs, semantic FastEmbed bge-m3/sqlite-vec memory по docs+logs, Telegram bridge, cookie/internal-token auth, Task Manager/YouGile sync и git worktrees.[O1]

| Ось | DSH | Orchestra | Для текущего сценария |
|---|---|---|---|
| Primary auth | DeepSeek/API keys, cloud-native creds, compatible endpoints | consumer subscriptions через native CLIs/SDK | **Orchestra** |
| Worker lifecycle | сильные native children; Claude/Codex bridges one-shot | persistent workers, steering, hibernate/resume, cross-agent delivery | **Orchestra** |
| Durable background | default jobs process-local; cold schedule не будит | server jobs persist/restore и доставляют | **Orchestra** |
| Memory | opt-in external MCP servers | встроенный hybrid semantic memory docs+logs | **Orchestra** |
| Tool architecture | typed/reversible seams, один pipeline | working, но неоднородные runtime integrations | **DSH** |
| Filesystem policy | kernel-backed shell confinement + trusted-code FS mutation fence | worktrees; OS sandbox не общий invariant | **DSH по явности архитектуры; без общей security-победы** |
| UI/control plane | polished local Web UI | authenticated dashboard + TG/tasks/payments/YouGile | **Orchestra** |
| Maturity | 4-day public preview, RC, no release/tag | production-shaped текущая система | **Orchestra** |

Полная замена создаст два шага назад ради двух шагов вперёд: потеряет subscription-first economics и operations plane, чтобы получить clean plugin/event/sandbox architecture. Sidecar не исправляет это: он дублирует UI, session store, settings/auth и process supervision.

## 9. Стоимость интеграции

Это **planning ranges, не измеренные трудозатраты**:

- **FULL:** multiple engineer-months, confidence LOW. Нужно переносить или переписывать Python control plane, persistent subscription runtimes, Telegram, durable jobs, semantic memory, auth, worktrees, tasks/payments/YouGile и lifecycle/merge rules.
- **Sidecar:** multiple engineer-weeks до production hardening, confidence LOW. Получаем две истины для sessions/settings/UI и Node process с ~525 installed packages; subscription primary route не появляется.
- **SLICE pilots:** ориентир 3–7 engineer-days каждый до следующей переоценки, confidence MEDIUM-LOW. Они ложатся на существующие seams и не требуют импортировать Cordis.

Главный операционный риск полной интеграции — не размер npm download, а две competing state machines: DSH event log/Cordis lifecycle и Orchestra SQLite/session manager. Согласовать crash recovery, ownership, cancellation и UI projections сложнее, чем обернуть API.

## 10. Что именно заимствовать

1. **Event-log invariant:** «model-visible means logged», с replay/projection tests и явным source каждого injected message/tool/schema snapshot.
2. **Capability seam contract:** definition/provider/consumer + reversible registration, прежде всего для subprocess/shell policy; не копировать FS fence как kernel guarantee.
3. **Enforcement status:** `full | partial | unavailable`, fail closed, раздельно для каждого enforcement path, и честное перечисление того, что он не покрывает.
4. **Tool pipeline:** единый pre/guard/execute/post/finalize path, чтобы approval, hooks, sandbox и audit нельзя было обойти альтернативным caller'ом.
5. **Plugin inventory/config overlay UI** как концепцию, но не Cordis runtime.

Не заимствовать сейчас: Cordis/vendor runtime; DSH Web/session sidecar; direct provider/API-key auth; one-shot product subagents; process-local jobs; worker-thread `node:vm` как security feature.

## 11. Три конкретных пилота

### P1 — replay invariant модельного контекста

На 20 representative Orchestra fixtures (plain turn, tool, steer, image, compact, interrupted/restarted) построить test-only projection всех model-visible inputs.

**Go:** 20/20 запросов дают byte-equivalent model-visible input либо заранее классифицированное расхождение; нет prod writes; fixture benchmark overhead <1%. **No-go:** хотя бы один неклассифицированный hidden input.

### P2 — shell-policy seam + раздельный enforcement report

Disposable Linux prototype для `read-only/workspace-write/danger-full-access` без изменения production runtime; kernel-backed shell и in-process FS checks учитываются как разные paths.

**Go:** shell write outside workspace denied; штатный FS tool запрещает mutation вне workspace; inside allowed только в правильном mode; отсутствие shell backend даёт `unavailable` и fail closed; FS fence маркируется как non-kernel; network/process отмечены как *not enforced*; mutation tests краснеют при снятии каждого guard. **No-go:** partial или trusted-code fence выглядят как единая kernel boundary.

### P3 — DSH benchmark, не интеграция

Только после отдельного разрешения на credential path: три фиксированных closed coding tasks в isolated clone через operator-selected DeepSeek API или local compatible endpoint; те же oracles в Orchestra.

**Go:** 3/3 oracles, ноль writes вне workspace, зафиксированы wall time/tokens/metered cost, качество и стоимость конкурентны Orchestra. **No-go:** любой unexpected write, credential leak либо провал oracle. Текущий Phase 1 credentials не использовал и этот pilot не запускал.

## Counter-evidence и ограничения

### Что говорит в пользу более сильного решения, чем SLICE

- 141,869 stars показывают исключительный интерес; крупная кодовая база и 12,293 reachable commits опровергают freshly generated пустышку, но сами по себе не доказывают зрелость или качество.[2][5][M3]
- Web UI действительно стартует; architecture реально pervasive; source большой, test-heavy и снабжён postmortems.[M3][M4][M10]
- DSH shell-policy/enforcement architecture, tool pipeline, event sourcing и continuable native subagents местами архитектурно сильнее Orchestra.[10][11][M6][M9]
- MCP reconnect и native child continuation уже есть; первоначальная гипотеза «всё process-local» была бы неверна.[M6][M7]

### Что удерживает от FULL

- README сам маркирует developer preview и обещает compatibility-breaking changes; только RC npm versions, ноль releases/tags.[1][4][7]
- Cold pinned/help npm path дважды stalled, но exact README Web command прошёл за 509 секунд; install latency/variance остаются риском, не quick-start blocker.[M4]
- Primary model path — API key; product subscription adapters opt-in и one-shot.[M5][M6]
- Default jobs не переживают process, semantic memory отсутствует, schedule не будит cold sessions, remote Web auth/TLS не найден.[M7][M8][M9]
- Cordis — heavily modified vendor fork, поэтому FULL означает принять не только framework, но и DeepSeek-specific fork maintenance.[M3]
- Собственный ACP incident прошёл 178 tests/100% line coverage и сломался на первом production connect.[M10]

### Ограничения исследования

- Stars/forks/activity — snapshot и меняются после 17.08.2026.
- Smoke — одна Linux-машина/сеть; exact command прошёл, а различия pinned/help runs не позволяют диагностировать npm без отдельного исследования.
- Модельный inference с реальным API не запускался: credentials были запрещены; quality/cost DSH не измерены.
- Cross-platform sandbox проверен исходниками/tests/docs, но не исполнялся на macOS/Windows/older Landlock.
- Application auth/TLS сформулирован как «не найден targeted search», а не математическое доказательство отсутствия во всех 7,412 файлах.
- Стоимость интеграции — rough range, её должен заменить pilot data.

### Adversarial review

Sol, round 1, нашёл один blocking security overclaim и пять неточностей. Исправлены: разделение shell confinement и FS fence; exact README smoke с полным бюджетом; subscription-oriented provider protocols; статус `evidence.json`; уверенность/смысл `SLICE`; трактовка stars/commits. Round 2: **APPROVED WITH NON-BLOCKING SUGGESTIONS; blocking none**. Две оставшиеся механические suggestions (`INCONCLUSIVE` в JSON и «mixed outcomes» вместо «variance») также внесены. Полная трасса: [review-research.md](review-research.md).

## Затрагиваемые файлы и будущие риски

Phase 1 изменяет только:

- `docs/tasks/308/research.md`
- `docs/tasks/308/evidence.json`
- `docs/tasks/308/review-research.md` после независимого review

При будущем планировании нельзя менять runtime до прохождения pilots. Особые edge cases: silently partial sandbox; same-UID secret reads; model-visible data вне log; child accepted-but-not-logged messages; cold-session schedules; two competing session stores; provider-native auth, которое UI ошибочно принимает за configured route; npm/pnpm supply-chain drift; Cordis vendor divergence.

## Источники

### Web / primary

1. [DeepSeek Harness README](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/README.md) — tier 2 primary; developer preview, run command, license.
2. [GitHub repository API](https://api.github.com/repos/deepseek-ai/deepseek-harness) — tier 2 primary; repo identity and counters.
3. [GitHub organization API](https://api.github.com/orgs/deepseek-ai) — tier 2 primary; org identity and counters.
4. [GitHub Releases API](https://api.github.com/repos/deepseek-ai/deepseek-harness/releases) и [Tags API](https://api.github.com/repos/deepseek-ai/deepseek-harness/tags) — tier 2 primary.
5. [GitHub commits API](https://api.github.com/repos/deepseek-ai/deepseek-harness/commits?per_page=1) — tier 2 primary; pagination count/latest/first commit.
6. [GitHub contributors API](https://api.github.com/repos/deepseek-ai/deepseek-harness/contributors?per_page=100) — tier 2 primary.
7. [npm registry: @deepseek-ai/dsh](https://registry.npmjs.org/%40deepseek-ai%2Fdsh) — tier 2 primary.
8. [Cordis repository](https://github.com/cordiverse/cordis) — tier 2 primary.
9. [Cordis paper repository](https://github.com/cordiverse/paper) — tier 2 primary.
10. [DSH architecture](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/architecture.md) — tier 2 primary.
11. [Tool execution pipeline](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/tool-execution-pipeline.md) — tier 2 primary.
12. [Node 24 official checksums](https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt) — tier 2 primary.
13. [DeepSeek LLM adapter README](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/llm/llm-deepseek/README.md) — tier 2 primary.
14. [Provider guide](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/user/guide/providers.md) — tier 2 primary, cross-checked with source/tarball.
15. [Codex subagent](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/subagent/subagent-codex/README.md) и [Claude Code subagent](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/subagent/subagent-claude-code/README.md) — tier 2 primary, cross-checked with `src/run.ts` and published config.

### Direct measurements / local source

- **[M1]** Screenshot hash/dimensions + GitHub JSON snapshots captured 17.08.2026; raw values normalized in `evidence.json` — tier 1.
- **[M2]** npm registry JSON and published manifest inspection — tier 1.
- **[M3]** Source snapshot SHA `47f943...`: `git ls-files`, `rg`, `wc`, bundle row counts, `vendor/README.md` — tier 1.
- **[M4]** Isolated Node 20/24 npm probes, pnpm positive control, HTTP probe, config dump, disk measurement — tier 1.
- **[M5]** Published default config + extracted `@earendil-works/pi-ai@0.82.1` provider data/source — tier 1.
- **[M6]** Published product-subagent metadata, default-dependency/config absence, source lifecycle paths — tier 1.
- **[M7]** `jobs-local`, schedule, persistence, MCP and memory-example source/docs at fixed SHA — tier 2 primary, composition cross-check tier 1.
- **[M8]** Published Web composition and targeted package/UI/worktree/TG/task search — tier 1.
- **[M9]** Sandbox/credentials/workflow/Web source/docs/tests at fixed SHA — tier 2 primary.
- **[M10]** `docs/postmortem/0001-acp-default-export-drops-inject.md` at fixed SHA — tier 2 primary; author-reported incident, internally corroborated by linked fixes/tests.
- **[O1]** Orchestra SHA `27a83859...`: `app/models.py`, `app/backend_*.py`, `app/bg_jobs.py`, `app/db.py`, `app/rag.py`, `app/routes/memory.py`, `app/tg_bridge.py`, `app/main.py`, `app/tm.py`, `app/tm_yougile.py`, `app/workspace.py`, `app/mcp_stdio.py` — local primary source/tier 1 counts.

## Confidence summary

- **Подлинность и counters — CONFIRMED:** official APIs + screenshot agreement.
- **Архитектура/plugin claim — CONFIRMED:** source/config measurement, не только README.
- **Published package runnable — CONFIRMED:** HTTP 200 через exact `npx` и через pnpm.
- **Exact README quick start — CONFIRMED locally:** HTTP 200 за 509 секунд; latency variance остаётся UNCERTAIN globally.
- **Нет primary consumer-subscription route — CONFIRMED:** adapter/config/tarball inspection.
- **Product subagents opt-in и one-shot — CONFIRMED:** published dependency/config + source.
- **Security architecture — LIKELY/MEDIUM:** shell kernel confinement и FS trusted-code fence разделены; cross-platform execution не проводился.
- **FULL rejected / REJECT rejected — HIGH; SLICE ROI — MEDIUM:** pilots — способ измерить ценность, а не доказательство, что перенос уже окупается.
