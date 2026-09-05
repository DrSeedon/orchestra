# База знаний — навигация

Факты и доказательства лежат в темах ниже; сырые отчёты — в `.orchestra/tasks/`.
Не читай все темы заранее. Выбери 1–3 отличительных якоря и ищи
`rg -n -i -F --glob '*.md' '<anchor>' .orchestra/kb`.
Читай совпавший факт со статусом и датой, затем его источник при необходимости.
Текущий runtime/config проверяется у владельца; исторический замер не отвечает за сегодня.

- [current-operations](current-operations.md) — Текущие правила и владельцы
- [Правила записи](../guides/knowledge-authoring.md) — доказательства, статусы и актуальность

## Темы

- [prompt-delivery](prompt-delivery.md) — Промпты: сборка и доставка
- [token-efficiency](token-efficiency.md) — Токены: цена и экономия
- [evidence-methods](evidence-methods.md) — Измерения: доказательства и шум
- [test-oracles](test-oracles.md) — Тесты: ложные зелёные результаты
- [test-suite-pruning](test-suite-pruning.md) — Тесты: удаление лишнего
- [dead-code-audit](dead-code-audit.md) — Мёртвый код: достижимость
- [agent-code-intelligence](agent-code-intelligence.md) — Навигация по коду: Serena/LSP
- [codex-runtime](codex-runtime.md) — Codex: модели, контекст, квоты
- [repo-ops](repo-ops.md) — Git, worktree, деплой
- [tg-media-delivery](tg-media-delivery.md) — Telegram: медиа и повторы
- [openrouter-quotas](openrouter-quotas.md) — OpenRouter: квоты :free
- [grep-memory-blowup](grep-memory-blowup.md) — grep: память на длинных строках
- [harness-tools](harness-tools.md) — Harness: встроенные инструменты
- [ox-alpha-harness-verdict](ox-alpha-harness-verdict.md) — Ox Alpha: историческая оценка
- [model-routing-selection](model-routing-selection.md) — Выбор модели и reviewer
- [knowledge-base-architecture](knowledge-base-architecture.md) — KB: архитектура и источники
- [task-storage-architecture](task-storage-architecture.md) — Задачи: Git и SQLite
- [information-architecture-synthesis](information-architecture-synthesis.md) — Данные: общая архитектура
- [data-locality](data-locality.md) — KB: локальность и перенос
- [chat-freshness](chat-freshness.md) — Чат: свежесть snapshot и SSE
- [message-provenance](message-provenance.md) — Сообщения: происхождение
- [agent-memory-architecture](agent-memory-architecture.md) — Память: архитектура агентов
- [prime-agent](prime-agent.md) — Prime Agent и Hermes
- [auto-work](auto-work.md) — Авторабота: триггеры и границы
- [project-portfolio](project-portfolio.md) — Проекты: scope и портфолио
- [dashboard-quota-map](dashboard-quota-map.md) — Квоты: сбои отображения
- [feature-usage-audit](feature-usage-audit.md) — Функции: аудит использования
- [competitive-landscape](competitive-landscape.md) — Harness: сравнение альтернатив
- [antigravity-runtime](antigravity-runtime.md) — Antigravity: протокол и запуск
- [muse-spark-runtime](muse-spark-runtime.md) — Muse Spark: совместимость
- [review-design-defects](review-design-defects.md) — Ревью: ошибки схемы проверки
- [knowledge-pipeline](knowledge-pipeline.md) — Знания: от сырья к фактам
- [founder-intent](founder-intent.md) — Намерения владельца
- [agent-guardrails](agent-guardrails.md) — Агенты: кодовые предохранители
- [code-simplification](code-simplification.md) — Код: упрощение без потери смысла
- [tool-latency](tool-latency.md) — Время инструментов: измерения и ожидания
