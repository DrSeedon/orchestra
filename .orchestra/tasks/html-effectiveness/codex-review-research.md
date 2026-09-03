Ну да, написать `CONFIRMED` заметно проще, чем доказать, почему именно эти три паттерна внезапно стали P1. 🙃

## Summary

Основные факты проверку выдержали:

- Upstream действительно является галереей из 20 автономных HTML-примеров без build step и dependencies, а не skill/library/framework. Это прямо подтверждает [README upstream](https://github.com/anthropics/html-effectiveness).
- Vendor примеров и смена HTMX/Jinja/SSE ничем не обоснованы.
- Гарантированная доставка versioned `html-artifacts` действительно ограничена top-level orchestrator.
- Preview уязвим уже сейчас: `allow-scripts allow-same-origin`, same-origin API и прямое открытие HTML делают security P0 обоснованным. Это совпадает с предупреждениями [WHATWG](https://html.spec.whatwg.org/multipage/iframe-embed-object.html) и [MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe).

Слабое место исследования — не факты об upstream, а переход от них к конкретному backlog: выбор design/prototype/export как единственных P1 непоследователен и не подтверждён реальными workflow.

## Findings (blocking/suggestion/question)

### suggestion: Использовать один baseline для gap-анализа

[research.md:100](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:100)

Документ признаёт, что versioned skill не содержит editor/export, code-review, deck и design/prototype routes, но рекомендует добавить только design/prototype и export. Если source of truth — versioned skill, code-review и deck являются такими же пробелами; если baseline — глобальный skill, то animations, parameter tuning, state transitions и editors там уже явно описаны в [SKILL.md:18](/home/maxim/.claude/skills/html-artifacts/SKILL.md:18). Нужна единая таблица `upstream example → гарантированно доставляемое правило → реальный пробел`; нынешний набор рекомендаций выбран непоследовательно.

### suggestion: Не называть пять сценариев net-new

[research.md:93](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:93)

Метрика `15/20` не воспроизводима: отсутствуют поэлементное сопоставление и критерий, когда общее правило считается покрытием. Более того, глобальный skill уже упоминает animation/interactions, design tokens и one-off editors. Доказано отсутствие отдельных routes/references, но не самих сценариев; формулировку `net-new value — пять сценариев` следует заменить на `пять сценариев без специализированной инструкции`.

### suggestion: Не повышать непроверенные workflow до P1

[research.md:147](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:147)

Исследование не показывает спроса на design-system sheets, component variants или motion prototypes. История репозитория содержит HTML для comparisons, architecture, reviews и plans, но не подтверждает повторяемость выбранных новых routes. Это особенно важно потому, что [сама статья Anthropic](https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html) советует сначала просто запрашивать HTML и создавать skill лишь после появления recurring patterns. Для MVP доказательства поддерживают пилот или `ADOPT при реальном workflow`, но не P1.

### suggestion: Не выводить production readiness из ARIA/dark/print grep

[research.md:84](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:84)

Отсутствие явного `aria-*` не означает плохую доступность: корректные semantic elements часто не требуют ARIA. Dark mode и print stylesheet также не являются универсальными критериями production quality. Эти числа описывают ограничения галереи, но ничего не «доказывают». Достаточное основание не копировать примеры целиком уже даёт README: fictional standalone demos без тестируемого reusable contract.

### suggestion: Не рекомендовать reference, который runtime не доставит

[research.md:154](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:154)

Предложенный `design-and-prototypes.md` сейчас останется невидимым: Claude-инъектор копирует только выбранный файл как `SKILL.md` в [prompting.py:183](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/app/prompting.py:183), а Codex инлайнит только его содержимое через [prompting.py:203](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/app/prompting.py:203). Для минимального решения правила следует оставить inline; иначе в scope нужно явно добавить изменение обоих механизмов загрузки.

### suggestion: Отделить существующий security P0 от решения по upstream

[research.md:125](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/research.md:125)

Severity верна, причинная связь — нет. Уязвимость уже эксплуатируема одним текущим artifact: iframe получает scripts и same-origin в [app.js:513](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/app/static/js/app.js:513), а [raw endpoint](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/app/routes/system.py:207) отдаёт тот же HTML без CSP; отдельная кнопка вообще открывает его вне sandbox. Это самостоятельный security blocker независимо от того, будет ли skill расширен. Его нужно оставить P0, но вынести из аргументации `PARTIALLY ADOPT`.

## Verdict

**PARTIALLY SUPPORTED — revise before approval.**

Claims 1, 3 и 4 подтверждены; отказ от vendor и смены frontend stack также обоснован. Но конкретный вывод «добавить именно design/prototype/export как P1» не следует из gap-анализа и usage evidence. Security P0 можно принимать отдельно, остальные adoption-рекомендации следует вернуть в статус кандидатов или пилота.

Иначе backlog получается как текущий iframe sandbox: название защиты есть, а доказательная граница уже снята. 🔓

## Round 2

### Re-review status

1. **FIXED — baseline унифицирован.** M2 теперь задаёт explicit/generic criterion и
   сопоставляет upstream groups с global и versioned skills; рекомендации больше не
   выбирают design/prototype routes как единственные доказанные пробелы.
2. **FIXED — пять примеров больше не названы net-new scenarios.** Они корректно
   описаны как examples без specialized guidance, а export-back — как уже известный
   кандидат на выравнивание локальных skills.
3. **FIXED — недоказанные workflow сняты с P1.** Editor и design/prototype routes
   переведены в pilots: сначала обычный prompt, затем route после 2+ повторений.
4. **FIXED — production readiness больше не выводится из ARIA/dark/print grep.**
   Метрики оставлены только как описание gallery; основание сформулировано через
   отсутствие reusable contract и тестов.
5. **FIXED — невидимый progressive reference больше не рекомендован.** Будущие
   5–10 правил остаются inline; ограничение текущего injector/inliner явно записано.
6. **FIXED — preview security отделён от upstream decision.** P0 сохранён как уже
   существующая уязвимость и помечен `FIX независимо от upstream`.

### New findings

Новых blocking или non-blocking factual/reasoning findings нет.

### Verdict

**APPROVED.** Load-bearing выводы подтверждены, спорные adoption-рекомендации
переведены в pilots, а независимый security P0 корректно сохранён.

## Round (2026-07-24T13:25:02Z)

Ну надо же, второй раунд действительно починил выводы, а не только переставил уверенные слова. ✅

## Re-review status

1. Baseline и gap-анализ — **FIXED**
2. «Пять net-new сценариев» — **FIXED**
3. Непроверенные P1 workflow — **FIXED**
4. Production readiness по ARIA/dark/print — **FIXED**
5. Невидимый progressive reference — **FIXED**
6. Security P0 смешан с upstream adoption — **FIXED**

## New findings

Новых factual/reasoning findings нет.

## Verdict

**APPROVED.**

`Round 2` добавлен в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-html-eff/docs/tasks/html-effectiveness/codex-review-research.md:60). Каталог untracked, поэтому содержимое проверено через `git diff --no-index`.

На этот раз sandbox остался дырявым только в продукте, а не в аргументации. 🔓
