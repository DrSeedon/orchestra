# #377 — Codex CLI на боевом VPS: версия, upstream и решение об обновлении

Дата проверки: 2026-08-23, 17:40 CEST.

## Короткий ответ

**Вердикт: NO-UPGRADE.** На VPS уже установлен последний стабильный Codex CLI:
`0.149.0`. Тот же номер возвращают npm `latest`, официальный OpenAI changelog и GitHub
`releases/latest` [1][2]. Все 12 живых native `codex app-server`, найденных на VPS в момент
проверки, также исполняют `0.149.0`; старого процесса после установки не осталось.

Диапазон release notes между установленной и актуальной версиями — пустой:
`0.149.0...0.149.0`. Обновлять некуда. В `main` upstream уже есть более новые коммиты, но
релиза новее `0.149.0` нет; ставить unreleased `main` ради открытых дефектов не обосновано.

У `0.149.0` есть полезные уже полученные исправления: 872K override для GPT-5.6,
восстановление permission profile при resume, ограничение legacy resume preview scan,
конкурентные config reads, ограничение TUI replay buffer, auth recovery и редактирование
access token в app-server diagnostics [10][11][12][19][24][28][29]. Они не закрывают
оставшиеся открытыми дефекты native compaction и lifecycle stdio MCP [15][20][21].

## Вопрос и критерий решения

- **Context:** Orchestra запускает persistent `codex app-server --stdio` с ChatGPT subscription
  auth, отдельным процессом и `CODEX_HOME` на каждую сессию.
- **Change under test:** заменить установленный CLI более новым стабильным релизом.
- **Baseline:** текущий `0.149.0` и текущие Orchestra workarounds/lifecycle.
- **Outcome:** upgrade оправдан только если существует более новый стабильный релиз с
  подтверждёнными исправлениями боевых путей Orchestra, а регрессионный риск можно ограничить
  canary и rollback.

### Гипотезы и фальсификаторы

1. **H1:** upgrade нужен, потому что новый стабильный CLI чинит релевантные Orchestra upstream
   defects. **Фальсификатор:** установленная версия равна latest либо найденные изменения уже
   установлены/относятся только к Desktop/TUI/другому transport.
2. **H2:** upgrade сейчас не нужен; остающиеся симптомы либо открыты upstream, либо являются
   Orchestra-specific. **Фальсификатор:** официальный релиз новее `0.149.0` с merged fix для
   боевого `app-server --stdio`, native resume/compact/MCP lifecycle.

**Результат:** H1 REFUTED, H2 CONFIRMED для решения на 2026-08-23.

## Метод и границы доказательства

- **Tier 1 — direct production measurements:** бинарник/package, версия каждого живого native
  app-server, `/proc` RSS/CPU/FD/limits, структура managed `CODEX_HOME`, текущий код Orchestra.
- **Tier 2 — primary:** OpenAI changelog/docs, tagged `rust-v0.149.0` app-server README, official
  upstream PR и release.
- **Tier 4 — single external report:** открытые GitHub issues. Их статус и приложенные замеры
  доказывают наличие report, но не автоматически доказывают воспроизведение на VPS.

По каждой нагрузочной категории issue сопоставлялся с фактическим production call path. Desktop,
TUI, Remote Control и custom-provider defects не переносились на Orchestra только по совпадению
слов `app-server` или `resume`.

## 1. Точные версии

### Production

```text
$ command -v codex
/usr/bin/codex
$ readlink -f /usr/bin/codex
/usr/lib/node_modules/@openai/codex/bin/codex.js
$ codex --version
codex-cli 0.149.0
$ node -p "require('/usr/lib/node_modules/@openai/codex/package.json').version"
0.149.0
```

Native Linux binary:

```text
sha256 bbc3341e44c9ead340ed9570c17be936e37870f570751a941699ffd04d672827
size   258322048 bytes
mtime  2026-08-23 11:30:48 CEST
```

