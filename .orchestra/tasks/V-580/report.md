# V-580 — сравнение research-методов и патч

## Объём и вывод

Сверены только `agent-skills/*/SKILL.md` в OpenResearch и
`.orchestra/pipelines/default/prompts/modules/research-method.md`. Файлы
`references/`, код OpenResearch и `roles/orchestrator.md` не читались и не менялись.

Полезный переносимый слой — не научная схема «узел → прогон → победитель», а три
механических страховки: ограничивать расход поиска/замеров, не считать промежуточный
статус доказательством без идентичности запуска и держать источник рядом с каждым
утверждением. Они добавлены в модуль. Научные правила заморозки узлов и ветвления от
победителя отвергнуты как несовместимые с разовыми правками живой платформы.

## Сравнение промпта с промптом

Ссылки на наш текст — строки текущего модуля после патча; «до» означает, что правило
не было сформулировано в нём явно.

| Приём OpenResearch и цитата | Есть ли у нас до патча | Чем наш текст слабее/сильнее; решение |
|---|---|---|
| `orx-lit-review`: «difficulty 1–3 gets 0 rounds, 4–7 gets 1, and 8–10 gets 2» (`orx-lit-review/SKILL.md:79–80`) и «The budget is a hard cap, not a target» (`:121–130`). | Частично: `research-method.md:129–133` масштабировал глубину, но не требовал бюджета до первого вызова и не запрещал пустые повторы. | Их формулировка сильнее против перерасхода; у нас теперь обобщённое правило для поиска и замеров (`research-method.md:30–35`) без чужой шкалы сложности. **Забрано.** Ошибка на нашем материале: агент повторяет одинаковый поиск или пробу и съедает малое free-окно без новой информации. |
| `orx-lit-review`: «Never spend a round merely rephrasing an existing search» (`:127–130`) и остановка при достаточном покрытии (`:118–120`). | Частично: было только «narrow or broaden based on results» (`research-method.md:30–32`). | Их stop-условие точнее. Встроено в новое bounded-budget правило (`research-method.md:33–35`). **Забрано.** Ошибка: агент продолжает “исследовать” уже решённый вопрос и откладывает действие. |
| `orx-lit-review`: «place the supporting source link immediately after each substantive scholarly claim» и «discovery-only result list may link candidate titles, but must not imply … verified from snippets» (`:159–162`). | Частично: источник должен быть реально открыт (`research-method.md:72–75`), но связь источника с конкретным утверждением и запрет на snippet-as-proof не были явными. | Их traceability сильнее; добавлено правило соседнего источника/замера и разграничение списка кандидатов и доказательства (`research-method.md:77–78`). **Забрано.** Ошибка: агент превращает найденный заголовок, issue-сниппет или поисковый фрагмент в доказанный факт о нашей платформе. |
| `orx-evidence`: «Echo the configuration the run actually used so the log identifies the variant» и «If a run's result is not in its log, it cannot be inspected later» (`orx-evidence/SKILL.md:26–33`). | Частично: были обязательны метрики/pass-fail и сырые outputs (`research-method.md:80–90`), но не идентичность ревизии и эффективного входа. | Их evidence-контур лучше защищает воспроизводимость; добавлено требование ревизии, effective config/input и end effect (`research-method.md:95–98`). **Забрано.** Ошибка: агент запускает тест не на той ревизии/конфигурации и объявляет исправление живого пути по одному статусу процесса. |
| `orx-evidence`: «Never infer a result from run status or memory» и проверка, что лог содержит supporting output (`orx-evidence/SKILL.md:35–45`). | Частично: уже запрещено считать промежуточный успех доказательством (`research-method.md:101–103`), но не было отдельного требования отвергать сам command status. | Наше существующее правило уже сильнее для optional/no-op цепочек; короткая добавка о command status (`research-method.md:95–98`) делает общий случай явным. **Забрано без дублирования механики.** Ошибка: зелёный exit-код подменяет проверку observable delivery/эффекта. |
| `orx-compute`: «Each run uses an immutable snapshot … recorded commit» и «Keep the run command fixed» (`orx-compute/SKILL.md:5–6, 19–25`). | Нет как общего правила, но это связано только с их backend/experiment runner. | Полная фиксация команды и env нам не подходит: в живой Orchestra правка может требовать нового запуска сервиса, а проектные команды не являются экспериментальными siblings. Взята только переносимая часть — записывать revision/effective input (`research-method.md:95–98`). **Частично забрано, остальное отвергнуто.** |
| `orx-experiment-tree`: «Once a run does answer the node … the node is frozen … branch a child instead» (`orx-experiment-tree/SKILL.md:29–33`). | Нет. | Для нашей платформы это неверная модель: ошибка может требовать починки того же production path, а задача обычно не повторяется как научный node. **Отвергнуто.** Добавление создало бы ложный запрет на исправление живой системы. |
| `orx-experiment-tree`: «Repair cap: two runs in a row that answer nothing … then ask the user» (`:40–42`). | Нет такой числовой границы. | Это лимит повторных экспериментальных прогонов, не общий лимит диагностики. Наш bounded budget задаётся до поиска/замера и не изобретает число, которое могло бы остановить нужное восстановление. **Отвергнуто.** |
| `orx-experiment-tree`: «small fan within a round … descend onto that round's winner» (`:65–81`). | Нет. | Ветка winner/child имеет смысл для оптимизации модели, но не для правки текущего кода: у нас рабочий baseline — развернутый путь, а не набор научных вариантов. **Отвергнуто.** |
| `orx-lit-review`: «Run the loop below yourself» (`:68–70`) и запрет делегировать retrieval (`SKILL.md:3`). | Нет в `research-method`; ownership поиска задают orchestration/worker правила. | Это routing-политика и дублировала бы другой слой. Для текущего модуля важен результат и источник, а не кто именно из агентов нажал retrieval. **Отвергнуто.** |
| `orx-lit-review`: специальные alphaXiv/OpenAlex ID, дедупликация DOI/arXiv и правила ссылок (`:105–117, 131–157`). | Нет. | Это API- и предметно-специфичные детали OpenResearch, не применимые к SQLite/SSE/CLI расследованиям Orchestra. **Отвергнуто.** |

