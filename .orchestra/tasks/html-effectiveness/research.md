# `anthropics/html-effectiveness` для Orchestra

**Срез:** 2026-07-24  
**Репозиторий:** `anthropics/html-effectiveness`, `main@58c305be97f47b26b678f2c07dec01d4242268ec`

## Вердикт

**PARTIALLY ADOPT на уровне подхода, не кода.** Не подключать репозиторий как
зависимость и не переносить его HTML/CSS в dashboard. Это галерея примеров к
авторской статье, а не skill, библиотека или frontend framework. Сохранить
standalone/render-first/export-back принципы как критерии для артефактов; новые
специализированные routes добавлять только после повторяющегося реального workflow.
Отдельно от решения по upstream нужно закрыть уже существующую изоляцию preview.

## Вопрос и критерии

- **Контекст:** dashboard Orchestra — FastAPI/Jinja2/HTMX/SSE; агенты создают
  standalone HTML-артефакты.
- **Изменение:** перенять `html-effectiveness` целиком или отдельными паттернами.
- **Baseline:** локальный `~/.claude/skills/html-artifacts/`, versioned
  `pipelines/default/prompts/skills/html-artifacts.md` и текущий file preview.
- **Результат:** net-new полезные сценарии без лишнего prompt/code weight, регрессий
  архитектуры dashboard и расширения XSS/control-plane поверхности.

Гипотеза A: галерея даёт Orchestra новый reusable toolkit. **Фальсификатор:** нет
manifest/API/build/runtime и большая часть сценариев уже покрыта локальным skill.

Гипотеза B: галерея полностью избыточна. **Фальсификатор:** минимум два полезных
сценария отсутствуют в локальной маршрутизации или versioned skill теряет
load-bearing часть паттерна.

Результат: A **REFUTED**, B **REFUTED** → обоснован именно частичный перенос.

## Что это на самом деле

**CONFIRMED — два первичных источника + статический срез репозитория.**

- Официальная статья называет подход личной практикой члена команды Claude Code и
  прямо говорит: сначала достаточно попросить «make an HTML file»; skill имеет смысл
  только позже для повторяющихся паттернов [1].
- Репозиторий — MIT-галерея из 20 standalone `.html` примеров и `index.html`.
  README: «no build step, no dependencies» [2][3].
- В `main` нет `SKILL.md`, package manifest, исходной библиотеки, CLI, API,
  шаблонизатора или тестов [M1]. Слово “templates” в статье означает примеры для
  подражания, не формальную template system.

Итого: **не skill, не library, не framework; executable style/pattern gallery плюс
guidance в сопровождающей статье.**

## Что продвигает

1. **Формат выбирается по форме информации.** Сравнения раскладываются рядом, diff
   получает annotations, процесс — SVG flow, состояние — интерактивные controls;
   HTML не должен быть Markdown с CSS [1][3].
2. **Один самодостаточный файл.** Inline CSS/JS/SVG, открытие прямо в браузере,
   отсутствие build/runtime dependency [2].
3. **Render, а не description.** Design variants, component contact sheets,
   animation/interaction prototypes и diagrams показывают результат в его реальном
   medium [1][3].
4. **Одноразовые problem-shaped editors.** Данные prefilled; triage, config и prompt
   tuning выполняются в UI; финальное состояние обязательно экспортируется обратно
   как Markdown/JSON/diff/prompt. Это замыкает human-in-the-loop [1][3].
5. **Артефакты как контекст следующего шага.** Exploration → выбранный вариант →
   implementation plan → передача новому implement/verification agent [1].

## Измерения и overlap

### M1 — статический inventory upstream

До измерения задан критерий: reusable toolkit существует, если найдётся хотя бы один
manifest, `SKILL.md`, отдельный source module или documented API. Результат:

| Метрика (`01`–`20`) | Результат |
|---|---:|
| Manifest / `SKILL.md` / source module / API | **0** |
| Объём | 10 789 строк, 350 175 bytes |
| Средний пример | 539 строк, 17.5 KB |
| `<meta name="viewport">` | 20/20 |
| JavaScript | 14/20 |
| Любой responsive `@media` | 15/20 |
| `prefers-color-scheme` / print stylesheet | 0/20 / 0/20 |
| Явный `aria-*` или `role=` | 5/20 |
| Внешние runtime-зависимости | 0/20 |

