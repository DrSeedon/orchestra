# #119 — Чем Codex делает красивые HTML-артефакты

**Дата:** 05.08.2026 · **Фаза:** 1 (research) · **Правок в коде НЕТ**

---

## Вопрос (Step 0)

- **Контекст:** Codex CLI 0.146.0 (`@openai/codex`), установлен глобально на этом VPS.
- **Проверяемое утверждение (юзер):** «Codex делает красивые HTML-артефакты не нашим скиллом
  `html-artifacts`, а каким-то своим». Нужен ДОСЛОВНЫЙ текст этой инструкции.
- **База сравнения:** наш глобальный `~/.claude/skills/html-artifacts/SKILL.md` (12 219 байт)
  и проектная копия `pipelines/default/prompts/skills/html-artifacts.md` (2 357 байт).
- **Измеримый исход:** найден ли на диске/в первоисточнике текст, который отвечает за визуальное
  качество, и можно ли его перенести.

## TL;DR — вердикт

Инструкция **есть, и она не одна.** Но ни одна из них не является «скиллом про HTML-артефакты»,
и ту, что даёт максимум красоты, **наши Sol-воркеры не получают вообще**.

| # | Что нашлось | Где | Достаётся ли нашим воркерам |
|---|---|---|---|
| 1 | `## Frontend guidance` / `### Design instructions` — 21 правило про вёрстку, палитру, иконки, карточки, типографику | зашито в бинарь codex, шаблон модели **`gpt-5.5`** | **НЕТ** — у нас `gpt-5.6-sol` |
| 2 | `## Frontend tasks` — «не скатывайся в AI slop» | зашито в бинарь, шаблоны **`gpt-5.4`/`gpt-5.4-mini`/`codex-auto-review`** | **НЕТ** |
| 3 | `### Visualizations` — когда вообще рисовать визуал | зашито в бинарь, шаблоны **`gpt-5.6-sol/terra/luna`** | **ДА** (проверено в живом rollout) |
| 4 | **`visualize.css` — готовая дизайн-система на 101 правило** (токены, таблицы, формы, тултипы, 6-цветная палитра серий) | `codex-rs/tui/src/inline_visualization/assets/visualize.css`, Apache-2.0 | **НЕТ** — рендерер живёт только в TUI |
| 5 | Агентский `SKILL.md`, на который ссылается CSS | **не поставляется ни в бинаре, ни в публичном репозитории** | — |
| 6 | Плагин `openai-templates` (20 «artifact-template-*» скиллов) | `~/.codex/plugins/cache/…` | Это **.pptx/.docx/.xlsx**, к HTML отношения не имеет |

**Главный практический вывод:** «красота», которую видел юзер, — это (4), дизайн-система
inline-визуализаций Codex. Она **открыта, лежит под Apache-2.0 и переносима целиком**.
А (1) — это текст-инструкция, которая переносима как формулировки.

---

## Как это воспроизвести (команды рабочие, проверены)

```bash
# 0. где стоит Codex
which codex; npm ls -g --depth=0 | grep codex        # @openai/codex@0.146.0
BIN=/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex

# 1. вытащить ВСЕ зашитые системные промпты моделей (8 штук)
#    ВНИМАНИЕ: `strings` тут врёт — он рвёт строку на первой типографской кавычке (U+2019).
#    Читать надо сырые байты.
python3 - <<'EOF'
import json, pathlib, re
B = pathlib.Path("/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex").read_bytes()
key = b'"instructions_template": '
dec = json.JSONDecoder(); i = 0
while True:
    i = B.find(key, i)
    if i < 0: break
    text, _ = dec.raw_decode(B[i+len(key):i+len(key)+200000].decode("utf-8", "replace"))
    slug = re.findall(r'"slug":\s*"([^"]+)"', B[i-6000:i].decode("utf-8", "replace"))[-1]
    pathlib.Path(f"codex-instructions-{slug}.md").write_text(text)
    print(slug, len(text), "## Frontend guidance" in text)
    i += 1
EOF

# 2. дизайн-система — берётся из ПУБЛИЧНОГО репозитория (первоисточник)
curl -sO https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/inline_visualization/assets/visualize.css
curl -sO https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/inline_visualization/assets/visualize.html
curl -sO https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/terminal_visualization_instructions.rs

# 3. доказать, что бинарь и репозиторий — один и тот же файл (см. «Сверка» ниже)
```

Все выгруженные файлы лежат рядом: `docs/tasks/119/extracted/`.

---

## Гипотезы и что с ними стало (Step 1)

