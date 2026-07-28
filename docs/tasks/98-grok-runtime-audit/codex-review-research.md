## Summary

🧪 `CONFIRMED`, как выяснилось, тоже нуждается в подтверждении. Основная диагностика верна: `turn_completed.totalTokens` является агрегатом, guard пропускает отсутствующий обязательный MCP, а вся приведённая арифметика сходится. Значений секретов или PII в артефакте не найдено.

Но исследование пока нельзя использовать как окончательную основу Phase 2: причина MCP-инцидента не доказана, предлагаемый conformance-контракт допускает подмену одноимённым сервером, а удаление OpenCode и единый metadata-registry обоснованы слабее, чем заявлено.

## Findings

### blocking: Проверяйте идентичность MCP, а не только имя

Предложенная проверка `required ⊆ started ⊆ allowed` сравнивает только имена серверов ([research.md:807](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:807)). Текущий backend также сохраняет из уведомления только `name` ([backend_grok.py:547](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:547)) и сравнивает множества имён ([backend_grok.py:342](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:342)). Поскольку intended ACP-конфиг и обнаруженный `.mcp.json` оба называются `orchestra`, доверенный repo-local сервер может удовлетворить обеим границам, даже если запущена чужая команда с другим окружением. Это ломает заявленную security-гарантию. Контракт должен подтверждать источник/конфигурацию или handshake конкретного Orchestra-сервера либо полностью исключать repo autodiscovery.

### suggestion: Оставьте H1 и причину trust нерешёнными

Наличие `orchestra` в собранном `session/new` доказывает лишь композицию на стороне Orchestra, но не опровергает замену или коллизию внутри Grok ([research.md:50](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:50)). `inspect` обнаружил одноимённую запись именно из `.mcp.json`, а приведённая диагностика относится к repo-local серверу. Положительный переход trust не выполнен, поэтому не доказано, что trust является gate именно для explicit ACP record. Нужен тест с уникальными именами: с/без `.mcp.json`, trusted/untrusted, с различимыми командами. До него H1 — `INCONCLUSIVE`, а trust — только кандидат причины; поздняя оговорка `LIKELY` не исправляет более сильные формулировки в Verdict и H1.

### suggestion: Не называйте реконструкцию точным историческим payload

Артефакт называет результат «exact/sanitized session/new payload» и ставит `CONFIRMED` ([research.md:117](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:117)), хотя это реконструкция из DB и текущего кода, а не сохранённый wire payload. Backend также выбирает между `session/load` и `session/new` по наличию native session id ([backend_grok.py:290](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:290)), а итоговое окружение зависит от runtime state. Корректная формулировка: «current-code reconstruction under stated environment assumptions»; подтверждённым остаётся наличие generated `orchestra` в результате этой реконструкции.

### suggestion: Не приравнивайте последний prompt к контексту после turn

Сумма 25 `prompt_tokens` действительно равна `1,665,949`, а `input + output = 1,678,471`; ошибка использования агрегата в backend подтверждается ([backend_grok.py:832](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/backend_grok.py:832)). Но `84,482` — размер входа последнего model call, а не доказанный occupied context после его completion ([research.md:405](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:405)). Финальный output и runtime serialization могут увеличить следующий prompt. Это не спасает ложные 100% — даже грубая верхняя граница остаётся далеко от 500K, — но поле следует назвать `last_call_prompt_tokens`, пока не измерен следующий prompt или поддерживаемая turn-end метрика.

### suggestion: Сделайте удаление OpenCode условным

Нулевая локальная история подтверждает отсутствие текущего использования, но не отсутствие продуктового пути. `fetch_models_from_proxy()` прямо загружает динамические модели ([models.py:254](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/models.py:254)), а модели без явного runtime направляются через inference ([models.py:323](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/models.py:323)); предусмотрены даже aliases для Gemini/Llama/Mistral. Поэтому измерения уверенно поддерживают удаление опасного catch-all и fail-loud для неизвестной модели, но не безусловное удаление adapter. Решение следует поставить после проверки всех deployments, proxy-конфигураций и runtime plugins — именно тех проверок, которые документ пока откладывает.

### suggestion: Не смешивайте model, provider, quota и runtime в одну запись

