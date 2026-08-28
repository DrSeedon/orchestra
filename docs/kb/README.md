# База знаний — по темам, не по номерам задач

Это то, что агент обязан прочитать ДО работы (гейт в модуле `memory-search`). Одна тема =
один файл = один владелец. `docs/tasks/<id>/research.md` остаётся сырым артефактом задачи;
сюда попадает вывод и доказательство, по которому его можно перепроверить.

**Формат темы — четыре раздела, строка = один факт:**

```markdown
# <тема>

## Установлено
- <утверждение> · <доказательство: файл:строка | команда + число | ссылка> · <дата, #задача>

## Отвергнуто
- <во что верили или что пробовали> · <чем опровергнуто> · <дата, #задача>

## Пробелы
- <вопрос без ответа> · <что помешало> · <дата, кто спрашивал>

## Источники
- docs/tasks/<id>/research.md — <одна фраза, о чём он>
```

**Правила:**
1. Дописывать, не переписывать. Опровергнутая строка получает
   ` — ОТОЗВАНО <дата> #<задача>: <чем>` и ОСТАЁТСЯ: удалив её, мы теряем единственную запись
   о том, что эта дорога закрыта.
2. Утверждение без доказательства в той же строке сюда не попадает.
3. «Пробелы» — источник следующих ресёрчей. Пустой раздел на живом вопросе означает, что края
   не смотрели, а не что вопрос закрыт.
4. Новая тема → строка в этом файле. Тема без строки через три недели превратится во второй
   файл про то же самое.

## Темы

- [prompt-delivery](prompt-delivery.md) — что агент РЕАЛЬНО получает в промпте: сборка ролей,
  модули, зеркала, доставка правок.
- [token-efficiency](token-efficiency.md) — из чего состоит цена хода, что реально её снижает,
  чужие замеры токен-сберегающих скиллов и способ доставки правил.
- [evidence-methods](evidence-methods.md) — чем доказывают, что работа сделана и число верно:
  проверки, врущие в сторону «всё хорошо», пороги, негативные контроли, мутационные проверки.
- [test-oracles](test-oracles.md) — почему зелёный прогон ничего не доказывает: оракулы, живые
  пробы в гейте мержа, общий рантайм и боевые креды в worktree.
- [test-suite-pruning](test-suite-pruning.md) — измеренный аудит pytest-набора: доказанные
  удаления, тесты на переписывание, ложные дубли и границы безопасной чистки.
- [dead-code-audit](dead-code-audit.md) — доказательная проверка достижимости production-кода:
  Serena/LSP, AST, runtime registries, динамические входы и безопасные удаления.
- [agent-code-intelligence](agent-code-intelligence.md) — измеренные границы Serena/LSP,
  нативного `rg`+AST и лёгкого code-intelligence MCP для задач агентов.
- [codex-runtime](codex-runtime.md) — Codex/Sol, выбор моделей, лимиты, потолки раундов ревью,
  приоритет пулов и отозванные сравнения по квоте.
- [repo-ops](repo-ops.md) — git, деплой, systemd, секреты в артефактах, дубли одной мысли в двух
  файлах, воркеры, чужая машина.
- [tg-media-delivery](tg-media-delivery.md) — timeout и UNKNOWN-семантика отправки файлов в
  Telegram, риск дублей и контракт durable per-file receipts/outbox.
- [openrouter-quotas](openrouter-quotas.md) — лимиты бесплатных моделей OpenRouter (1000/сутки, 20/мин),
  где брать число запросов: /api/v1/key не даёт, analytics API даёт но нужен management key.
- [grep-memory-blowup](grep-memory-blowup.md) — почему `grep` в сессии Claude Code съедает
  гигабайты на шаблоне `.{0,N}литерал.{0,M}`, чем это грозит на VPS и чем заменять.
- [harness-tools](harness-tools.md) — аудит шести встроенных тулов рантайма harness: grep,
  read, write/edit, glob, dispatch — что молча врёт и что проверено замерами.
- [ox-alpha-harness-verdict](ox-alpha-harness-verdict.md) — вердикт первого рабочего дня Ox Alpha
  на своём харнесе: 858 вызовов без ошибок тула, честные отрицательные результаты — и три
  расхождения отчёта с артефактом за день; почему приёмка по артефакту обязательна.
- [model-routing-selection](model-routing-selection.md) — текущие executable/prompt owners выбора reviewer и worker model, omission/default behavior, effort и supersession evidence (#229).
- [knowledge-base-architecture](knowledge-base-architecture.md) — canonical evidence, typed fact promotion/supersession, freshness generations, hot/warm/cold delivery and #256 baseline.
- [task-storage-architecture](task-storage-architecture.md) — Git-canonical задачи с SQLite-проекцией, стабильным ID и сохраняемым проектным `#N`; двухконтурная синхронизация и baseline #299.
- [information-architecture-synthesis](information-architecture-synthesis.md) — joined typed namespace/data plane, separate task/evidence/fact/session/resource contracts, OpenViking transfer verdicts and #315 plan.
- [data-locality](data-locality.md) — fixed project-local `docs/kb/` owner, exact distribution
  ledger, one-record JSON format, cutover consumers and rollback proof.
