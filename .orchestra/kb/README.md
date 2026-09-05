# База знаний — навигация

Факты и доказательства лежат в темах ниже; сырые отчёты — в `.orchestra/tasks/`.
Не читай все темы заранее. Выбери 1–3 отличительных якоря и ищи
`rg -n -i -F --glob '*.md' '<anchor>' .orchestra/kb`.
Читай совпавший факт со статусом и датой, затем его источник при необходимости.
Текущий runtime/config проверяется у владельца; исторический замер не отвечает за сегодня.

- [current-operations](current-operations.md) — действующие ограничения и владельцы текущего состояния
- [Правила записи](../guides/knowledge-authoring.md) — доказательства, статусы и актуальность

## Темы

- [prompt-delivery](prompt-delivery.md) — что агент РЕАЛЬНО получает в промпте
- [token-efficiency](token-efficiency.md) — из чего состоит цена хода
- [evidence-methods](evidence-methods.md) — доказательства, шум измерений, ложные проверки
- [test-oracles](test-oracles.md) — почему зелёный прогон ничего не доказывает
- [test-suite-pruning](test-suite-pruning.md) — измеренный аудит pytest-набора
- [dead-code-audit](dead-code-audit.md) — доказательная проверка достижимости production-кода
- [agent-code-intelligence](agent-code-intelligence.md) — измеренные границы Serena/LSP
- [codex-runtime](codex-runtime.md) — Codex/Sol
- [repo-ops](repo-ops.md) — Git, worktree, деплой, процессы и ресурсы машины
- [tg-media-delivery](tg-media-delivery.md) — Telegram: timeout, UNKNOWN, повторы отправки
- [openrouter-quotas](openrouter-quotas.md) — квоты бесплатных маршрутов OpenRouter
- [grep-memory-blowup](grep-memory-blowup.md) — расход памяти grep на длинных строках
- [harness-tools](harness-tools.md) — аудит шести встроенных тулов рантайма harness
- [ox-alpha-harness-verdict](ox-alpha-harness-verdict.md) — вердикт первого рабочего дня Ox Alpha
- [model-routing-selection](model-routing-selection.md) — текущие executable/prompt owners выбора reviewer и worker model
- [knowledge-base-architecture](knowledge-base-architecture.md) — canonical evidence
- [task-storage-architecture](task-storage-architecture.md) — Git-canonical задачи с SQLite-проекцией
- [information-architecture-synthesis](information-architecture-synthesis.md) — joined typed namespace/data plane
- [data-locality](data-locality.md) — fixed project-local `.orchestra/kb/` owner
- [chat-freshness](chat-freshness.md) — чат в дашборде берётся ТОЛЬКО из сети
- [message-provenance](message-provenance.md) — явное происхождение `user_message`
- [agent-memory-architecture](agent-memory-architecture.md) — общая память поверх project-local `.orchestra/kb`
- [prime-agent](prime-agent.md) — Prime Agent и Hermes против нашего контура
- [auto-work](auto-work.md) — что у нас может запускаться автоматически
- [project-portfolio](project-portfolio.md) — `scope` как технический ключ против человеческого проекта
- [dashboard-quota-map](dashboard-quota-map.md) — браузерный `TimeoutError` при обновлении квоты
- [feature-usage-audit](feature-usage-audit.md) — замороженный срез #309
- [competitive-landscape](competitive-landscape.md) — сравнение ADE/harness и границы отличий
- [antigravity-runtime](antigravity-runtime.md) — официальный `agy` headless/NDJSON и MCP технически совместимы с runtime Orchestra
- [muse-spark-runtime](muse-spark-runtime.md) — Muse Spark 1.3
- [review-design-defects](review-design-defects.md) — измеренные design-miss/coverage seams ревью
- [knowledge-pipeline](knowledge-pipeline.md) — единый ledger «сырьё → candidates → sink → release»
- [founder-intent](founder-intent.md) — замысел создателя из его дословных ответов
- [agent-guardrails](agent-guardrails.md) — code-enforced guardrails production-агентов
- [code-simplification](code-simplification.md) — доставка требования «упрости»
