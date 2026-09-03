# Research: open-source Grok Build и применимость для Orchestra

**Дата:** 2026-07-16  
**Исследованный revision:** `xai-org/grok-build@c68e39f` (`Publish harness and TUI open-source`)  
**Статус:** Phase 1 complete

## Вопрос

- **Контекст:** Orchestra уже запускает Claude и Codex как отдельные backend-реализации и использует Codex для cross-LLM review.
- **Изменение:** использовать опубликованный исходный код Grok Build — как backend воркеров, отдельный review executor либо источник архитектурных решений.
- **Baseline:** существующий Python `BackendProtocol` + `CodexBackend`, который запускает CLI и нормализует его event stream.
- **Критерий:** нужен стабильный программный transport, управляемая сессия, поток событий, tool/MCP parity и приемлемая цена сопровождения.

## Гипотезы и falsifiers

1. **Grok Build можно подключить тонким CLI-adapter.** Опровергло бы отсутствие headless/structured output или невозможность передать cwd/config/MCP без TUI.
2. **Нужно встраивать Rust runtime или форкать проект.** Опровергается, если публичный CLI/ACP уже покрывает lifecycle и streaming.
3. **Код полезнее как источник паттернов, чем как зависимость.** Опровергло бы наличие маленького стабильного library API с совместимым релизным контрактом.

## Findings

### 1. Это полноценный Rust agent runtime, а не обёртка над API

**CONFIRMED — primary source.** Репозиторий содержит composition root, TUI, shell/runtime, tool implementations, workspace/VCS layer, MCP, sandbox, memory, hooks/plugins, telemetry и ACP. Root workspace включает более 70 crates; `xai-grok-pager-bin` собирает бинарник, `xai-grok-shell` ведёт agent/session lifecycle, `xai-grok-agent` связывает sampler, tool registry и session policy. [1][2][3]

Практическое следствие: переносить runtime в Orchestra бессмысленно. Это второй оркестратор внутри первого с большим дублированием наших session, workspace, MCP и lifecycle слоёв.

### 2. Интеграционный seam уже есть: headless JSON и ACP

**CONFIRMED — primary source.** CLI документирует `grok -p "..." --output-format json` и `--output-format streaming-json`; README прямо называет headless режим пригодным для scripting/CI. Отдельно поддержан Agent Client Protocol для editor/host embedding. [1][4]

Это опровергает H2: для первого прототипа не нужен Rust FFI или fork. Самый узкий путь — subprocess backend, повторяющий структуру `CodexBackend`: argv + cwd/env, чтение JSONL, нормализация событий в `BackendEvent`, interrupt/kill и resume semantics. ACP потенциально чище для долгоживущих сессий, но добавляет новый протокол в Python-код и не нужен до доказанного продукта.

### 3. Model/backend слой уже multi-provider

**CONFIRMED — primary source.** В Grok Build есть три API backend: OpenAI Chat Completions, OpenAI Responses и Anthropic Messages. Custom models задаются конфигом; для Anthropic поддерживается `x-api-key`, для Responses — отдельный `api_backend`. [5]

Следствие: open-source публикация не равна бесплатному Grok inference. CLI можно направить на другие providers, но Grok-модель всё равно требует допустимую аутентификацию/подписку/API. Для Orchestra это снижает уникальность backend: provider diversity уже закрыта Codex, а Grok CLI добавит ещё один agent runtime, не просто модель.

### 4. Tool surface шире минимально необходимого для review

**CONFIRMED — primary source.** Runtime включает terminal/file editing/search, checkpoints/worktrees, TODO state, long-running tasks, compaction, memory, hooks, plugins, skills, MCP OAuth/liveness и web/X search. MCP tool results имеют session-scoped inline cap; sandbox имеет профили `off`, workspace/read-only/strict и platform-specific enforcement. [1][3][6][7]

Для `grok_review` большая часть этого surface лишняя и повышает риск. Review-wrapper должен запускать Grok в read-only/sandboxed режиме и выдавать только артефакт; рабочий backend может раскрывать tools лишь после отдельного parity/security теста.

### 5. Проект открыт, но это периодический export монорепозитория

**CONFIRMED — primary source.** README говорит, что дерево периодически синхронизируется из SpaceXAI monorepo; root `Cargo.toml` generated/read-only. Внешние contributions не принимаются. First-party код Apache-2.0, при этом присутствуют vendored/ported компоненты Codex и OpenCode с отдельными notices. [1][8][9]

Контрсигнал к идее прямой зависимости: публичный source полезен для аудита, но upstream process не обещает обычную community governance или стабильный crate API. Форк означает самостоятельное сопровождение большого generated workspace.

## Сравнение вариантов интеграции

| Вариант | Стоимость | Риск | Польза | Вердикт |
|---|---:|---:|---|---|
| `grok_review` через `grok -p --output-format streaming-json` | низкая | средний: auth, format drift, региональная доступность | независимый review | **Лучший технический seam**, но включать только если доступ и качество оправдают третий reviewer |
| Grok worker backend через subprocess | средняя | высокий: lifecycle/event/tool parity | полноценные Grok workers | Делать после review pilot, не первым шагом |
| ACP client в Orchestra | средняя/высокая | новый protocol/lifecycle | persistent embedding без парсинга CLI | Отложить до проблем с subprocess |
| Встроить/форкнуть Rust runtime | очень высокая | очень высокий | максимум контроля | **Не делать** |
| Переиспользовать отдельные паттерны | низкая | низкий | улучшение Orchestra | Делать точечно после сравнительного аудита |