| Гипотеза | Фальсификатор, который я искал | Итог |
|---|---|---|
| **(а)** У Codex CLI есть встроенная инструкция/скилл про HTML-артефакты | отсутствие текста про HTML/вёрстку в бинаре и в `~/.codex/` | **ЧАСТИЧНО ПОДТВЕРЖДЕНА.** Инструкции про *frontend/дизайн* есть и зашиты в бинарь. Отдельного «скилла про HTML-артефакт-файл», аналога нашего, **НЕТ** |
| **(б)** Отдельной инструкции нет, красота от базовой модели | наличие дословных дизайн-правил | **ОПРОВЕРГНУТА** для gpt-5.4/5.5 — правила дословные и очень конкретные. **ПОДТВЕРЖДЕНА для gpt-5.6-sol**: в его шаблоне дизайн-правил нет ни одного |
| **(в)** Красивое видели не в CLI, а в вебе (canvas и т.п.) | наличие рендерера в CLI-коде | **ОПРОВЕРГНУТА как «чужой продукт»**, но с оговоркой: рендерер живёт в CLI (`codex-rs/tui/`), однако **только в TUI**. Orchestra запускает `codex app-server --stdio` (`app/backend_codex.py:358`), то есть **не TUI** → наши воркеры этот путь не проходят никогда. Значит юзер видел красивое либо в своём личном TUI-сеансе, либо в вебе |

---

## Находка 1 — `## Frontend guidance` (модель `gpt-5.5`). CONFIRMED

**Источник (tier 1, измерение):** байты бинаря
`/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex`,
смещение 248332713, поле `instructions_template` записи с `"slug": "gpt-5.5"`.
Полный текст шаблона — `extracted/codex-instructions-4.md` (19 754 символа).

Это и есть основной генератор «красивостей». Дословно:

```
## Frontend guidance

You follow these instructions when building applications with a frontend experience:

### Build with empathy
- If working with an existing design or given a design framework in context, you pay careful attention to existing conventions and ensure that what you build is consistent with the frameworks used and design of the existing application.
- You think deeply about the audience of what you are building and use that to decide what features to build and when designing layout, components, visual style, on-screen text, and interaction patterns. Using your application should feel rich and sophisticated.
- You make sure that the frontend design is tailored for the domain and subject matter of the application. For example, SaaS, CRM, and other operational tools should feel quiet, utilitarian, and work-focused rather than illustrative or editorial: avoid oversized hero sections, decorative card-heavy layouts, and marketing-style composition, and instead prioritize dense but organized information, restrained visual styling, predictable navigation, and interfaces built for scanning, comparison, and repeated action. A game can be more illustrative, expressive, animated, and playful.
- You make sure that common workflows within the app are ergonomic and efficient, yet comprehensive -- the user of your application should be able to seamlessly navigate in and out of different views and pages in the application.

### Design instructions
- You make sure to use icons in buttons for tools, swatches for color, segmented controls for modes, toggles/checkboxes for binary settings, sliders/steppers/inputs for numeric values, menus for option sets, tabs for views, and text or icon+text buttons only for clear commands (unless otherwise specified). Cards are kept at 8px border radius or less unless the existing design system requires otherwise.
- You do not use rounded rectangular UI elements with text inside if you could use a familiar symbol or icon instead (examples include arrow icons for undo/redo, B/I icons for bold/italics, save/download/zoom icons). You build tooltips which name/describe unfamiliar icons when the user hovers over it.
- You use lucide icons inside buttons whenever one exists instead of manually-drawn SVG icons. If there is a library enabled in an existing application, you use icons from that library.
- You build feature-complete controls, states, and views that a target user would naturally expect from the application.
- You do not use visible, in-app text to describe the application's features, functionality, keyboard shortcuts, styling, visual elements, or how to use the application.
- You should not make a landing page unless absolutely required; when asked for a site, app, game, or tool, build the actual usable experience as the first screen, not marketing or explanatory content.
- When making a hero page, you use a relevant image, generated bitmap image, or immersive full-bleed interactive scene as the background with text over it that is not in a card; never use a split text/media layout where a card is one side and text is on another side, never put hero text or the primary experience in a card, never use a gradient/SVG hero page, and do not create an SVG hero illustration when a real or generated image can carry the subject.
- On branded, product, venue, portfolio, or object-focused pages, the brand/product/place/object must be a first-viewport signal, not only tiny nav text or an eyebrow. Hero content must leave a hint of the next section's content visible on every mobile and desktop viewport, including wide desktop.
- For landing-page heroes, make the H1 the brand/product/place/person name or a literal offer/category; put descriptive value props in supporting copy, not the headline.
- Websites and games must use visual assets. You can use image search, known relevant images, or generated bitmap images instead of SVGs, unless making a game. Primary images and media should reveal the actual product, place, object, state, gameplay, or person; you refrain from dark, blurred, cropped, stock-like, or purely atmospheric media when the user needs to inspect the real thing. For highly specific game assets you use custom SVG/Three.js/etc.
- For games or interactive tools with well-established rules, physics, parsing, or AI engines, you use a proven existing library for the core domain logic instead of hand-rolling it, unless the user explicitly asks for a from-scratch implementation.
- You use Three.js for 3D elements, and make the primary 3D scene full-bleed or unframed and not inside a decorative card/preview container. Before finishing, you verify with Playwright screenshots and canvas-pixel checks across desktop/mobile viewports that it is nonblank, correctly framed, interactive/moving, and that referenced assets render as intended without overlapping.
- You do not put UI cards inside other cards. Do not style page sections as floating cards. Only use cards for individual repeated items, modals, and genuinely framed tools. Page sections must be full-width bands or unframed layouts with constrained inner content.
- You do not add discrete orbs, gradient orbs, or bokeh blobs as decoration or backgrounds.
- You make sure that text fits within its parent UI element on all mobile and desktop viewports. Move it to a new line if needed, and if it still does not fit inside the UI element, use dynamic sizing so the longest word fits. Text must also not occlude preceding or subsequent content. Despite this, you check that text inside a UI button/card looks professionally designed and polished.
- Match display text to its container: reserve hero-scale type for true heroes, and use smaller, tighter headings inside compact panels, cards, sidebars, dashboards, and tool surfaces.
- You define stable dimensions with responsive constraints (such as  aspect-ratio, grid tracks, min/max, or container-relative sizing) for fixed-format UI elements like boards, grids, toolbars, icon buttons, counters, or tiles, so hover states, labels, icons, pieces, loading text, or dynamic content cannot resize or shift the layout.
- You do not scale font size with viewport width. Letter spacing must be 0, not negative.
- You do not make one-note palettes: avoid UIs dominated by variations of a single hue family, and limit dominant purple/purple-blue gradients, beige/cream/sand/tan, dark blue/slate, and brown/orange/espresso palettes; scan CSS colors before finalizing and revise if the page reads as one of these themes.
- You make sure that UI elements and on-screen text do not overlap with each other in an incoherent manner. This is extremely important as it leads to a jarring user experience.

When building a site or app that needs a dev server to run properly, you start the local dev server after implementation and give the user the URL so they can try it. If there's already a server on that port, you use another one. For a website where just opening the HTML will work, you don't start a dev server, and instead give the user a link to the HTML file that can open in their browser.
```