## Патч и предотвращаемые ошибки

1. **Bounded retrieval/measurement** — добавлены две строки в `Step 2`
   (`research-method.md:33–35`). Предотвращает повтор одинакового запроса/пробы и
   расход free-квоты без нового сигнала; останавливает поиск, когда исход уже решаем.

2. **Traceability на уровне утверждения** — добавлены две строки в `Step 4`
   (`research-method.md:77–78`). Предотвращает вывод о поведении платформы из
   поискового сниппета или списка кандидатов без открытого источника/замера.

3. **Идентичность и observable effect прогона** — добавлены две строки в `Step 5`
   (`research-method.md:95–98`). Предотвращает ложное «починено»: команда вернула
   `0`, промежуточный вызов сработал или тест запускался на другой ревизии, но живой
   end effect не проверен.

До правки модуль: 9291 байт; после первого патча: 9809 байт, +518 байт (+5.6%).
После review-уточнения: 9942 байта, +651 байт (+7.0%), меньше допуска +10%. Изменён
только `research-method.md`; `roles/orchestrator.md`, `project_goal`, `project_wait`
и portfolio не затронуты.

Срез OpenResearch для ссылок: репозиторий
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-openresearch`, commit
`6dd4b3bd44bad034edb3ec5b05bb08b607bb340d` (рабочее дерево чистое на момент чтения).
Это фиксирует прочитанный каталог скиллов, не импортируя его в Orchestra.

## Проверка доставки

Запущено:

```text
uv run --frozen pytest -q tests/test_default_pipeline.py tests/test_check_pipeline_manifest.py
76 passed in 8.60s
```

`python -m pytest` выполнить нельзя: в окружении нет команды `python`, а системный
`python3` не содержит pytest. `uv run` использовал CPython 3.12.3; импортированный
модуль приложения — `/home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/app/__init__.py`.

Проверки покрывают реальный default-манифест, сборку system prompt и доставку общих
модулей ролям, а также согласованность манифеста. Литеральный тест на новый текст не
добавлялся: контрактом является доставка модуля и его механика, не формулировка.
Дополнительно через loader проверено, что `research-method` приходит ровно один раз
в `full-cycle` и не протекает в `orchestrator`, `sub-orchestrator`, `worker` или
`reducer` (это соответствует текущему манифесту).

## Review и ограничения

После первого коммита Luna implementation-review
(`.orchestra/tasks/V-580/review.md`) дал `APPROVED`, блокирующих дефектов не нашёл.
Замечание о неоперационном слове «bounded» принято: финальная формулировка требует
конкретного потолка в calls/rounds/time/spend, но не навязывает универсальное число.
Уточнение про outcome-sensitive environment/model принято для воспроизводимости;
полный тестовый прогон повторён после него.

Проверена доставка текста в роли и отсутствие синтаксических/манифестных нарушений.
Повторный live-прогон агентов не выполнялся: патч меняет только инструкции, а не
исполнительный код; эффект формулировок остаётся гипотезой до следующего наблюдаемого
сценария. Числовая квота намеренно не зашита в модуль: потолок зависит от конкретной
задачи, риска и маршрута.