В 17:40 CEST `/proc/<pid>/exe --version` вернул `codex-cli 0.149.0` для **12 из 12**
живых native процессов с аргументом `app-server`. Один процесс не имел Orchestra session id и
исключён из fleet resource measurements; версия у него тоже `0.149.0`.

### Latest stable

- `npm view @openai/codex version --json` → `"0.149.0"`.
- Официальный OpenAI changelog: **Codex CLI 0.149.0**, 2026-08-20 [1].
- GitHub `releases/latest` → tag `rust-v0.149.0`, release commit `758ef40` [2].

**CONFIRMED — три независимых primary/measurement сигнала.** GitHub показывает коммиты в
`main` после релиза, но это не новый stable target [2].

## 2. Official changelog между installed и current

`installed = current = 0.149.0`, поэтому множество релизов между ними пусто. Никакого
upgrade delta нет.

Для понимания уже полученного состояния релевантные пункты самого `0.149.0`:

| Область | Уже в установленном `0.149.0` | Что это не чинит |
|---|---|---|
| Large context | GPT-5.6 override до 872,000 tokens, PR #39102 [10] | Полные API 1.05M и compaction fidelity |
| Resume | Persisted approvals/profile восстанавливаются при cold resume/fork, PR #39153 [12] | `--ephemeral resume` regression #20084 [13] |
| Resume latency | Legacy preview читает максимум 1 MiB tail, PR #39033 [11] | Полный `thread/list` scan #22411 [9] |
| App-server concurrency | Config reads присоединяются к active shared-read batch, PR #39036 [19] | Общий SQLite contention #20213 [8] |
| Memory | Inactive **TUI** replay buffer ограничен 256 KiB deltas, PR #39081 [24] | MCP child/FD lifecycle #26984/#30408 [20][21] |
| Auth | Provider-owned one-shot recovery и token redaction в diagnostics, PR #39274/#39141 [28][29] | Custom `base_url` с subscription auth #34608 [27] |

## 3. Upstream defects и применимость к Orchestra

### 3.1 App-server latency

**Открыто upstream, но два главных механизма не используются Orchestra.**

- #16158 — открытый Desktop report: local app-server RPCs задерживались от десятков секунд до
  минут на большой истории [7]. Это один внешний macOS/Desktop report, не воспроизведение на VPS.
- #22411 — открытый report: каждый `thread/list` полностью читает все rollout files, вызывая
  high CPU/slow startup [9]. В production code Orchestra нет `thread/list`, `thread/read` для
  picker или Desktop sidebar.
- #20213 — открытый report о contention нескольких CLI на общих `state_5.sqlite` и
  `logs_2.sqlite` [8]. У 11 измеренных Orchestra app-server было **11 уникальных private
  `CODEX_HOME` и 11 уникальных state DB inode**; общими были только один target `sessions/` и
  один target `auth.json`. Поэтому описанный shared-state-DB writer contention разрезан текущей
  архитектурой Orchestra.
- PR #39036 и #39033 уменьшают два узких класса ожидания/scan и уже входят в `0.149.0`
  [11][19]. Они не дают основания для нового update.

**Confidence: CONFIRMED для непопадания production call path** — code grep + process/home
measurement. **LIKELY для наличия иных upstream latency defects** — несколько независимых open
reports, но нет VPS reproduction.

### 3.2 Resume и persistence

**Core resume поддерживается и используется корректно.** Tagged app-server contract требует
сохранить `thread.id` и вызвать `thread/resume`; stored thread снова открывается, а при наличии
persisted token usage сервер сразу после ответа эмитит `thread/tokenUsage/updated` [3]. Orchestra:

- хранит thread id;
- вызывает `thread/resume`;
- отвергает ответ, если upstream вернул другой id (`app/backend_codex.py:1061-1078`);
- держит shared rollout directory, поэтому private home не теряет историю
  (`app/backend_codex.py:2349-2370`).

Разбор открытых reports:

- #20084: `codex exec --ephemeral resume` всё равно пишет rollout [13]. **Не применимо:**
  Orchestra не запрашивает ephemeral threads; сохранение history здесь ожидаемо.
- #30916: Desktop не подхватывает созданный внешним app-server thread до рестарта Desktop [14].
  **Не применимо:** Orchestra не ждёт Desktop reconciliation, а вызывает resume по своему id.
- #39153: permission profile терялся на cold resume; **исправлено и уже установлено** [12].

**Persistence активного хода через рестарт supervisor — Orchestra-specific, не upstream.**
Upstream `0.149.0` документирует stdio, WebSocket и Unix-socket transport [3], но не передачу
живых pipe endpoints между поколениями чужого supervisor. Orchestra сама создаёт parent-owned
pipes, публикует обе стороны через systemd FD store и принимает их после рестарта
(`app/fdstore.py:1-115`, `app/manager.py:1915-2050,2311-2375`,
`app/backend_codex.py:896-916`). Предыдущие production-shaped experiments #230/#237 доказали
полный Codex result через restart; это локальная функция Orchestra, которую CLI upgrade не
заменяет.

**Confidence: CONFIRMED** — tagged protocol + current code + prior direct local measurement.

### 3.3 Native compact

**Открытые upstream risks применимы к same-thread compact Orchestra.**

- #37121 открыт: после truncation tool output compaction может сделать сохранённое в rollout
  tool state недоступным продолжению [15].
- #14589 закрыт без linked PR и с `Development: No branches or pull requests`; закрытый issue
  сам по себе не является доказательством fix. Его experiment показывает потерю точных tool
  details при summary compaction [17].
- #38269 открыт: unchanged client `additionalContext` пропадает после auto-compaction [16].
  **Сейчас не применимо:** Orchestra не отправляет `additionalContext`; символ отсутствует во
  всём production Codex path.

Orchestra вызывает официальный `thread/compact/start` в том же thread и ждёт полный
`turn/started → contextCompaction → turn/completed` lifecycle
(`app/backend_codex.py:1203-1270`), как требует tagged contract [3]. Это исправляет старый
Orchestra-specific fresh-thread compact/cache reset, но не может восстановить сведения, которые
сам upstream summary не сохранил.