Предложенный единый registry должен одновременно владеть model matching, runtime capabilities, provider/accounting bucket и UI metadata ([research.md:796](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:796)). Но текущая модель намеренно разделяет `ModelSpec(runtime, provider)` ([models.py:19](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/models.py:19)) и runtime harness/capabilities ([runtime_registry.py:65](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/runtime_registry.py:65)). OpenCode уже является контрпримером отношению один runtime → один provider, а quota-card в UI — ещё одна отдельная сущность. Доказательства поддерживают exhaustive validation и запрет Claude fallback, но не этот объединённый контракт. Для MVP проще сохранить две плоские сущности и валидировать их согласованность.

### question: Что означает «reject impossible current context»?

Предложение требует отвергать `current > max` вместо clamp ([research.md:589](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:589)). Если это исключение при создании `turn_end`, ошибка телеметрии способна потерять usage или рассинхронизировать статус сессии. Следует заранее определить fail-soft семантику: сохранить usage, пометить context неизвестным и поднять заметное предупреждение; сам turn при этом не должен исчезнуть.

## Verdict

**Changes required.** Выводы об aggregate-vs-current, неверном MCP guard и раздельных provider adapters выдерживают проверку, а числовые суммы корректны. Причина trust, точность реконструкции, безопасность MCP-контракта и безусловное удаление OpenCode требуют пересмотра до Phase 2.

Иначе аудит починит ложные 100% тем же методом: уверенно покажет 100% там, где измерено только 16,9%. 🙃

## Round (2026-07-28T13:08:57Z)

## Summary

🧪 Почти всё закрыто — но матрица, которая должна проверить collision, предусмотрительно убрала сам collision. Предыдущие замечания по historical payload, unknown context, fail-soft usage, identity-aware conformance и разделению metadata исправлены. Headline-арифметика сходится; значений секретов или PII не найдено.

## Findings

### blocking: Матрица с разными именами не проверяет same-name collision

Предложенный 2×2 использует различимые имена ([research.md:368](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:368)), поэтому изолирует trust/autodiscovery, но не precedence двух записей с именем `orchestra` — именно сценарий инцидента. Нужен дополнительный same-name эксперимент с разными командами и проверяемой identity; иначе Phase 2 может пропустить подмену repo-local сервером.

### blocking: Inventory должна предшествовать и удалению fallback

Документ предлагает убрать unknown-model fallback немедленно, а inventory сделать только перед удалением adapter ([research.md:819](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:819)). Но proxy loader прямо назначает fallback runtime моделям без `runtime/backend` ([models.py:323](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/app/models.py:323)). Неинвентаризированный deployment с такой proxy-моделью после изменения потеряет рабочий маршрут. Сначала inventory и миграция моделей на explicit runtime, затем удаление fallback и adapter.

### suggestion: Не называйте оценочный prompt split точным

Раздел признаёт отсутствие per-section токенов и использование другого tokenizer ([research.md:457](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:457)), но затем называет `32,047` «exact conversation subtotal» ([research.md:463](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:463)). Точен только общий prompt `38,710`; разделение `32,047 / 6,663` является calibrated estimate.

### suggestion: Уберите несопоставимый Grok/Sol context ratio

Таблица делит Grok last-call prompt на Sol stored context metric и получает `1.36×` ([research.md:591](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/98-grok-runtime-audit/research.md:591)), хотя документ не подтверждает одинаковую семантику этих полей. Этот ratio не поддерживает вывод и должен быть удалён либо помечен non-comparable.

## Verdict

**Changes required.** Основные выводы об aggregate usage, ложной compaction и раздельных adapters выдержали повторную проверку. Осталось исправить порядок OpenCode inventory и дополнить MCP-эксперимент настоящим same-name collision case; остальные замечания не блокируют Phase 2.

Иначе collision-тест получится как проверка пожара без огня: чисто, безопасно и совершенно бесполезно. 🔥

## Round (2026-07-28T13:11:37Z)

## Summary

✅ Ну надо же, эксперименты теперь проверяют именно то, что написано на этикетке. Все четыре замечания второго раунда исправлены:

- trust/autodiscovery и same-name collision разведены в отдельные эксперименты;
- inventory и migration предшествуют удалению fallback;
- prompt partitions явно обозначены как calibrated estimates;
- несопоставимый Grok/Sol context ratio удалён.

Предыдущие исправления также сохранены. Арифметика согласована; credential values, secrets и PII не обнаружены.

## Findings

Нет blocking, suggestion или question findings.

## Verdict

**Approved.** Research достаточно аккуратно отделяет подтверждённые факты от неизвестного и задаёт безопасные Phase‑2 gates. Оставшиеся неопределённости явно перечислены и не маскируются под выводы.

Три раунда понадобились, зато теперь `CONFIRMED` хотя бы не носит накладные усы. 🥸
