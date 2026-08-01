# Prompt engineer — постоянная база знаний

Обновлено: 2026-08-01. Это рабочая шпаргалка, не журнал задач. Перед правкой промпта
сначала найди измеренный сбой, после — проверь тот же сценарий. Внешние рекомендации
не переносить между моделями без локального eval.

## Уровни доказательств

- **[LOCAL]** — логи, код или эксперимент Orchestra; главный источник для наших промптов.
- **[PROVIDER]** — актуальная документация OpenAI/Anthropic; авторитетна для своей модели,
  но это не независимое исследование и не гарантия на другом провайдере.
- **[PAPER]** — опубликованный эксперимент; проверяй модели, задачи и дату до переноса.
- Нет источника или замера → это гипотеза. Не превращать её в постоянное правило.

## Рабочий цикл правки промпта

1. Сформулируй наблюдаемый сбой: кто, на каком событии, что сделал/не сделал; возьми 3–10
   реальных трасс, если они есть. Массово переписывать промпт без baseline нельзя. [O1][L1]
2. Определи метрику до правки: доля соблюдения, число лишних вызовов/раундов, ошибки,
   полнота артефакта. Для качества используй репрезентативные задачи, не один красивый ответ. [O1]
3. Классифицируй правило: инвариант, условное решение, рецепт, формат результата или стиль.
4. Внеси минимальную правку одного класса и перезапусти те же кейсы. GPT-5.6 guide прямо
   рекомендует менять по одной группе инструкций/примеров/тулов. [O1]
5. Сохрани только изменение с измеримым эффектом. Новый текст без следа — шум, не страховка.

## Исполнимая инструкция

Надёжная форма:

```text
WHEN: проверяемое событие или состояние.
DO: одно действие либо точный рецепт.
WHY: конкретный предотвращаемый ущерб.
EXCEPT: закрытый список исключений, если он нужен.
DONE WHEN: наблюдаемое условие завершения.
```

- Момент должен определяться без «ощущений»: `перед первым Read/Grep`, `перед DONE`,
  `после третьего инфраструктурного падения`, а не `когда кажется знакомым`. [L4][A2]
- Для настоящего инварианта используй `must/always/never`; для контекстного выбора — явное
  `if X → A; else → B`. OpenAI советует абсолюты только для инвариантов. [O1]
- Для Claude не усиливай каждую строку `CRITICAL/MUST`: новые Claude могут overtrigger;
  обычное ясное `Use X when Y` лучше для условного поведения. [A1]
- Пиши желаемое действие, не только запрет. Anthropic отдельно рекомендует positive instruction. [A1]
- Точный путь/команда/формат копируются буквально: в Orchestra pytest-команда дала 270
  вызовов у 20 агентов, правило `/tmp` — 859 вызовов у 42 агентов без найденных нарушений. [L1]

### Кейс `memory-search` — эталон болезни и исправления

- Было: `feels done before`, `smells familiar`, `may surface`, `rarely needed` — разрешение
  без момента действия. Снимок логов: 15 агентов, около 60 совпадений, медиана 1–2;
  `audit-fullcycle` был выбросом 29, `audit-overeng` на аудите 26k строк вызвал тул один раз. [L4]
- Стало: обязательный первый вызов **до первого Read/Grep** для перечисленных типов задач,
  плюс закрытые исключения и причина (не повторять исследование/грабли). [L4]
- Контраст: `always worker_wip before kill_worker` стоит ровно у события, называет действие
  и потерю данных; операционно соблюдается. [L4]
- Вывод: императив сам по себе не магия. Работает связка **событие → действие → причина →
  исключения**; для гарантии уровня API используй enforcement/tool choice, если доступно. [A2]
- Сильный запрет тоже обходится, если он называет ярлык, а не наблюдаемое действие: Opus 5
  переименовал запрещённую очередь новой задачи в «контекст на будущее». Привязывай gate к
  моменту tool call, status/`task_id` и эффекту; явно ранжируй конфликтующие эвристики. [L4]
- Если политика зависит от типа сущности, тип должен жить в видимом состоянии, а не выводиться
  из имени: `fix-*` оказался и одноразовым, и постоянным. Введи явный marker при создании,
  а немаркированный legacy трактуй консервативно. [L4]

## Архитектура и порядок промпта

- Начинай с результата, success criteria, существенных ограничений и stop rules; процесс
  расписывай только когда сам процесс является контрактом. Это текущая рекомендация Codex/GPT-5.6. [O1][O2]