**Confidence: LIKELY для fidelity risk** — два применимых fidelity reports (#37121/#14589) и
один corroborating, но сейчас неприменимый `additionalContext` report (#38269); defect не
воспроизводился заново на боевой истории из-за destructive/paid nature.

### 3.4 Large context

- Official API model card GPT-5.6 Sol заявляет 1,050,000 context и 128,000 max output [6]. Это
  API contract, не обещание полного окна в ChatGPT-auth CLI.
- PR #39102 в `0.149.0` разрешает GPT-5.6 CLI override максимум до **872,000** [10].
- Production `~/.codex/models_cache.json` сейчас сообщает:
  `context_window=272000`, `max_context_window=872000`,
  `effective_context_window_percent=95`.
- Production config выставляет `model_context_window=872000` и
  `model_auto_compact_token_limit=784800`. По catalog effective ceiling это 828,400 tokens;
  auto-compact threshold — 90% от override.
- #30910 всё ещё открыт и просит full 1M mode [18]. Следовательно, #39102 — частичное
  улучшение, уже полученное, а не повод ставить новую версию.

**Confidence: CONFIRMED** — official model page + merged PR + current catalog/config. Нельзя
подменять API 1.05M значением подписочного CLI.

### 3.5 CPU/RAM idle sessions и MCP/FD leak

**Upstream defect остаётся открытым; локально измерен footprint, но не leak.**

- #26984 открыт: stdio MCP refresh может оставлять pipe FD и child processes до EMFILE [20].
- #30408 открыт: один shared app-server оставлял per-thread MCP sets после закрытия threads,
  report — 133 orphan processes и 9.3 GiB RSS [21].
- #37971 открыт: после восьми дней shared daemon дошёл до 1022/1024 FD и сохранил старый binary
  после CLI update [22].
- PR #39081 ограничивает только inactive **TUI replay text buffer**, не MCP children и не
  Orchestra process-per-session footprint [24].

Production snapshot: пять DB sessions со статусом `idle|waiting` и пустым `active_turn_id` были
измерены тремя 2-second samples. Нагрузка машины (`loadavg1`) печаталась рядом.

```text
sample  loadavg1  total tree CPU  total tree RSS
1       3.07      5.5%            1139.9 MiB
2       3.54      13.0%           1139.9 MiB
3       3.54      7.0%            1139.9 MiB
mean              8.5%            228.0 MiB/session
```

Каждое дерево содержало 3–7 процессов: native `codex`, `codex-code-mode` и 1–5 MCP/runtime
children. У native app-server было 39–57 FD (242 суммарно) и soft `RLIMIT_NOFILE=524288`.

Это подтверждает **реальную цену удержания idle Orchestra sessions**, но не доказывает утечку:
сессии имеют разные MCP sets, срез короткий, а open issues накапливали дефект днями и через
thread/MCP churn. Механизм #30408 ослаблен архитектурой Orchestra: один app-server владеет одним
thread и при disconnect убивается весь owned scope. Но #26984 внутри долгоживущего процесса
остаётся правдоподобным и требует longitudinal FD/RSS monitoring, а не upgrade на ту же версию.

**Confidence: CONFIRMED для footprint; UNCERTAIN для leak на VPS.**

### 3.6 Concurrency

Tagged `0.149.0` использует bounded ingress/processing/outbound queues и при saturation возвращает
JSON-RPC `-32001 Server overloaded; retry later`; клиенту предписан exponential backoff with
jitter [3]. В Orchestra:

- delivery сериализован `asyncio.Lock` на session (`app/manager.py:1014-1028`);
- один backend допускает один active turn; новый input идёт через `turn/steer`
  (`app/backend_codex.py:1096-1115`);
- разные Orchestra sessions исполняются параллельно в разных app-server processes;
- явного special-case retry для `-32001` нет, но process-per-session + serialization сильно
  уменьшают вероятность ingress overload.

Open #14916 просит multi-user service semantics [25]. Это не текущий контракт: Orchestra работает
под одним доверенным Unix user/ChatGPT account и изолирует sessions процессами. Open #35894
описывает first-response-wins при нескольких subscribers одного thread с experimental
`dynamicTools` [26]; текущему single-connection/single-thread path не применимо, но является
blocker для простого перехода к одному shared socket app-server.

**Confidence: CONFIRMED для текущей сериализации; LIKELY для риска shared consolidation.**

### 3.7 Subscription auth

Official OpenAI docs поддерживают `codex login` через ChatGPT для subscription access; login cache
переиспользуется, ChatGPT tokens автоматически refresh-ятся, а file storage находится в
`~/.codex/auth.json` и должен считаться password [4]. Tagged app-server сам владеет ChatGPT OAuth
и refresh token [3].

Orchestra-specific delivery:

- все 203 существующих managed `auth.json` — symlinks на один base target;
- target имеет mode `0600`; 11 живых managed homes имели mode `0700`;
- это исключает stale copied credential после relogin, но logout/rotation становится fleet-wide;
- 11 из 11 mapped live app-server не содержали `mcp_servers.*.env.*` values в argv; текущий код
  переносит MCP env в private `config.toml` (`app/backend_codex.py:2229-2297`).

Upstream:

- #34608 открыт только для ChatGPT subscription auth через custom provider `base_url` [27].
  Orchestra не задаёт `base_url`/custom `model_provider`, а использует обычный network proxy;
  issue не применим.
- #39274 (provider auth recovery) и #39141 (redaction access token из app-server response logs)
  merged и входят в уже установленный `0.149.0` [28][29].

При inventory найден один **unmapped** app-server, в argv которого присутствовали MCP env values.
Он исключён из вывода о current Orchestra mapping: все mapped процессы чисты. Это отдельный VPS
hygiene risk; значения в этот документ не переносились.

**Confidence: CONFIRMED** — official auth docs + filesystem/process measurement + current code.

### 3.8 Unix socket и FD inheritance

Upstream `0.149.0` уже умеет local Unix socket, но wire protocol там — WebSocket after HTTP Upgrade;
raw stdio остаётся JSONL [3]. Поэтому старый local socket probe #230, посылавший наш raw JSONL,
не доказывал поломку socket transport: он мерил несовместимый framing.

Тем не менее socket не является drop-in replacement для текущей restart continuity:

- Orchestra client реализует только stdio JSONL и custom inherited-pipe adoption;
- upstream daemon lifecycle имеет открытые reports о самопроизвольной замене/reset shared
  app-server (#23954) и stale dead daemon state (#35295) [30][31];
- #37971 показывает daemon version skew и низкий inherited `RLIMIT_NOFILE` [22]; production
  Orchestra direct-stdio processes сейчас все одной версии и имеют soft limit 524288.

Смена на shared Unix socket потребует отдельной архитектуры: WebSocket client/reconnect,
subscriber ownership, `-32001` retry, auth/config isolation, active-turn recovery. CLI update на
`0.149.0` ничего из этого не доставляет, потому что версия уже стоит.

**Confidence: CONFIRMED для текущего transport split; UNCERTAIN для ценности будущей socket
архитектуры без отдельного эксперимента.**

## 4. Что upstream уже исправил, что остаётся, что принадлежит Orchestra

| Класс | Статус |
|---|---|
| 872K GPT-5.6 override, permission-profile resume, bounded preview/config reads, TUI replay cap, auth recovery/redaction | **UPSTREAM FIXED, already installed in 0.149.0** |
| Compaction tool-state fidelity #37121; stdio MCP FD/process lifecycle #26984/#30408; full 1M request #30910 | **UPSTREAM OPEN** |
| Desktop picker/sidebar latency, Desktop discovering external threads, Remote Control daemon resets | **UPSTREAM OPEN, not current Orchestra call path** |
| `--ephemeral resume` persistence | **UPSTREAM OPEN, intentionally irrelevant to durable Orchestra sessions** |
| One app-server per Orchestra session; private state DB; shared auth/rollouts; session delivery lock | **ORCHESTRA-SPECIFIC** |
| Active turn survives supervisor restart through systemd FDSTORE and adopted parent-owned pipes | **ORCHESTRA-SPECIFIC, already implemented/measured** |
| Idle fleet footprint (~1.14 GiB/5 trees) | **MIXED:** upstream process/MCP cost × Orchestra process-per-session retention |

## 5. Upgrade decision, canary и rollback

### Решение сейчас

- **Target version:** остаётся `0.149.0`.
- **Action:** ничего не устанавливать, не рестартовать и не переподключать.
- **Canary:** не запускается — нет version delta.
- **Rollback:** не нужен — изменений нет.
- **Не ставить:** unreleased `main`, fork или prerelease только ради открытых issues без merged
  stable fix.

### Триггер следующего рассмотрения

Вернуться к upgrade только после stable release `>0.149.0` и проверить его release/PR на один из
load-bearing fixes: #26984/#30408, #37121 либо явно измеренный app-server latency defect нашего
stdio path. Закрытый issue без linked/located fix недостаточен.

Если такой релиз появится, canary должен быть одним disposable non-orchestrator и доказать:

1. actual `/proc/<pid>/exe --version`, не только новый `/usr/bin/codex` (daemon/version skew уже
   наблюдался upstream [22]);
2. `thread/start → turn/start → turn/steer → turn/completed → disconnect → thread/resume` с тем
   же id;
3. manual same-thread compact и продолжение с контрольными operational facts;
4. MCP refresh/reconnect cycles с FD/RSS trend, а не один snapshot;
5. active-turn supervisor handover отдельным rehearsal — только при явной авторизации рестарта.

Rollback future canary: остановить только canary backend, вернуть package `0.149.0`, проверить
старый binary на private state DB schema и при несовместимой forward migration восстановить
предварительный snapshot canary home. Shared rollout/auth не перезаписывать вслепую.

## Counter-evidence и ограничения

- GitHub issues — первичные reports авторов, но не все подтверждены maintainer или воспроизведены
  на Linux/stdio/Orchestra. Статус `open` не равен доказанному root cause.
- `closed` issue не равен fix: у #14589 нет linked development; поэтому он не включён в
  «исправлено».
- Resource snapshot измеряет footprint на текущей нагрузке, не накопление. Для leak нужен
  одинаковый процесс/MCP set во времени и положительный churn control.
- Public API 1.05M и ChatGPT-auth CLI catalog — разные surfaces.
- Текущий exact version установлен за несколько часов до исследования. Проверка всех живых
  `/proc/<pid>/exe` была обязательна: один только `codex --version` не исключил бы старые процессы.
- Один unmapped process не отнесён к Orchestra без session-id evidence.

## Affected files / риски / edge cases для будущего upgrade

Research-only: код не менялся. При будущем обновлении наиболее чувствительны:

- `app/backend_codex.py` — versioned state migrations, app-server schema, resume/compact events,
  private home/auth/session links;
- `app/backend_jsonrpc.py` — transport framing, outstanding requests, adopted pipes;
- `app/fdstore.py`, `app/manager.py`, `app/session.py` — active-turn handover and cleanup;
- managed `~/.orchestra/codex-home/*/state_*.sqlite` — forward-migration/rollback boundary;
- shared `~/.codex/sessions/` and `~/.codex/auth.json` — fleet-wide persistence/auth boundary.

Edge cases: package updated while old app-servers live; shared auth logout; compact during active
turn; `-32001` overload; MCP child surviving refresh; half-pair FD handover; new state migration
that an older rollback binary cannot read.

## Источники

1. **Tier 2 — official OpenAI changelog:** [Codex CLI 0.149.0, 2026-08-20](https://learn.chatgpt.com/docs/changelog#codex-cli-01490).
2. **Tier 2 — official GitHub release:** [openai/codex 0.149.0 (`rust-v0.149.0`)](https://github.com/openai/codex/releases/tag/rust-v0.149.0).
3. **Tier 2 — tagged upstream protocol:** [`codex app-server` README at `rust-v0.149.0`](https://github.com/openai/codex/blob/rust-v0.149.0/codex-rs/app-server/README.md).
4. **Tier 2 — official OpenAI docs:** [Codex authentication](https://learn.chatgpt.com/docs/auth).
5. **Tier 2 — local source:** `app/backend_codex.py`, `app/backend_jsonrpc.py`, `app/fdstore.py`, `app/manager.py`, `app/session.py` at Orchestra `2abaed4e`.
6. **Tier 2 — official OpenAI model card:** [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol).
7. **Tier 4 — external report:** [#16158 — app-server/Desktop startup and RPC latency](https://github.com/openai/codex/issues/16158).
8. **Tier 4 — external report:** [#20213 — shared SQLite contention](https://github.com/openai/codex/issues/20213).
9. **Tier 4 — external report:** [#22411 — `thread/list` full rollout scans](https://github.com/openai/codex/issues/22411).
10. **Tier 2 — merged upstream PR:** [#39102 — raise GPT-5.6 maximum override to 872K](https://github.com/openai/codex/pull/39102).
11. **Tier 2 — merged upstream PR:** [#39033 — bound legacy resume preview scans](https://github.com/openai/codex/pull/39033).
12. **Tier 2 — merged upstream PR:** [#39153 — restore permission profiles on resume](https://github.com/openai/codex/pull/39153).
13. **Tier 4 — external report:** [#20084 — ephemeral resume persists](https://github.com/openai/codex/issues/20084).
14. **Tier 4 — external report:** [#30916 — Desktop misses externally-created threads](https://github.com/openai/codex/issues/30916).
15. **Tier 4 — external report:** [#37121 — compaction loses recoverable tool state](https://github.com/openai/codex/issues/37121).
16. **Tier 4 — external report + reproducer:** [#38269 — auto-compaction drops unchanged `additionalContext`](https://github.com/openai/codex/issues/38269).
17. **Tier 4 — external experiment:** [#14589 — compaction discards exact tool/reasoning detail](https://github.com/openai/codex/issues/14589).
18. **Tier 4 — external request:** [#30910 — request full 1M context](https://github.com/openai/codex/issues/30910).
19. **Tier 2 — merged upstream PR:** [#39036 — concurrent app-server config reads](https://github.com/openai/codex/pull/39036).
20. **Tier 4 — external report + code analysis:** [#26984 — stdio MCP FD/orphan leak](https://github.com/openai/codex/issues/26984).
21. **Tier 4 — independent external report:** [#30408 — per-thread MCP processes retained](https://github.com/openai/codex/issues/30408).
22. **Tier 4 — independent Linux measurement:** [#37971 — FD exhaustion, inherited limit and daemon version skew](https://github.com/openai/codex/issues/37971).
23. **Tier 1 — prior local experiments:** `docs/tasks/230/research.md`, `docs/tasks/237/research.md` — systemd FD store / active Codex handover.
24. **Tier 2 — merged upstream PR:** [#39081 — bound inactive TUI replay buffer](https://github.com/openai/codex/pull/39081).
25. **Tier 4 — external request:** [#14916 — multi-user deployments](https://github.com/openai/codex/issues/14916).
26. **Tier 4 — external report:** [#35894 — multiple subscribers and dynamic-tool response race](https://github.com/openai/codex/issues/35894).
27. **Tier 4 — external report:** [#34608 — subscription auth with custom `base_url`](https://github.com/openai/codex/issues/34608).
28. **Tier 2 — merged upstream PR:** [#39274 — provider-owned auth recovery](https://github.com/openai/codex/pull/39274).
29. **Tier 2 — merged upstream PR:** [#39141 — redact auth tokens from app-server diagnostics](https://github.com/openai/codex/pull/39141).
30. **Tier 4 — external report:** [#23954 — managed app-server daemon resets](https://github.com/openai/codex/issues/23954).
31. **Tier 4 — external report:** [#35295 — stale dead daemon state](https://github.com/openai/codex/issues/35295).

## Review

Review gate inputs:

- **Changed artifact / consumer:** only this `research.md`; consumer is the user deciding whether
  to change the production Codex CLI. No executable/config consumer changed.
- **Author:** `gpt-5.6-sol`, Codex runtime (session metadata, not agent name).
- **AC:** exact installed/live/latest versions; official release delta; direct issue/PR links for
  all eight requested surfaces; explicit upstream-fixed/open/Orchestra-specific split; actionable
  upgrade/no-upgrade verdict and conditional canary/rollback.
- **Mechanical check:** `git diff --check -- docs/tasks/377/research.md` → exit 0;
  29 direct web links; 24 unique issue/PR ids; secret-shape scan → 0 hits.

Review route: one targeted Sol pass because the conclusion affects production shared runtime,
persistence and subscription auth and therefore cannot use a fact-extraction-only skip.

- **Round 1 verdict:** `APPROVED`; blocking 0, suggestions 2.
- **Disposition:** обе suggestions приняты — resume usage сужен до точного protocol event,
  compaction evidence разделён на два применимых report и один corroborating/inapplicable.
- **Completed-verdict evidence:** reviewer процитировал отсутствовавшую в request строку
  `три согласующихся issue/experiments` и сверил версию/release commit, семь PR ancestors,
  issue states и арифметику `1139.9 / 5 = 228.0 MiB/session`.
- Полный артефакт: `docs/tasks/377/review-research.md`.
