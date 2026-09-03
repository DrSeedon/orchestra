# #127 — отчёт Phase 3

Правки сделаны строго по списку оркестратора (4 пункта), за границы списка не выходил.
Основание каждой — `docs/tasks/127/research.md`.

## Что изменено

| # | Файл | Правка | Основание |
|---|---|---|---|
| T1 | `pipelines/default/prompts/roles/worker.md` (−2 стр.)<br>`pipelines/default/prompts/roles/full-cycle.md` (−2 стр.) | Удалён `**Adversarial self-review.** Before committing, find 2-3 potential bugs or weak spots in your own code…` — оба вхождения, дубль одной фразы | §Self-correction гайда: объект проверки — свой вывод, нового наблюдения не порождает, триггер безусловный. Единственное дословное попадание в класс, который гайд велит удалять |
| T2 | `pipelines/default/prompts/modules/orchestration.md` (+6/−1) | Step 0.5: `Otherwise delegate; hesitation means the gate failed` → `Unclear scope is a reason to delegate, not to start editing yourself` + потолок с ценой спавна | §Controlling subagent spawning: *"Do not delegate work you can finish yourself in a handful of tool calls… use one rather than several"* |
| T3 | `CLAUDE.md` (+1/−1) | PROCESS RULES: «максимально параллельно» → «параллельность — средство, а не цель»; спавн оправдан независимостью работы, а не наличием свободной модели. Механика очереди и `check_conflict` сохранена дословно | То же + замер §5.3 research.md |
| T4 | `pipelines/default/prompts/base.md` (+8) | Новый абзац в `<communication-style>`: письменные артефакты освобождены от краткости, но не от калибровки | §Written deliverable length. У нас правила не было ни одного (греп по всем файлам), при медиане 10.3 КБ и максимуме 61.8 КБ |

Формулировка T4 (ключевая, потому что легко испортить):

> **Written artifacts (`docs/tasks/*.md`, reports, docs you write to disk) are exempt from
> brevity, not from calibration.** Length is earned by NEW facts: a quote you fetched, a number
> you measured, a file:line, a decision and its basis. Evidence is never the thing you cut — a
> long document made of measurements is correctly long. What comes out regardless of total
> length: a section that restates an earlier one, a summary of the summary, boilerplate framing,
> and a table that repeats the paragraph above it. If a section contains no fact absent from the
> rest of the document, it is padding whether the file is 5 KB or 50 KB.

Порог задан наличием новых фактов, а не размером файла — отчёт с доказательствами этим правилом
не режется, что и требовалось.

## Проверка (артефакты, не рассказ)

**1. Правки доехали до собранного промпта, а не только до файлов.** Проверял через
`app.pipeline.build_system_prompt`, то есть тем же кодом, которым промпт собирается воркеру:

```
worker        bytes= 22507  adversarial=gone  calibration=yes  gate=n/a
full-cycle    bytes= 38614  adversarial=gone  calibration=yes  gate=n/a
orchestrator  bytes= 39582  adversarial=gone  calibration=yes  gate=new
```

`gate=n/a` у воркеров корректно: `orchestration.md` входит только в оркестраторские роли.

**2. Тесты.** `uv run python -m pytest tests/test_pipeline.py tests/test_default_pipeline.py
tests/test_tasks_pm_pipeline.py -q` → **123 passed, 7 skipped in 8.47s** (`/tmp/pytest-127.log`).
Полный сьют не гонял — запрещено постановкой. `uv.lock` не изменился (`git status` чист, кроме
5 правленых файлов).

**3. Висячих ссылок на удалённое правило нет.** `grep -rn "Adversarial\|self-review" pipelines/
CLAUDE.md` → два попадания, оба про другое: «Codex недоступен → self-review вместо вердикта»
(`skills/codex-debate.md:104`, `CLAUDE.md:192`). Это фолбэк при отказе внешнего ревьюера с
требованием честно записать «вердикта нет», а не постоянная инструкция самопроверки. Оркестратор
их в список не включал — не трогал.

**4. Бюджет зеркала `AGENTS.md`.** `CLAUDE.md` 51 526 → **51 905 байт** (+379) при
`project_doc_max_bytes = 65536` → занято 79.2 %, запас 13 631 байт.

## Взгляд Sol/Spark/Grok на каждую правку (условие оркестратора)

Зеркалится только T3 (`CLAUDE.md`); T1/T2/T4 живут в `pipelines/` и в `AGENTS.md` не попадают,
но попадают в собранный системный промпт воркера любого рантайма.

- **T1 — единственная правка, где рекомендация специфична для Opus 5.** Утверждение «модель ловит
  свои ошибки сама» Anthropic делает про свою модель; для Sol/Spark/Grok оно не проверено никем.
  Смягчающее обстоятельство: удалённая фраза требовала «найти 2-3 бага в своём коде» — то есть
  ровно перечитывание без нового наблюдения, и её отсутствие не отменяет ни одного правила про
  предъявление артефакта, которые для не-Anthropic рантаймов и держат качество. Наш собственный
  контрпример (Spark пропустил double-count, пойманный Sol) касается **ревью на дешёвой модели**,
  а не самопроверки — маршрутизация финальных ревью не менялась.
- **T2, T3 — нейтральны к рантайму:** цена спавна и независимость работы от модели не зависят.
- **T4 — нейтральна:** склонность писать длинные документы у Sol и Grok не измерена, но правило
  запрещает только текст без новых фактов, что верно для любого рантайма.

Ничего из свода доказательств (секции «Проверка и доказательства», «ПРОВЕРЬ ПЕРЕД РАБОТОЙ»,
`research-method`) не тронуто.

## ОТКРЫТЫЙ ВОПРОС — не закрыт этой задачей

Различие «самопроверка текста против предъявления артефакта», на котором держится решение резать
2 строки вместо секции, **выведено мной из примеров гайда, а не заявлено в нём**. Формулировка
*"legacy harness scaffolding that adds separate verification steps"* достаточно широка, чтобы
накрыть и наш Codex-гейт, и пофазовые гейты `full-cycle`. Если Anthropic имели в виду широкое
прочтение, правильный объём резки больше сделанного.

**Чем закрывается:** A/B `full-cycle` на одинаковом наборе заданий — с секцией «Проверка и
доказательства» и без неё, метрика «доля выводов, у которых за спиной артефакт». Такого замера
нет ни у нас, ни у Anthropic (гайд не приводит ни чисел, ни методики). До него любая массовая
резка правил проверки — решение на веру.

**Второе, что осталось незакрытым по решению оркестратора** (отдельные задачи с замером):
калибровочный блок ревью с `"nit" = skip` против §Code review гайда («be conservative»
исполняется буквально и снижает находимость); свежий effort sweep вместо унаследованных
`xhigh`/`high`/`medium`.

## Что осталось на решение оркестратора

`CHANGELOG.md` ведётся руками (автосборка отозвана, `172ab22`) и содержит записи такого класса.
Правка меняет поведение всех агентов, то есть на запись тянет — но версию и формулировку
CHANGELOG выбирает владелец файла, а я вышел бы за границы списка. Запись не добавлял.

## Итог

Файлы: `CLAUDE.md`, `pipelines/default/prompts/base.md`,
`pipelines/default/prompts/modules/orchestration.md`,
`pipelines/default/prompts/roles/{worker,full-cycle}.md` — **+14/−6 строк**.
Breaking: нет. Промпт воркера вырос на 487 байт, оркестратора — на 1 005.