## Находка 2 — `## Frontend tasks` (модели `gpt-5.4`, `gpt-5.4-mini`, `codex-auto-review`). CONFIRMED

**Источник (tier 1):** тот же бинарь, смещение 248379009, `"slug": "gpt-5.4"`.
Полный текст — `extracted/codex-instructions-5.md`.

Более старая и короткая формулировка того же намерения. Дословно:

```
## Frontend tasks

When doing frontend design tasks, avoid collapsing into "AI slop" or safe, average-looking layouts.
Aim for interfaces that feel intentional, bold, and a bit surprising.
- Typography: Use expressive, purposeful fonts and avoid default stacks (Inter, Roboto, Arial, system).
- Color & Look: Choose a clear visual direction; define CSS variables; avoid purple-on-white defaults. No purple bias or dark mode bias.
- Motion: Use a few meaningful animations (page-load, staggered reveals) instead of generic micro-motions.
- Background: Don't rely on flat, single-color backgrounds; use gradients, shapes, or subtle patterns to build atmosphere.
- Ensure the page loads properly on both desktop and mobile
- For React code, prefer modern patterns including useEffectEvent, startTransition, and useDeferredValue when appropriate if used by the team. Do not add useMemo/useCallback by default unless already used; follow the repo's React Compiler guidance.
- Overall: Avoid boilerplate layouts and interchangeable UI patterns. Vary themes, type families, and visual languages across outputs.

Exception: If working within an existing website or design system, preserve the established patterns, structure, and visual language.
```

## Находка 3 — что РЕАЛЬНО получают наши Sol-воркеры. CONFIRMED (измерение)

**Источник (tier 1):** бинарь, смещение 248215530, `"slug": "gpt-5.6-sol"` →
`extracted/codex-instructions-1.md` (17 730 символов).

**Проверка, что это не мёртвый ассет, а живой промпт.** Взял реальный rollout нашего
Codex-воркера от 05.08.2026 и поискал в нём предложения из обоих шаблонов:

```
файл: ~/.codex/sessions/2026/08/05/rollout-2026-08-05T12-41-05-019fd183-37d1-7692-b0d9-3b9054f7ee02.jsonl
(originator: orchestra, cli_version 0.146.0, model_context_window 258400)

предложение из gpt-5.6-sol («Use a visualization only when…»)          → True
предложение из gpt-5.5  («You do not add discrete orbs, gradient orbs…») → False
шапка шаблона gpt-5.6-sol                                              → True
```

То есть: **шаблон Sol — это буквально то, что уходит нашему воркеру, и дизайн-правил в нём нет.**
Единственное, что есть про визуал, — вот это:

```
### Visualizations

Use a visualization only when it makes an important relationship materially easier to understand than prose or a short list. Do not add one merely because an answer has components or steps.

Good candidates include:

- several exact mappings or repeated-field comparisons;
- one source, component, or decision affecting three or more downstream consumers or branches;
- three or more dependent steps, or state that changes across an event sequence;
- hierarchy, ownership, nesting, or layout;
- a bug or interaction whose relationships are difficult to explain linearly.

Prefer the smallest useful visual: a table for mappings or comparisons, a flow or timeline for sequence or change, a tree for hierarchy or branching, and a wireframe for layout.

Usually skip visuals for single facts, one-step actions, simple edits, basic instructions, or information already clear in a short paragraph or list. Compact notation and small examples do not count as visualizations.
```

Ни слова про HTML, CSS, палитру, шрифты. Это инструкция «когда рисовать», а не «как красиво».

## Находка 4 — настоящая «красота»: дизайн-система inline-визуализаций. CONFIRMED

Codex умеет выдавать в ответе директиву `::codex-inline-vis{…}` (константа
`DIRECTIVE_PREFIX` в `codex-rs/tui/src/inline_visualization.rs:27`), а CLI оборачивает
это в самодостаточный HTML-документ и открывает в браузере. Стили этого документа —
готовая дизайн-система на 101 CSS-правило.

**Два независимых источника, и они совпали точно:**

- **tier 1 (измерение):** извлёк из байтов бинаря со смещения 249784301 → 18 390 символов CSS.
- **tier 2 (первоисточник):** `curl` файла
  `https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/inline_visualization/assets/visualize.css`
  → 18 391 байт.

**Сверка:** побайтовое сравнение — совпадение полное, первое расхождение ровно на позиции 18390,
где в бинаре начинается следующий ассет (`visualize.html`). То есть версия на диске = версия в
репозитории, промпт/стиль не протух.

Дословно — контракт токенов (комментарии авторские, включая ссылку на несуществующий у нас SKILL.md):

```css
:root {
  color-scheme: light dark;
  background-color: var(--background) !important;

  /* Agent-facing contract; keep in sync with SKILL.md. */
  --background: light-dark(rgb(255 255 255), rgb(24 24 24));
  --foreground: light-dark(rgb(26 28 31), rgb(255 255 255));
  --card: color-mix(in oklab, var(--foreground) 5%, transparent);
  --card-foreground: var(--foreground);
  --popover: light-dark(rgb(255 255 255), rgb(45 45 45));
  --popover-foreground: var(--foreground);
  --primary: light-dark(rgb(51 156 255), rgb(131 195 255));
  --primary-foreground: light-dark(rgb(255 255 255), rgb(13 13 13));
  --secondary: light-dark(rgb(255 255 255 / 96%), rgb(54 54 54 / 96%));
  --secondary-foreground: var(--foreground);
  --muted: color-mix(in srgb, var(--foreground) 10%, transparent);
  --muted-foreground: light-dark(
    rgb(26 28 31 / 49.4%),
    rgb(255 255 255 / 49.8%)
  );
  --accent: light-dark(rgb(229 242 255), rgb(13 39 63));
  --accent-foreground: var(--primary);
  --destructive: light-dark(rgb(226 85 7), rgb(255 133 73));
  --border: light-dark(rgb(26 28 31 / 8%), rgb(255 255 255 / 8.2%));
  --input: light-dark(
    rgb(26 28 31 / 11.8%),
    color-mix(in oklab, rgb(0 0 0) 10%, transparent)
  );
  --ring: light-dark(rgb(51 156 255), rgb(131 195 255 / 76%));
  --font-size-base: 14px;
  --viz-series-1: var(--primary);
  --viz-series-2: light-dark(rgb(243 136 59), rgb(245 154 86));
  --viz-series-3: light-dark(rgb(93 201 119), rgb(116 213 139));
  --viz-series-4: light-dark(rgb(235 119 177), rgb(240 143 192));
  --viz-series-5: light-dark(rgb(155 121 236), rgb(170 145 239));
  --viz-series-6: light-dark(rgb(58 185 177), rgb(90 203 194));

  /* Internal implementation variables; not part of the agent contract. */
  --font-sans: -apple-system, system-ui, "Segoe UI", sans-serif;
  --font-mono:
    ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono",
    monospace;
  --font-size-normal: max(11px, var(--font-size-base));
  --font-size-tooltip: calc(var(--font-size-base) - 1px);
  --font-size-small: max(11px, calc(var(--font-size-base) - 2px));
  --font-size-h1: calc(var(--font-size-normal) * 1.7142857143);
  --font-size-h2: calc(var(--font-size-normal) * 1.4285714286);
  --font-size-h3: calc(var(--font-size-normal) * 1.2857142857);
  --font-weight-normal: 430;
  --font-weight-medium: 500;
  --line-height-normal: calc(var(--font-size-normal) * 1.5);
  --line-height-tooltip: calc(var(--font-size-tooltip) * 1.4285714286);
  --line-height-small: calc(var(--font-size-small) + 4px);
  --radius: 12.5px;
  --radius-sm: calc(var(--radius) * 0.6);
  --radius-md: calc(var(--radius) * 0.8);
  --radius-lg: var(--radius);
  --radius-2xl: calc(var(--radius) * 1.6);
  --radius-full: 9999px;
  --shadow-sm: 0 1px 2px -1px rgb(0 0 0 / 8%);
  --checkmark-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 17 17'%3E%3Cpath d='M12.8961 3.64101C13.1297 3.41418 13.4984 3.37523 13.7779 3.56581C14.0571 3.75635 14.1554 4.11331 14.0299 4.41347L13.9615 4.53847L7.71151 13.7045C7.59411 13.8767 7.4063 13.9877 7.19881 14.0072C6.99136 14.0267 6.78564 13.9533 6.63826 13.806L2.88826 10.056L2.79842 9.9457C2.6192 9.67407 2.64927 9.30496 2.88826 9.06581C3.12738 8.82669 3.49647 8.79676 3.76815 8.97597L3.8785 9.06581L7.03084 12.2182L12.8053 3.74941L12.8961 3.64101Z'/%3E%3C/svg%3E");

  /* Legacy aliases; not part of the current agent contract. */
  --viz-bg: transparent;
  --viz-panel: var(--card);
  --viz-border: var(--border);
  --viz-text: var(--foreground);
  --viz-muted: var(--muted-foreground);
  --viz-accent: var(--primary);
  --viz-accent-text: var(--primary-foreground);
  --viz-accent-bg: var(--accent);
  --viz-font-size: var(--font-size-base);
  --viz-warning: var(--destructive);
  --color-background-primary: var(--background);
  --color-text-primary: var(--foreground);
  --color-border-secondary: var(--border);
}
```