Команды: `find`, `wc`, `rg` по clone `main@58c305be`; критерий toolkit не выполнен.
Dark/print/ARIA grep только описывает границы gallery: semantic HTML может быть
доступным без ARIA, а dark/print не универсальны. Основание не считать upstream
production standard — другое: fictional standalone demos не имеют reusable contract
или тестов.

### M2 — сравнение с локальным skill

Критерий покрытия: сценарий считается **explicit**, только если category index или
отдельный раздел называет его; общая фраза «interactivity/color» даёт **generic**,
не specialized guidance.

| Upstream group | `~/.claude` global skill | Versioned pipeline skill |
|---|---|---|
| Comparisons / implementation plans | explicit | comparisons explicit, plans generic |
| Code review / PR / module map | explicit | absent |
| Design systems / component variants | generic design tokens | absent |
| Animation / interaction prototypes | generic interaction/state language | generic interactivity |
| SVG / flowcharts | explicit | explicit |
| Slide decks | explicit | absent |
| Research / explainers / reports | explicit | reports/status generic |
| Custom editors | explicit + export-back | absent |
| Standalone/offline/output mechanics | explicit | explicit |

Поэтому upstream не даёт пять доказанно **новых** сценариев. Он даёт пять наглядных
примеров без specialized guidance в global skill; versioned skill имеет гораздо
больше пробелов. Главная идея upstream — editor **обязан экспортировать** состояние —
уже есть в global skill (`SKILL.md:44`, `references/editors.md`), то есть это
кандидат на выравнивание двух локальных версий, а не новая находка.

Но Orchestra использует второй, сокращённый versioned skill:
`pipelines/default/prompts/skills/html-artifacts.md` (64 строки). В нём нет
editor/export-back, code-review, deck и design/prototype routes. Более того,
`pipeline.yaml:24,54,69` назначает его только orchestrator; worker/full-cycle его не
получают. `app/prompting.py:183-219` подтверждает, что именно role skills копируются
для Claude и инлайнятся для Codex. Поэтому `~/.claude/skills/html-artifacts/` не
является надёжным cross-backend source of truth для агентов Orchestra.

## Пригодность для Orchestra

### Standalone artifacts: высокая как принцип, недоказанная как новый backlog

Подход совпадает с уже выбранным направлением Orchestra: standalone file, inline
SVG/JS, Telegram delivery, rich preview. Галерея хорошо демонстрирует loop
«манипулируй → export → продолжай с агентом», но исследование не нашло usage data,
доказывающих повторяемый спрос на design-system sheets, component variants или
motion prototypes. По совету самой статьи их надо сначала пилотировать простым
prompt, а route добавлять после повторения [1].

### Dashboard frontend: низкая

Upstream не учит HTMX, Jinja2, SSE, component boundaries, server state, auth,
performance или testing. Его файлы — одноразовые leaf documents; dashboard —
долгоживущее authenticated application. Перенос архитектуры или CSS создаст второй
frontend pattern без решения проблемы. Использовать можно только язык представления
информации: side-by-side comparison, annotated diff, visual timeline, contact sheet.

### Независимая находка: preview security P0

**CONFIRMED — код Orchestra + HTML Standard/MDN.**

`app/static/js/app.js:513-518` открывает агентский HTML с
`sandbox="allow-scripts allow-same-origin"` через same-origin `/api/files/raw`.
Кнопка Open ведёт на тот же raw URL вне iframe. `app/routes/system.py:207-218`
отдаёт файл inline без artifact-specific CSP. HTML Standard и MDN предупреждают:
same-origin iframe с `allow-scripts` + `allow-same-origin` может снять sandbox,
то есть такая комбинация не является защитной [4][5].