- Не закапывай несущую инструкцию в середину длинного контекста. В TACL 2024 relevant evidence
  в начале/конце извлекалась лучше, чем в середине; это long-context evidence, не доказательство
  универсального порядка всех правил. [P1]
- Для Claude с 20k+ токенов: длинные документы сверху, запрос/инструкции после них; Anthropic
  сообщает до 30% улучшения качества при query в конце на сложных multi-doc тестах. [A1]
- Практическое правило: goal/инварианты — в начале релевантного блока; переменные данные — отдельно;
  финальный task/query — рядом с местом генерации. Не дублируй правило «в начало и в конец».
- Одна мысль = один источник истины. Если решение принимается в другом месте, перенеси правило
  туда либо дай ссылку. Дубли расходятся: у нас протухала копия model-routing, а background-jobs
  одновременно жил в трёх местах. [L3]
- Role/persona помогает фокусу и тону, но не заменяет goal, критерии и границы. [A1][O1]

## Zero-shot, few-shot и примеры

- Начинай с zero-shot baseline. Добавляй examples только если они исправляют измеренный сбой
  формата, тона, неоднозначной классификации или edge case. Неработающий пример удалить. [O1]
- Few-shot не обязательно «обучает правильному рассуждению»: в EMNLP 2022 случайные labels
  почти не ухудшили ряд classification/multiple-choice задач; важными оказались label space,
  input distribution и формат. Не переносить этот результат на генерацию/код без eval. [P2]
- Для Claude Anthropic рекомендует 3–5 релевантных, разнообразных, структурированных примеров
  и `<examples>`; для GPT-5.6 OpenAI советует убирать примеры, не меняющие behavior. [A1][O1]
- Пример должен зеркалить реальный вход и показывать трудную границу, а не идеальный happy path.
  Несколько примеров должны быть разнообразны, иначе модель выучит случайный паттерн. [A1][P2]
- Если формат машинный, schema сильнее примера: OpenAI Structured Outputs и Anthropic strict
  tool use обеспечивают schema conformance; «верни JSON как в примере» этого не гарантирует. [O4][A2]

## Chain-of-thought, reasoning и декомпозиция

- Не добавляй универсальное `think step by step`. Мета-анализ 100+ работ и тест 20 datasets ×
  14 models: сильный эффект CoT главным образом на math/symbolic/logic; на commonsense,
  language understanding и reading comprehension — мало или ноль. [P3]
- Для GPT-5.6 сначала проверь success criterion/tool routing/verification и reasoning effort;
  актуальная инструкция OpenAI прямо относит generic `think step by step` к anti-patterns. [O1]
- Для Claude сначала меняй `effort`/adaptive thinking; Anthropic предупреждает о latency и
  overthinking на высоком effort и советует thinking для реально multi-step задач. [A1]
- Публичный CoT не является доказательством правильной причины: coherent rationale может быть
  неверным или неfaithful; Anthropic показал неполное раскрытие использованных hints. [A3][P4]
- Проси проверяемые промежуточные артефакты: факты с источниками, расчёт, тест, diff, invariants,
  а не приватный внутренний монолог.
- Декомпозируй, когда подзадачи зависимы и композиционная сложность реальна. Least-to-most дал
  99.7% против 16% CoT на SCAN у code-davinci-002, но это узкий старый benchmark, не универсальная
  лицензия плодить фазы. [P5]
- Наш аудит: research и review risky plan ловили дефекты, но `plan.md` при уже заданном плане
  становился ритуалом. Декомпозиция окупается границами состояния/проверки, не количеством файлов. [L1]

## Claude против Sol/Codex в Orchestra

- **Фактический транспорт:** Claude получает preset `claude_code` + наш appended system prompt;
  Codex получает его как `developerInstructions`. Project `CLAUDE.md` зеркалится Codex в
  `AGENTS.md`; skills у Sol сейчас инлайнятся полностью. [L5]
- **Личная память:** manager оборачивает файл в `<worker-memory>` при spawn/load. Правка файла
  внутри уже живой сессии не перечитывается самим `compact()`; до reload/restart prompt cache
  содержит прежнюю версию. Не обещай мгновенный refresh без отдельного механизма. [L5]
- **Claude:** ясные explicit instructions, motivation/context, XML для смешанного контента,
  3–5 examples; latest models буквальнее и могут overtrigger от агрессивных MUST. [A1]
- **Sol/GPT-5.6:** outcome + constraints + evidence + completion bar, затем свобода выбрать
  эффективный путь; absolutе rules только для invariants, judgment — через decision rule. [O1]