Что ещё в этом файле, помимо токенов (полный список селекторов — 101 правило,
`extracted/upstream-visualize.css`):

- `.table` / `.table-sm` / `.table-responsive` — таблицы с `caption`, выравниванием, `text-nowrap`
- `.card`, `#widget`, `.viz-grid`, `.viz-stat`, `.viz-stat-value`, `.viz-row`, `.viz-badge`
- полный набор форм: `.btn`/`.btn-primary`/`.btn-ghost`, `.form-control`, `.form-select`,
  `.form-check`, `.form-switch`, `.form-range` (включая `::-webkit-slider-thumb` и `::-moz-range-thumb`),
  `[type="color"]`, `[type="file"]::file-selector-button`
- `.tooltip` + JS на Floating UI (`autoUpdate`/`computePosition`/`flip`/`shift`), задержка 700 мс,
  `aria-describedby`, закрытие по Escape — `extracted/upstream-visualize.html`
- иконки: `lucide` с unpkg, `[data-lucide]`
- `.sr-only`, `:focus-visible` на каждом интерактивном элементе

**Почему мы этого не видим у себя.** Весь рендерер лежит в `codex-rs/tui/` — в дереве репозитория
по маске `visualiz` нет ни одного файла вне `tui/`. А Orchestra поднимает воркера как
`codex app-server --stdio` (`app/backend_codex.py:358`), TUI не участвует. Наши Codex-воркеры
физически не могут выдать этот HTML — и в трёх живых rollout'ах его действительно нет.

**Ограничение, важное для переноса:** документ **не самодостаточен** — Floating UI и lucide
тянутся с `unpkg.com`, а CSP разрешает `cdnjs`, `jsdelivr`, `esm.sh`, `fonts.bunny.net`,
`fonts.googleapis.com`, `fonts.gstatic.com`, `unpkg.com`. Наше правило «работает офлайн»
этот документ нарушает.

## Находка 5 — отрицательный результат: агентского SKILL.md в поставке НЕТ. CONFIRMED

В самом CSS стоит комментарий `/* Agent-facing contract; keep in sync with SKILL.md. */`,
то есть на стороне OpenAI такой файл существует. Чем доказано, что нам он недоступен:

1. `grep` по всем 6 789 путям дерева `openai/codex@main` (GitHub trees API, `recursive=1`,
   `truncated: false`): по маске `visualiz` — только 10 файлов, все в `codex-rs/tui/`,
   ни одного `SKILL.md`. Все `SKILL.md` в репозитории — это `.codex/skills/*` (babysit-pr,
   code-review и т.п.) и 6 сэмплов в `codex-rs/skills/src/assets/samples/`.
2. Поиск байтов `b'codex-inline-vis'` в бинаре: 3 вхождения, все — код рендерера/парсера TUI,
   ни одного текста инструкции. `b'name: visualization'` — 0 вхождений.
3. Поиск в трёх живых rollout'ах `~/.codex/sessions/`: `codex-inline-vis` — 0,
   `--viz-series` — 0, `light-dark(` — 0. Значит скилл не приезжал и с сервера в наших сессиях.