## Что стоит забрать в Orchestra

1. **Явный composition root.** Grok отделяет pager/TUI, shell/runtime, agent, tools и workspace. У Orchestra уже есть backend boundary; развивать её выгоднее, чем импортировать runtime.
2. **Capability-based sandbox profiles.** Отдельный review executor должен технически лишаться записи/сети, а не получать запрет только промптом.
3. **MCP liveness как state machine.** Grok различает transport closure/health и умеет re-arm watcher; это полезный reference для наших внешних MCP процессов.
4. **Ограничение inline tool results на уровне session.** Это совпадает с принципом Orchestra «не тащить тяжёлые tool_result обратно в контекст».
5. **ACP как будущий общий adapter seam.** Если несколько CLI поддержат ACP стабильно, один ACP backend может быть лучше отдельных JSONL parser'ов. Сейчас это преждевременно.

## Рекомендация

**Не встраивать и не форкать Grok Build.** Если организационные ограничения на Grok сняты, проверять его через минимальный `grok_review` subprocess pilot: один read-only вызов, structured stream, фиксированный output artifact, timeout/interrupt и измерение качества на реальных diff'ах. Только если pilot даст дополнительную находчивость поверх Codex при приемлемой стабильности, расширять до worker backend.

С учётом уже установленной политики Orchestra «только подписка, без API keys» и ранее подтверждённой недоступности Grok для РФ, **реализацию сейчас не начинать**. Open-source release меняет архитектурную прозрачность, но не устраняет auth/legal/product blocker.

## Counter-evidence и неопределённости

- ACP может оказаться стабильнее CLI JSONL и сделать backend дешевле, чем оценено; это проверяется только prototype against released binary.
- Большой runtime не обязательно означает плохую надёжность: модульность, sandbox tests и mock inference server — положительные сигналы.
- Исследован исходный revision, но не выполнен end-to-end inference: доступ к Grok/auth не предоставлен. Поэтому совместимость конкретных JSON events с Orchestra остаётся **LIKELY**, не CONFIRMED.
- Репозиторий опубликован одним snapshot; стабильность публичных crate/API boundaries пока не доказана историей релизов.

## Affected files при будущем pilot

- `app/backend_grok.py` — новый subprocess adapter.
- `app/backend_protocol.py`, `app/session.py`, `app/models.py` — регистрация backend/model и lifecycle.
- `app/mcp_stdio.py`, `app/bg_jobs.py` — только если делается отдельный `grok_review` tool.
- `tests/test_backend_grok.py`, `tests/test_mcp_grok_review.py` — JSONL fixtures, interruption, malformed events, missing binary/auth.

## Sources

1. [Grok Build README at c68e39f](https://github.com/xai-org/grok-build/blob/c68e39f/README.md) — primary.
2. [Root Cargo workspace](https://github.com/xai-org/grok-build/blob/c68e39f/Cargo.toml) — primary.
3. [`xai-grok-agent/src/agent.rs`](https://github.com/xai-org/grok-build/blob/c68e39f/crates/codegen/xai-grok-agent/src/agent.rs) и [`builder.rs`](https://github.com/xai-org/grok-build/blob/c68e39f/crates/codegen/xai-grok-agent/src/builder.rs) — primary.
4. [Headless mode documentation](https://github.com/xai-org/grok-build/blob/c68e39f/crates/codegen/xai-grok-shell/README.md#headless-mode) — primary.
5. [Custom model/API backend guide](https://github.com/xai-org/grok-build/blob/c68e39f/crates/codegen/xai-grok-pager/docs/user-guide/11-custom-models.md) — primary.
6. [`xai-grok-mcp` source](https://github.com/xai-org/grok-build/tree/c68e39f/crates/codegen/xai-grok-mcp/src) — primary.
7. [`xai-grok-sandbox` profiles](https://github.com/xai-org/grok-build/blob/c68e39f/crates/codegen/xai-grok-sandbox/src/profiles.rs) — primary.
8. [CONTRIBUTING.md](https://github.com/xai-org/grok-build/blob/c68e39f/CONTRIBUTING.md) — primary.
9. [THIRD-PARTY-NOTICES](https://github.com/xai-org/grok-build/blob/c68e39f/THIRD-PARTY-NOTICES) — primary.

## Confidence summary

| Claim | Confidence | Evidence |
|---|---|---|
| Grok Build — модульный Rust agent runtime | CONFIRMED | код + workspace manifest |
| Headless subprocess integration возможна | CONFIRMED | официальный README/CLI docs |
| Тонкий adapter дешевле fork/embedding | LIKELY | подтверждён seam; prototype не запускался |
| ACP нужен на первом этапе | REFUTED | headless JSON уже закрывает критерий pilot |
| Open-source снимает доступ/auth blocker | REFUTED | исходники не предоставляют inference entitlement |
| Реализацию Grok backend стоит начинать сейчас | REFUTED | policy/access + избыточность относительно Codex |