Уязвимость существует уже с одним текущим artifact и не является аргументом за или
против adoption upstream. Рекомендованный boundary: отдельный cookie-less origin для
preview; как минимум — убрать `allow-same-origin`, выдавать для HTML строгий
`Content-Security-Policy: sandbox allow-scripts` с запрещённым network/connect, и не
оставлять прямой same-origin Open без sandbox.

## Конкретные рекомендации

| Priority | Действие | Решение |
|---|---|---|
| P0 | Изолировать HTML preview от origin/API Orchestra; покрыть тестом iframe attributes и HTML response headers | **FIX независимо от upstream** |
| P1 | Определить один source of truth/доставку skill: versioned файл сейчас гарантирован только orchestrator; не считать `~/.claude` cross-backend контрактом | **ADOPT** |
| P1 | Явно разделить durable source и review surface: Git-diffable facts/AC остаются Markdown/JSON; HTML — производное представление для чтения/interaction | **ADOPT в текущем skill** |
| Pilot | Для следующего реального editor потребовать prefilled data, visible constraints и export в Markdown/JSON/diff/prompt; после 2+ повторений закрепить route | **TRY, THEN ADOPT** |
| Pilot | Design-system/contact sheet, component variants, motion/interaction prototype сначала вызывать обычным prompt; route добавлять только при повторении | **TRY, THEN ADOPT** |
| P2 | Для интерактивных artifacts добавить semantic controls/labels, keyboard path, `prefers-reduced-motion`; сохранить offline/no-build | **ADOPT как quality floor** |
| — | Vendor/fork 20 HTML-файлов, добавлять JS/CSS framework, переписывать HTMX/Jinja/SSE или копировать upstream aesthetics | **SKIP** |

Не стоит переносить всю глобальную skill-документацию в system prompt: 20 upstream
examples в среднем по 539 строк, а Orchestra оптимизирует tool/context cost. Если
пилоты станут recurring workflow, нужные 5–10 правил следует оставить inline:
текущий injector копирует/инлайнит только один `SKILL.md`, поэтому отдельный reference
без изменения runtime останется невидимым.

## Риски и контраргументы

- Автор статьи считает дополнительный token cost приемлемым и почти отказался от
  Markdown [1]. Для Orchestra это не универсально: task artifacts в Git должны
  оставаться reviewable/diffable, а HTML лучше считать presentation layer.
- HTML повышает шанс, что длинный материал прочитают, но не лечит overproduction.
  Критерий должен быть «пространство/interaction реально несут смысл», а не просто
  `>100 lines`.
- Upstream примеры качественно показывают breadth; M1 не оценивает их полную
  accessibility или production quality, а только подтверждает, что gallery не
  поставляет такой проверяемый contract.

## Second opinion

Codex подтвердил классификацию upstream, mismatch доставки skill, отказ от vendor/
frontend rewrite и severity preview issue. Он опроверг первоначальный переход от
пяти примеров без specialized reference к немедленным P1 routes: usage evidence нет,
а baseline был смешан. После review рекомендации разделены на proven adoption,
workflow pilots и независимый security fix. Полный разбор:
`docs/tasks/html-effectiveness/codex-review-research.md`.

## Затрагиваемые файлы при будущей реализации

- `pipelines/default/prompts/skills/html-artifacts.md`
- `pipelines/default/pipeline.yaml` — только если будет выбрана artifact-producing role
- `app/static/js/app.js`
- `app/routes/system.py`
- `tests/test_frontend.py` и route security tests

## Источники

1. **Primary:** Anthropic/Claude blog, “Using Claude Code: The unreasonable effectiveness of HTML”, 2026-05-20.  
   https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html
2. **Primary:** `anthropics/html-effectiveness` README/repository.  
   https://github.com/anthropics/html-effectiveness
3. **Primary:** rendered gallery/index of 20 examples.  
   https://thariqs.github.io/html-effectiveness/
4. **Primary standard:** WHATWG HTML Standard, iframe sandbox.  
   https://html.spec.whatwg.org/multipage/iframe-embed-object.html
5. **Reference implementation documentation:** MDN `<iframe>` sandbox warning.  
   https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe
