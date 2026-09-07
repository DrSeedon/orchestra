# База знаний — навигация

Шестнадцать тем; факты и доказательства лежат в них, сырые отчёты — в `.orchestra/tasks/`.
Не читай темы заранее. Возьми 1–3 отличительных якоря и найди
`rg -n -i -F --glob '*.md' '<якорь>' .orchestra/kb`.
Читай совпавшую запись вместе с её разделом (`Established` — принято, `Rejected` — отвергнуто,
`Gaps` — неизвестно, `Historical observations` — срез прошлого) и датой.
Текущий рантайм и конфиг проверяются у владельца; исторический замер за сегодня не отвечает.

- [current-operations](current-operations.md) — Что действует сейчас и у кого спрашивать
- [Правила записи](../guides/knowledge-authoring.md) — доказательства, статусы и актуальность

## Темы

- [founder-intent](founder-intent.md) — Владелец: замысел продукта и дословные решения
- [evidence-methods](evidence-methods.md) — Замеры: как доказать число и не поймать шум
- [code-and-tests](code-and-tests.md) — Код и тесты: что доказано, что мертво, что лишнее
- [review](review.md) — Ревью: дефекты схемы проверки и калибровка от проекта
- [models-and-quotas](models-and-quotas.md) — Выбор модели, цена и квоты
- [runtimes](runtimes.md) — Рантаймы CLI: Codex/Sol, Antigravity, Muse Spark
- [agent-tools](agent-tools.md) — Инструменты агента: что врут, сколько ждут, где жрут память
- [knowledge-base](knowledge-base.md) — База знаний и память агентов: устройство, источники, локальность
- [agent-control](agent-control.md) — Промпты, правила и предохранители: как текст становится действием
- [tasks-and-projects](tasks-and-projects.md) — Задачи, проекты, портфолио: хранение и жизненный цикл
- [token-efficiency](token-efficiency.md) — Токены: цена, экономия и отозванные обещания
- [repo-ops](repo-ops.md) — Git, worktree, деплой, секреты в артефактах
- [auto-work](auto-work.md) — Авторабота и самоулучшение: когда система действует сама
- [external-harnesses](external-harnesses.md) — Чужие харнесы и агенты: что у них есть и что мы взяли
- [chat-and-telegram](chat-and-telegram.md) — Чат, Telegram и происхождение сообщений