- **Tools:** Claude `auto` выбирает по request + description; сильный first-tool imperative
  повышает trigger, `tool_choice` гарантирует. GPT-5.6: оставлять только task-relevant tools,
  описывать when/returns/errors и routing prerequisites. [A2][O1]
- **Не переносить prompt hacks:** у нас «95% Codex reviews find bugs» было верно для старого
  Claude-корпуса и не перенеслось на Sol. Сравнивать провайдеры на одинаковых кейсах. [L3]

## Экономика и жёсткие лимиты

- [LOCAL] Sol cost гонит число tool calls, не объём промпта/результатов: OLS n=103,
  `cost = 0.898 + 0.0859*calls + 1.140*MB`, R²=0.646; доля calls ≈70%, bytes ≈4%
  (95% CI bytes −13…21%). Цифры не округлять до закона природы; устойчив порядок факторов. [L2]
- Следствие: сокращай промпт ради ясности, свежести, cache stability и лимита, не обещай
  заметную экономию денег. Экономию дают меньше лишних раундов/вызовов при сохранённом качестве. [L2][O1]
- Codex собирает цепочку `AGENTS.md` root→CWD и обрезает её на `project_doc_max_bytes`, default
  32,768 bytes. Наш эксперимент подтвердил обрыв **посреди фразы**; Claude файл читал целиком. [O3][L3]
- На 2026-08-01 `CLAUDE.md` = 32,385 bytes: запас **383 bytes**. Базовая кириллица в UTF-8 —
  2 bytes/символ; считай `wc -c`, не символы. Машинный `project_doc_max_bytes=98304` — страховка,
  не переносимая на VPS/новую машину. [L3]
- Критическое новое правило должно вытеснить менее ценное; нельзя просто дописывать конец файла,
  который Sol может физически не увидеть.

## Антипаттерны и замена

- `be careful / use judgment / when familiar` → observable trigger + action + completion bar.
- Два разных числа/маршрута для одного решения → один decision rule; противоречие хуже недосказанности. [O1]
- Одинаковая мысль в role/module/tool docstring → один owner; в остальных местах ссылка. [L3]
- Полный rewrite «по best practices» → один measured failure, одна surgical edit, тот же eval. [O1]
- Больше prose «для полноты» → оставить только outcome, constraints, routing, validation, stop rules. [O1]
- Только запреты → positive safe path. [A1]
- Few-shot/CoT/XML как ритуал → применять только в подтверждённой provider/task зоне. [P2][P3][A1]
- Вывод одного провайдера объявлен общим → отдельный eval Claude и Sol. [L3]
- Prompt-only гарантия там, где есть schema/hook/tool_choice/test → использовать enforcement. [O4][A2]

## Источники

- **[L1]** `docs/tasks/fullcycle-audit/research.md` — traces 28k calls, working/dead rules, phases.
- **[L2]** `docs/tasks/sol-efficiency/research.md` — OLS n=103 и raw TSV/scripts.
- **[L3]** `docs/tasks/context-engineering/research.md` — 32 KiB experiment, duplicate drift.
- **[L4]** read-only `orchestra.db` snapshots + prompt incidents `memory-search` and
  active-worker task queue / kill lifecycle (2026-08-01).
- **[L5]** `app/backend_claude.py`, `app/backend_codex.py`, `app/runtime_registry.py`,
  `app/manager.py`, `app/workspace.py` — фактическая сборка prompt stack.
- **[O1]** [OpenAI: Prompting guidance for GPT-5.6 Sol](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6) (checked 2026-08-01).
- **[O2]** [OpenAI: Prompting Codex](https://learn.chatgpt.com/docs/prompting).
- **[O3]** [OpenAI: AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
- **[O4]** [OpenAI: Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- **[A1]** [Anthropic: Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices) (checked 2026-08-01).
- **[A2]** [Anthropic: Tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).
- **[A3]** [Anthropic: Reasoning models don't always say what they think](https://www.anthropic.com/research/reasoning-models-dont-say-think).
- **[P1]** [Liu et al., TACL 2024 — Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/).
- **[P2]** [Min et al., EMNLP 2022 — Role of Demonstrations](https://aclanthology.org/2022.emnlp-main.759/).
- **[P3]** [Sprague et al., 2024 — To CoT or not to CoT?](https://arxiv.org/abs/2409.12183).
- **[P4]** [Wang et al., ACL 2023 — What Matters in CoT](https://aclanthology.org/2023.acl-long.153/).
- **[P5]** [Zhou et al., ICLR 2023 — Least-to-Most Prompting](https://arxiv.org/abs/2205.10625).