**Вывод:** инструкция «как автору писать `::codex-inline-vis`» — серверная и нам недоступна.
Выдумывать её текст я не стал. Но для переноса она и не нужна: у нас переносится
**результат** (CSS-контракт), а не способ его вызвать.

## Находка 6 — тупик, который выглядел как ответ: плагин `openai-templates`

`~/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/` — 27 МБ, 20 скиллов
вида `artifact-template-*` (simple-dark-mode, analytics-dashboard, design-report…).
По названиям — ровно то, что искали. По содержанию — **нет**.

`README.md` плагина, дословно:

> Select or name a template and describe the content you want. The selected skill keeps its
> retained reference unchanged, delegates rendering to ChatGPT's preinstalled document,
> presentation, or spreadsheet capability, and verifies the finished artifact.

Это .docx/.pptx/.xlsx через reference-файлы Office, HTML там нет вообще.
`plugin.json`: `"license": "Proprietary"` — **копировать нельзя**, в отличие от Apache-2.0 репозитория.

## Находка 7 — побочная, но, возможно, более важная для юзера

Наш скилл существует в двух разных версиях, и воркеры получают **урезанную**:

| | глобальный `~/.claude/skills/html-artifacts/SKILL.md` | проектный `pipelines/default/prompts/skills/html-artifacts.md` |
|---|---|---|
| Размер | 12 219 байт | **2 357 байт** |
| Раздел «TEACH, don't report» | есть | нет |
| 7 файлов `references/` по категориям | есть | **нет вовсе** |
| Favicon per artifact | есть | нет |
| Anti-patterns | 9 пунктов | 5 пунктов |
| Interactive patterns (`<details>`, CSS-табы…) | есть | нет |

`pipelines/default/pipeline.yaml:24,55,71` раздаёт воркерам именно **проектную** копию.
То есть жалоба «наши артефакты одно и то же» может объясняться не Codex'ом, а тем, что
воркер видит 2 КБ вместо 12 КБ — и в этих 2 КБ жёстко зашит **один** набор цветов
(`--accent: #7c3aed`, фиолетовый), без единого совета про типографику и сетку.
Это ровно тот случай «одна мысль = один owner», про который предупреждает `CLAUDE.md`.

---

## Контр-доказательства и конфликты источников

- **Вторичные источники врут.** `WebSearch` по теме выдал утверждение: *«There's no first-party
  "inline visualization" renderer in Codex CLI itself — the terminal handles images, and HTML output
  is delegated to external viewers or hosting»*. Это **опровергнуто** первоисточником: файлы
  `codex-rs/tui/src/inline_visualization/` и запись в официальном changelog. Ни одного факта из
  этой выдачи в отчёт не взято.
- **Официальный changelog (tier 2, открыт в этой сессии):**
  v0.145.0 (21.07.2026) — *«Added secure, clickable inline visualization links in the terminal UI»*;
  v26.715 (23.07.2026) — *«Inline visualizations now render tables and visual themes more reliably»*.
  Фича новая (три недели на момент отчёта) — этим и объясняется, что вторичные источники её ещё не знают.
- **Против «просто скопируем frontend guidance»:** эти правила писались для *приложений*
  (лендинги, игры, Three.js, dev-сервер, Playwright-скриншоты), а не для одностраничного отчёта.
  Прямой копипаст притащит в наш скилл мусор про hero-страницы и дев-серверы.
- **Против «дизайн-система решит всё»:** `visualize.css` — стиль **виджета внутри чужого вьюера**
  (`html > body { padding: 5px; background: transparent }`, `#widget`), а не документа.
  Типографической шкалы для длинного текста там нет — только `--font-size-h1..h3` от базовых 14px.
