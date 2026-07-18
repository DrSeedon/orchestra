## Summary

Тезисы в основном выдерживают атаку, но доказательство по #84 проваливается на границе доступных данных — классика: отсутствие нашли там, куда ревьюеру смотреть нельзя. 😏

## Findings

- blocking: Claim 4 не доказан разрешёнными источниками. `results.jsonl` подтверждает только одобрение перехода к Phase 2; отсутствие `self_learning.py`, таблицы и флага обосновано отдельным repository-wide search (`research.md:543-545`), который не воспроизводим по разрешённому evidence set. Формулировку следует ослабить до «implementation не подтверждена доступными evidence» либо приложить допустимый manifest/search artifact.
- suggestion: P0–P7 назван «sound», хотя это пока экспертная гипотеза без cost/impact measurement. Особенно спорно ставить общий evaluator в P2 после P1: минимальный regression benchmark и promotion contract лучше определить до проектирования registry schema, иначе поле `evaluator result` закрепит ещё не существующий контракт.
- suggestion: Cross-family routing снижает correlated-error risk, но не создаёт настоящую evaluator independence. Claude и Codex остаются LLM judges с потенциально общими данными и сходными biases; независимость дают executable oracles, независимый held-out набор и организационное разделение. Использовать термин «diversified critic», а не `independent critic`.
- suggestion: Inventory недостаёт практического shadow/canary deployment: candidate prompt следует сначала прогонять в shadow mode или на ограниченной роли с автоматическим fallback, а не переходить сразу от offline held-out evaluation к human merge. Git rollback не компенсирует уже испорченные реальные ответы.
- suggestion: P1 хранит raw-source linkage и rejected proposals, но retention/redaction/access policy описана только как acceptance-фраза `no secrets/raw prompt dump`. Нужны TTL, минимизация содержимого, deletion/export semantics и защита от durable prompt injection до накопления production corrections.
- suggestion: Внутренняя ссылка `[I2]` включает `docs/experiments/85/report.md`, которого нет в разрешённом evidence set; при этом численные выводы должны ссылаться непосредственно на `experiment-results.md` и `results.jsonl`. Иначе локальная трассируемость зависит от недоступного документа.

## Verdict

APPROVED WITH SUGGESTIONS — после ослабления либо воспроизводимого подтверждения claim 4. А то #84 сейчас признали несуществующей по следам отсутствия следов — почти археология, только с SQLite.

## Round 2

### Prior findings

- F1: FIXED — `local-evidence.md` фиксирует checkout, команды, exit codes и ограничивает вывод текущим checkout.
- F2: FIXED — evaluation contract и evaluator теперь идут в P0–P1, registry schema заблокирована ими в P2.
- F3: FIXED — cross-family review назван diversified critic и явно не считается независимым oracle.
- F4: FIXED — перед production promotion предусмотрены shadow mode, ограниченный canary и automatic fallback.
- F5: FIXED — registry охватывает минимизацию, redaction, project-scoped access, TTL, deletion/export и недопуск untrusted provenance к executable instructions без promotion.
- F6: FIXED — `[I2]` прямо указывает `docs/tasks/85/experiment-results.md:1-77` как источник численных результатов #85.

### New blockers

- none

### Verdict

APPROVED