- **Второго мнения нет.** Codex-ревью этого отчёта запускалось и упало на терминальном лимите
  («You've hit your usage limit… try again at Aug 8th, 2026») — дословный вывод и заменивший его
  собственный состязательный проход в `codex-review-research.md`. Самопроверка нашла **3 ошибки
  в таблице сравнения, все три в пользу моего же вывода**; они исправлены. Внешней проверки
  отчёт не проходил — при переходе в Фазу 2 прогнать после 08.08.
- **Чего я НЕ проверял:** не запускал `codex` ни разу (квота выбрана до 08.08 — ограничение задачи),
  поэтому «как выглядит отрендеренный `::codex-inline-vis` вживую» — не измерено. Всё выше — из
  байтов, файлов первоисточника и логов уже состоявшихся сессий.

---

## Сравнение: что есть у них и чего нет у нас

Колонка «у нас» — по **глобальному** 12 КБ скиллу (проектный ещё беднее).

| Пункт | Codex | Наш `html-artifacts` |
|---|---|---|
| Тема через `light-dark()` + `color-scheme` | **да**, одна переменная на оба режима | нет — дублирующий блок в `@media (prefers-color-scheme: light)` |
| Ручной оверрайд темы (`:root[data-theme]`) | **да** | **нет** |
| Токены как контракт (`--card`, `--popover`, `--muted`, `--ring`, `--destructive`…) | **да**, 25 токенов в блоке, помеченном «Agent-facing contract» (всего в `:root` — 59, остальные помечены как внутренние) | 15 токенов, без `ring`/`popover`/`input` |
| Цвета через `color-mix()` / `oklab` | **да** (`--card`, `--muted` выводятся из `--foreground`) | нет — все цвета захардкожены хексами |
| Палитра серий для графиков | **да**, `--viz-series-1..6`, подобраны и для light, и для dark | **нет вообще** |
| Типографическая шкала от одной базы | **да**, `--font-size-h1 = base × 1.714` и т.д. | нет — размеры проставляются на глаз |
| `--font-weight-normal: 430` (нецелый вес) | **да** | нет |
| Шкала радиусов от одного `--radius: 12.5px` | **да**, `sm/md/lg/2xl/full` | **нет** |
| Тени | `box-shadow` встречается 12 раз, но **9 из них — это фокус-кольца** (`inset 0 0 0 1px var(--ring)`), и лишь 2 — реальная высота (`--shadow-sm`). То есть тень у них = механизм состояния, а не украшение | упомянута один раз — в anti-patterns, где запрещена |
| Состояния `:focus-visible` на каждом контроле | **да**, через `--ring` | **не упомянуты ни разу** |
| Готовые классы форм (switch, range, checkbox, color, file) | **да**, ~40 правил | нет |
| Тултипы с позиционированием | **да** (Floating UI, 700 мс, Escape, `aria-describedby`) | нет |
| Иконки | lucide, «не рисуй SVG-иконку руками» | нет правила; SVG только для диаграмм |
| `.sr-only`, доступность | **да** | нет |
| Таблицы как отдельный компонент | **да** (`.table-sm`, `caption`, выравнивание, `nowrap`) | нет |
| Правила против «AI slop» | да (5.4: шрифты/цвет/motion/фон; 5.5: 21 правило) | **да, и наши конкретнее** (9 anti-patterns + эталоны: Stripe Press, Ciechanowski, NYT) |
| Работает офлайн | **нет** — unpkg + разрешённые CDN шрифтов | **да**, жёсткое правило |
| Системные шрифты без CDN | да (`--font-sans`), но CSP пускает Google Fonts | **да**, строже |
| `@media print` | **нет** | **да** |
| Мобильная адаптивность, viewport | не оговорена (виджет в чужом вьюере) | **да** |
| Favicon на артефакт | нет | **да** |
| «TEACH, don't report», экспорт обратно в markdown | нет | **да** |

Коротко: **у них сильнее «система» (токены, состояния, компоненты, серии графиков),
у нас сильнее «редактура» (офлайн, печать, анти-слоп с эталонами, смысловые требования к тексту).**
Пересечение почти нулевое — поэтому перенос осмыслен.

---

## Предложение к переносу (реализацию НЕ делал — жду решения)

### Можно брать целиком

`visualize.css` — **Apache-2.0** (проверено: `https://raw.githubusercontent.com/openai/codex/main/LICENSE`,
первые строки — `Apache License Version 2.0`). Условие лицензии — сохранить уведомление об авторстве.
Практически: положить исходник в `references/` с шапкой «© OpenAI, Apache-2.0, источник + дата»
и не выдавать за своё.

Что предлагаю взять:

1. **Блок токенов целиком** (Находка 4) — как альтернативную «CSS Foundation». Он строго лучше
   нашей: `light-dark()` вместо дублей, `color-mix()` вместо хексов, есть `--ring`, `--popover`,
   шкала радиусов, шкала кеглей от одной базы.
2. **`--viz-series-1..6`** — у нас дыры на графиках нет вообще, а тут готовая палитра под обе темы.
3. **`:root[data-theme="light"|"dark"]`** — ручной переключатель темы, которого нам не хватает.
4. **Правила состояний:** `:focus-visible` через `--ring` на каждом интерактивном элементе + `.sr-only`.
5. **Компонентные правила таблиц** — наши артефакты состоят из таблиц, а правил для них у нас ноль.

### Брать, но переписав под нас

6. Из `## Frontend guidance` (Находка 1) — **только правила, применимые к документу**, дословных
   пунктов там 6 из 21: карточки не вкладывать в карточки и не оформлять секции карточками;
   не использовать «orbs/gradient orbs/bokeh»; не масштабировать кегль от ширины вьюпорта и
   `letter-spacing: 0`; не делать одноцветные палитры (перечислены запрещённые темы, включая
   фиолетово-синие градиенты — **а у нас `--accent: #7c3aed` ровно такой**); текст должен влезать
   в контейнер на всех вьюпортах; кегль подбирать под контейнер, а не «геройский везде».
7. Из `## Frontend tasks` (Находка 2) — формулировка *«Vary themes, type families, and visual
   languages across outputs»*. Это прямой ответ на жалобу «наши артефакты одно и то же»:
   у нас в скилле зашит **один** акцент на все артефакты навсегда.

### Брать нельзя

- **Плагин `openai-templates`** — `"license": "Proprietary"`, плюс это Office-файлы, не HTML.
- **Floating UI / lucide с unpkg** — ломает наше правило «работает офлайн». Тултипы, если нужны,
  писать на `<details>`/`title`/своём мини-JS; иконки — инлайн-SVG.
- **`::codex-inline-vis`, `#widget`, `html > body { background: transparent }`** — привязка к их
  рантайму (виджет внутри вьюера). Нам нужен самостоятельный документ.
- **Правила про hero-страницы, лендинги, Three.js, дев-сервер, Playwright** — не про наш жанр.
- Серверный `SKILL.md` — его нет, и придумывать его текст я отказался (Находка 5).

### Форма переноса

Отдельным тикетом Фазы 2, и **в глобальный `~/.claude/skills/html-artifacts/`**, а не в проектную
копию — иначе разъедутся ещё сильнее. Отдельный вопрос к решению: не убить ли проектный
2-килобайтный дубль вовсе (Находка 7), потому что сейчас воркеры Orchestra читают именно его.

---

## Затронутые файлы (если Фаза 2 будет одобрена)

- `~/.claude/skills/html-artifacts/SKILL.md` — раздел «CSS Foundation», anti-patterns. **Глобальный,
  за пределами репозитория, правится только по явному решению.**
- `~/.claude/skills/html-artifacts/references/` — сюда лёг бы `visualize.css` с атрибуцией.
- `pipelines/default/prompts/skills/html-artifacts.md` — проектная копия; решить её судьбу.
- Риск: `pipeline.yaml:24,55,71` раздаёт скилл трём ролям; для Sol-воркеров текст скилла
  **вклеивается в системный промпт целиком** (`app/runtime_registry.py`, `read_skills_content`),
  поэтому рост скилла = рост токенов в каждой сессии Sol. Раздувать без нужды нельзя.

---

## Источники

Открыты/выполнены в этой сессии 05.08.2026.

1. Бинарь `/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex` (311 001 136 байт, `@openai/codex@0.146.0`) — 8 шаблонов `instructions_template`,
   ассеты `visualize.css`/`visualize.html`. **tier 1, измерение.**
2. `https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/inline_visualization/assets/visualize.css` — **tier 2, первоисточник.**
3. `https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/inline_visualization/assets/visualize.html` — **tier 2.**
4. `https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/terminal_visualization_instructions.rs` — **tier 2.** Полный текст:

```
- This surface is a terminal. When the formatting rules require a visual, include one in the final answer using compact ASCII diagrams, trees, timelines, or tables.
- Use tables for exact mappings or comparisons rather than collapsing known mappings into prose.
- Use trees for hierarchy or one-to-many relationships, and diagrams or timelines for sequence, change, or state transferred between records across event order.
- Use only ASCII characters in visuals.
```

5. `https://api.github.com/repos/openai/codex/git/trees/main?recursive=1` — 6 789 путей, `truncated: false`. **tier 2.**
6. `https://raw.githubusercontent.com/openai/codex/main/LICENSE` — Apache-2.0. **tier 2.**
7. `https://learn.chatgpt.com/docs/changelog` (редирект с `developers.openai.com/codex/changelog`) —
   записи v0.145.0 и v26.715. **tier 2.**
8. `~/.codex/sessions/2026/08/05/rollout-…019fd183….jsonl` — живой rollout Orchestra-воркера. **tier 1.**
9. `~/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/` — `README.md`, `plugin.json`,
   `skills/artifact-template-simple-dark-mode/SKILL.md`. **tier 1.**
10. `~/.claude/skills/html-artifacts/SKILL.md` и `pipelines/default/prompts/skills/html-artifacts.md` — база сравнения. **tier 1.**
11. `WebSearch` по inline-визуализациям Codex — **использован только как контр-пример**, факты не заимствованы.

## Выгруженные артефакты

```
docs/tasks/119/extracted/
├── codex-instructions-1.md … -8.md   # 8 системных промптов моделей Codex, дословно
│     1=gpt-5.6-sol  2=gpt-5.6-terra  3=gpt-5.6-luna  4=gpt-5.5
│     5=gpt-5.4      6=gpt-5.4-mini   7=gpt-5.2       8=codex-auto-review
├── codex-visualization-assets.txt    # ассеты вьюера, извлечённые из байтов бинаря
├── upstream-visualize.css            # то же из репозитория (сверено побайтово)
├── upstream-visualize.html
├── upstream-terminal_visualization_instructions.rs
└── section-*.txt                     # дословные куски, вставленные в этот отчёт
```
