# V-1091 — факты о ai-design-skills / landing-page-design

Дата исследования: 2026-10-26 UTC. Класс B, только чтение публичных источников и создание исследовательских артефактов. Ни лендинг, ни установка навыка, ни изменение правил не выполнялись. Вердикта о применении нет; сравнение с native html-artifacts остаётся root.

## 1. Зафиксированный источник и доказательства

Репозиторий: [elayadesign/ai-design-skills](https://github.com/elayadesign/ai-design-skills). GitHub `commits/HEAD` при первом обращении вернул **`a2735a3eaf092eaaffb6dc17df25de33ef3bd048`**, дата коммита `2026-10-26T00:14:04Z`. Все последующие GitHub-файлы загружены по этому SHA, а не по `main`. [Коммит](https://github.com/elayadesign/ai-design-skills/commit/a2735a3eaf092eaaffb6dc17df25de33ef3bd048), [ответ HEAD](evidence/github-head.json), [полное рекурсивное дерево](evidence/github-tree.json).

Короткие обозначения ниже всегда означают этот pinned commit. `L:150–198` — строки оригинального `skills/landing-page-design/SKILL.md`, не строки отчёта. Для офлайн-проверки оригиналы сохранены без изменений, нумерованный вывод — в [inspection.stdout.txt](evidence/inspection.stdout.txt).

| ID | Публичный источник | Локальная копия | Размер / строки | Git blob SHA-1 |
|---|---|---|---|---|
| R | [README](https://github.com/elayadesign/ai-design-skills/blob/a2735a3eaf092eaaffb6dc17df25de33ef3bd048/README.md) | [README.md](sources/github/README.md) | 3139 B / 85 | `99387ba735fabf044220ca8799e2b7aef4b82b41` |
| L | [landing-page-design/SKILL.md](https://github.com/elayadesign/ai-design-skills/blob/a2735a3eaf092eaaffb6dc17df25de33ef3bd048/skills/landing-page-design/SKILL.md) | [landing-page-design.SKILL.md](sources/github/landing-page-design.SKILL.md) | 18801 B / 431 | `39caa206ac2b179b110562db65e3e3c79a759fb5` |
| LIC | [LICENSE](https://github.com/elayadesign/ai-design-skills/blob/a2735a3eaf092eaaffb6dc17df25de33ef3bd048/LICENSE) | [LICENSE](sources/github/LICENSE) | 1062 B / 21 | `9ff21c8c5b2e713c357d3e15e641172a211eac21` |
| M | [design-to-motion/SKILL.md](https://github.com/elayadesign/ai-design-skills/blob/a2735a3eaf092eaaffb6dc17df25de33ef3bd048/skills/design-to-motion/SKILL.md) | [design-to-motion.SKILL.md](sources/github/design-to-motion.SKILL.md) | 39109 B / 513 | `b7326add823b585689f065a83e7b6b3aadc252fa` |
| O1 | [OpenAI: Build skills](https://learn.chatgpt.com/docs/build-skills) | [build-skills.md](sources/openai/build-skills.md) | 11035 B | Live snapshot, SHA-256 в manifest |
| O2 | [OpenAI: Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | [agents-md.md](sources/openai/agents-md.md) | 9149 B | Live snapshot, SHA-256 в manifest |

Байты и Git blob SHA-1 всех четырёх GitHub-файлов вычислены локально и совпали с pinned GitHub tree. SHA-256 всех шести источников и URL — в [source-manifest.json](evidence/source-manifest.json). GitHub пометил подпись коммита `verified: false`, `reason: unknown_key`; совпадение blob-хешей подтверждает соответствие полученному дереву, а не удостоверяет личность автора.

O1/O2 прочитаны с официального домена OpenAI. Старые адреса `developers.openai.com/codex/skills/` и `developers.openai.com/codex/guides/agents-md/` при проверке перенаправили на указанные страницы `learn.chatgpt.com`. Сохранены Markdown-представления и HTTP headers. Это датированный снимок документации, без закреплённой версии установленного Codex.

## 2. Полнота landing и граф его ресурсов

Прочитаны **все L:1–431**: frontmatter, Scope, A1–A8, B1–B11, Output format, Quick checklist и Credits с полным встроенным MIT notice. Рекурсивный tree имеет `truncated: false`. В `skills/landing-page-design/` находится ровно один файл `SKILL.md`:

- Bundled `references/`: **0**.
- Bundled `assets/`: **0**.
- Bundled `scripts/`, шаблоны кода, `agents/openai.yaml`: **0**.
- В репозитории нет `package.json`, lockfile сборки, eval harness или тестов лендинга. Это устанавливается по полному tree, а не по отсутствию найденных слов.

Внешние связи L:

| Источник | Связь | Когда используется | Что установлено / граница исследования |
|---|---|---|---|
| L:18 | `redesign-existing-projects`, ссылка `elayadesign/redesign-skill` | Условная ветка обновления существующего сайта | Текст предписывает использовать companion и утверждает, что тот делегирует конкретные значения обратно L. Companion не включён в этот repo, не закреплён SHA и не нужен для пути нового лендинга; его содержимое не исследовано |
| L:40–43 | Логотипы, отзывы, числа, case studies, screenshots, demo video, product GIFs, гарантии | Intake входных доказательств и медиа | Это запрашиваемые входы пользователя, не поставляемые assets и не команда скачать/сгенерировать медиа |
| L:154, 263 | Шрифты Geist, Manrope, Geist Mono, Poppins; иконки Phosphor, Solar, Iconamoon | Выбор типографики и иконок | Имена библиотек/гарнитур, без файлов, URL загрузки, версий или команд установки |
| L:291, 351 | `IntersectionObserver`; альтернативы Framer Motion / rAF | Реализация scroll motion | Browser API либо альтернативная библиотека; внешняя библиотека не обязательна при выборе browser API |
| L:403–431 | `Leonxlnx/taste-skill`, профиль Leon Lin | Credits и встроенная лицензия | Attribution/provenance, не указание читать или запускать upstream. Notice сохранён; upstream HEAD не исследован и не считается pinned dependency |
| R:14,79; M:18 | Соседний `design-to-motion` | Объяснение возможного пути получения MP4/GIF | В L нет вызова этого соседа. M, напротив, называет L companion для landing context; экспорт не является обязательной частью L |

README называет папки self-contained (R:5). Для L это верно в отношении поставляемого текста; реальные продуктовые доказательства, гарнитуры, иконки и среда выполнения в папке отсутствуют. Наличие реального API/инструмента у агента не следует из упоминания имени в Markdown.

## 3. Лицензии и предел утверждения «no attribution»

Обозначения для таблиц:

- **E** = LIC:1–21, MIT, `Copyright (c) 2026 Elaya`: разрешены использование, копирование, модификация, распространение и продажа с сохранением copyright и permission notice в копиях либо существенных частях; стандартное отсутствие гарантии.
- **T** = L:401–431: автор указывает адаптацию идей/разделов taste-skill; встроенный MIT notice `Copyright (c) 2026 Leonxlnx`, в частности обязанность сохранения notice в L:420–421. Для полного L присутствуют **E+T**; точное поблочное авторство отдельных предложений не размечено.
- **X** = лицензии внешних медиа, гарнитур, иконок, зависимостей и данных этим repo не установлены; они не становятся MIT только от использования с навыком.

R:85 содержит маркетинговую формулировку `No attribution needed.` LIC:12–13 и L:420–421 отдельно содержат условие сохранения notices. Это разные утверждения: интерфейс с результатом не обязан по этому тексту показывать credit, но при распространении копий/существенных частей самого материала условие MIT остаётся в тексте лицензии. Это фиксация буквальных условий источника, не юридическое заключение о конкретном производном продукте.

M:505–513 называет Elaya/MIT и адаптации из `emilkowalski/skills`, `Owl-Listener/designer-skills`, `dylantarre/animation-principles` с заявлением MIT. Их upstream-содержимое и лицензии независимо не проверены: M рассмотрен только для разграничения demo/export. Эти ссылки не требуются L.

## 4. Таблица механизмов L

Это нормативные инструкции модели, а не исполняемые проверки. «Behavior» описывает, что текст требует от агента, не замер его фактического исполнения. Для всех строк E+T означает лицензионное покрытие полного файла без приписывания каждого предложения конкретному автору.

| Mechanism | Source:line | Concrete trigger | Resulting behavior | Dependencies | License | Limitations |
|---|---|---|---|---|---|---|
| Широкий авто-триггер | L:1–18 | Build/edit/style/review/copy любого web UI, включая dashboard, section, prototype | Консультировать файл до выбора sections, CTAs, fonts, spacing, radius, icons, transitions; explicit user выше правила, правило выше framework default | Host должен обнаружить/подключить текст | E+T | Scope шире названия landing; нет enforcement-кода, tool allowlist или теста маршрутизации |
| Одно намерение | L:8–12, 29–31 | Начало landing task | Одно предложение, одна аудитория, одно primary action; пройти A до B | Продуктовая цель | E+T | Не измеряет конверсию и не реализует аналитику |
| Intake + fallback | L:24–50 | Недостающие сведения о цели, ICP, objections, traffic, proof, brand/mobile | Один пакет вопросов; если пользователь не знает — однострочное допущение и продолжение | Ответы/допущения; входные assets | E+T; X для inputs | Нет обязательной проверки достоверности допущений, отзывов, гарантий |
| Структура страницы | L:52–72 | Новый landing | Hero с 5 элементами; problem→solution; 3–5 benefits; 3 steps; proof; FAQ 6–12; risk reversal; финальный CTA как сверху; tagline | Copy и визуал продукта | E+T; X для media | Фиксированный набор; правила сокращения для minimal layout отдельно не описаны |
| Выбор layout | L:74–83 | Определение структуры | Выбрать A classic screenshot / B обучающий story / C high-intent minimal / D comparison-search и назвать причину | Audience/traffic из intake | E+T | Нет готовых шаблонов, breakpoints или decision score |
| Конверсионное сообщение | L:85–99 | Ad traffic, написание CTA и аргументов | Зеркалить ad promise; один CTA; benefit-first; конкретика; хотя бы один risk reversal; FAQ раньше при friction; proof около claim | Реальные promise, proof, условия offer | E+T | Числовая специфика — правило текста, не доказанный lift |
| Copy patterns | L:101–114 | Headlines, subheadline, buttons, benefits | 3 headline formulas; subheadline 1–2 предложения; CTA verb+получаемое; запрет Learn more/Submit; benefit bold + detail | Контекст продукта | E+T | Английские образцы; локализация и фактчекинг не определены |
| Build order / iteration | L:116–127, 355–367 | После текстового плана / следующий проход | Hero→Benefits→How it works→Proof→FAQ→Final CTA; не перестраивать целиком каждый раз | Редактируемый проект, host tools | E+T | Нет файловых путей, scaffold, build/test/deploy команд или rollback |
| SEO/AEO | L:129–142 | Campaign/time-bound либо evergreen/search-intent | В первом случае noindex/«non indexed path»; во втором title/meta, internal links, FAQ Q&A; schema если уместно | Доступ к head/routes/другим страницам сайта | E+T | Сам путь не задаёт HTTP/robots/meta политику; реализация, верификация индексации и schema не даны |
| Шрифтовая политика | L:150–168 | Любой выбор fonts/weights/copy wrapping | Allowed 4 families; ban 5 families; одна гарнитура; mono только функционально; без italic/900; ban hyphen; balance/pretty | Установленные/доступные fonts; CSS | E+T; X fonts | Нет fallback stack, font delivery, покрытия языков или проверки переносов |
| Type tokens | L:170–197 | Установка/аудит font-size | 12→128px по таблице; off-scale округлять вниз вместе с line-height; buttons 16/14px semibold | Tailwind default scale как словарь | E+T | Версия Tailwind не pinned; нет mapping на breakpoints; line-height wording неоднозначен |
| Spacing tokens | L:199–219 | Любые расстояния | Только 0,2,4,8,12,16,24,32,40,48,64,80,96px; main button padding 8×12px | CSS / token mapping | E+T | Не поставляется token config; исключений для layout не дано |
| Радиусы | L:221–233 | Nested shape с gap<32px | Tailwind radius; inner=outer−gap только при результате>2; иначе square/unchanged | Размеры контейнера/вложенного элемента | E+T | Формула может дать не-scale radius; приоритет между двумя правилами не расписан |
| Фон / border | L:235–244 | Карточки и dark backgrounds | Border целиком либо отсутствует; flat background; dark только 6 hex | CSS | E+T | Light palette и контрастные пары не определены |
| Hero treatment | L:246–259 | Hero light/dark | Text gradient white→gray или black→gray; heading/subheading max680px; осмысленные line breaks | CSS / доступный viewport | E+T | Нет нижней границы width, мобильного размера, проверки contrast |
| Иконки | L:261–265 | Выбор icon set | Phosphor/Solar/Iconamoon; ban Material Icons/Symbols | Внешние icon assets либо package | E+T; X icons | Версий, установки, a11y labels и размеров нет |
| Базовая motion-политика | L:267–275 | Любая анимация UI | Custom bezier(.22,1,.36,1), layout/position 500ms; hover color/opacity 300ms, ≥200; только transform/opacity; reduce→opacity | CSS; reduced-motion preference | E+T | Hover color упомянут при ограничении animate-only; нет исполняемой политики |
| Navigation | L:277–285 | Навигация / menu opening | Плавающий compact centered glass bar; animated toggle; mobile full-height blurred panel; links +24px fade, stagger60ms cap400ms | CSS и menu state | E+T | Не задано focus trapping, Escape, aria-expanded, body-scroll handling |
| Scroll sections | L:287–291 | Section впервые входит в viewport | +32px→0, opacity0→1, 600–800ms, один раз; IO либо whileInView; запрет unthrottled scroll | Browser IO либо Framer Motion | E+T; X для lib | Threshold/rootMargin и no-JS fallback не даны |
| Реализм sample content | L:295–305 | Заполнение demo-copy, отзывов, brands, metrics | Контекстные полные имена/бренды, уникальные faces, неровные числа и даты; sentence case; ban filler; спокойные specific messages | Продуктовые сведения/медиа либо выдуманные образцы | E+T; X images | Нигде не требует маркировать придуманные отзывы/числа как fictional или подтверждать их |
| Interactive states | L:307–318 | Любой interactive element | Hover/active/focus/loading/empty/error; active scale .98 или +1px; visible ring; layout skeleton; actionable empty; inline error; no dead links/current nav | UI state/data | E+T | Требования текстовые; нет ARIA/state-machine, тестов keyboard или реального backend |
| Ship checklist | L:320–333 | Завершение страницы | Legal links, 404, validation email/required, skip link, conditional cookie consent, favicon, title/meta/OG, alt, semantic HTML, way back | Routes, legal content, image assets | E+T; X legal/media | Нет legal текста, jurisdiction detection, server validation или publish шагов |
| Обязательная tagline | L:335–351 | Каждый landing | Отдельный benefit block ≥2 lines, 36–60px, capped width; words25–35%→full по trigger line; IO-per-word либо rAF-throttled scroll | Разбиение текста, browser JS | E+T | Позиция относительно hero и IO-vs-rAF расходятся с другими формулировками; contrast не проверяется |
| План до кода / финальный checklist | L:355–397 | Генерация с нуля / сдача | Сначала 7 результатов (outline, hero, benefits, steps, FAQ, SEO, layout), затем код; сверить checklist | Host и агент | E+T | Нет автоматического pass/fail, фиксированных screenshots, budgets или пользовательского acceptance |

## 5. Существенные правила по областям

### Контент, структура и композиция

L:8–142 и L:295–305: одно конверсионное действие; outcome+audience в headline; поясняющий subheadline; CTA с глаголом и предметом результата; proof уже в hero и возле утверждения; 3–5 outcome benefits, три шага, 6–12 FAQ; как минимум один способ снизить риск. High-friction FAQ переносится выше. Ad message согласуется с рекламой. Layout выбирается из A–D по knowledge/intent. Sample content пишется в голосе продукта, с contextual names/brands и varied dates; одинаковые лица для разных людей запрещены. Метрики должны выглядеть неокруглёнными. Headings/buttons sentence case; confirmations/errors конкретные, без восклицаний и cute interjections. Запрещённые filler expressions перечислены в L:303, а не сведены к универсальному детектору «AI copy».

Композиция L:219–259,279,335–351: padding main buttons 8px vertical/12px horizontal; nested radius; full border/flat background; hero title+subtitle max680px; floating glass nav; обязательный отдельный large-type tagline. Dark palette: `#000000`, `#181818`, `#1F1F1F`, `#272727`, `#313131`, `#131209`. Единственный разрешённый gradient — hero heading text: dark `#FFFFFF→#9B9B9B`, light `#000000→#666666`.

### Типографика и tokens

L:150–219: разрешены Geist, Manrope, Geist Mono, Poppins; запрещены Inter, Roboto, Arial, Open Sans, Helvetica. Одна основная гарнитура, mono дополнительно только для code/data/numerics; pairing — при явном запросе. Без italic, без 900/black; cap semibold/bold. ASCII `-` запрещён в body/headings/labels. Одинокое последнее слово запрещено, предложены `text-wrap: balance` / `pretty`.

| Type class | px / line-height по L:176–190 |
|---|---|
| xs, sm, base, lg, xl | 12/16, 14/20, 16/24, 18/28, 20/28 |
| 2xl, 3xl, 4xl | 24/32, 30/36, 36/40 |
| 5xl, 6xl, 7xl, 8xl, 9xl | 48/1, 60/1, 72/1, 96/1, 128/1; `1` — коэффициент |

Off-scale значения заменяются ближайшим меньшим шагом вместе с его line-height. Основные кнопки base/semibold, header buttons sm/semibold. Spacing tokens L:203–217: `Spacing-0=0`, `25=2`, `50=4`, `75=8`, `100=12`, `200=16`, `300=24`, `400=32`, `500=40`, `600=48`, `700=64`, `800=80`, `900=96px`. Отдельного config-файла нет.

### Адаптив

Явное покрытие L:48,141,257–259,283–285,344–345: спросить mobile priority; не ломать readability; max680px hero; осмысленные переносы; full-height mobile menu; tagline4xl–6xl в зависимости от числа строк. **Отсутствуют** breakpoints, fluid/clamp scale, правила column collapse/order, min-width, safe-area, touch target minimum, горизонтальный overflow test, viewport test matrix. Это границы полноты текста, не результат проверки построенной страницы.

### Motion

L:267–291: основная кривая `cubic-bezier(0.22,1,0.36,1)`; 500ms position/layout, hover300ms с floor200ms; transform/opacity; reduce оставляет plain opacity. Nav toggle морфит состояние, links rise24px, interval60ms, cap400ms. Section reveal rise32px и opacity, 600–800ms, один раз. IO / `whileInView`; unthrottled `scroll` запрещён. B11: слова tagline активируются отдельно в reading order, начальный text tone25–35%, final100%; допускается per-word IO либо единственный rAF-throttled listener. Автоматического motion test нет.

### Accessibility и состояния

L:275,309–333: reduced motion; заметный focus ring; skip-to-content; alt для meaningful images; `<nav>`, `<main>`, `<article>`, `<aside>`, `<section>`; current nav; работающие/disabled links; inline errors и client validation; way back. Полный state set включает hover, active, focus, loading, empty, error; skeleton повторяет layout, spinner запрещён. **Не описаны** числовой contrast threshold/WCAG level, ARIA для иконок и меню, keyboard interaction model/focus return/trap/Escape, screen-reader reading of word-split text, zoom/reflow tests, `aria-live` ошибок, проверка контраста muted tagline. Наличие списка требований не доказывает соответствие accessibility стандарту.

### Concrete sample patterns из источника

Это фрагменты и численные примеры правил, не созданный для пользователя landing и не утверждения о реальном продукте.

| Паттерн / пример | Source | Что конкретно задаёт |
|---|---|---|
| `{Outcome} without {pain}`; `The {category} for {audience}`; `Ship {result} in {time}` | L:103–106 | Три разрешённых образца headline |
| `Save time and streamline` → `Cut your weekly reporting from 4 hours to 15 minutes` | L:93–95 | Авторский пример замены расплывчатого benefit на конкретный; 4h/15min — sample, не измерение |
| `Start free trial`, `Book a demo`, `Get the checklist` | L:110 | CTA verb+получаемое; рядом прямой запрет `Learn more` / `Submit` |
| `Faster iteration` — `generate three layout variants in one click` | L:112 | Bold benefit + пояснение; source не предоставляет generator трёх вариантов |
| `Invoice sent to Dana`; `Upload failed. The file is over 20 MB.` | L:305 | Calm specific success / actionable error; имена и20MB — sample copy |
| `text-wrap: balance`; `text-wrap: pretty` | L:168 | Механизм борьбы с одиночным последним словом; ширинный тест не предоставлен |
| Outer `rounded-2xl`16px − gap8px = inner8px `rounded-lg` | L:225–233 | Прямой source example nested radius; условия gap<32 и result>2 |
| `ease-[cubic-bezier(0.22,1,0.36,1)]`, `duration-500` | L:271 | Буквальная Tailwind-style запись base curve/duration |
| Size22px → `text-xl`20px с line-height28px | L:172–190 | Вычисленный здесь пример применения правила snap-down по source table, не готовый пример автора |

## 6. Полная карта действий и внешних условий

Статусы: **explicit** — прямо написано; **implied** — необходимо для требуемого результата, но инструмент/команда не задан; **conditional** — только при указанном входе; **absent** — в полном L нет такого действия. Ни одна команда из R/L/M в этом исследовании не исполнялась.

| Тип | Source / status | Trigger → действие / эффект | Network / install / cost / ограничение |
|---|---|---|---|
| Read инструкции | L:1–18, explicit | Любой охваченный UI-task → прочитать/применить L | Локальное чтение после доставки; токены зависят от host; нет model endpoint |
| Read пользователя | L:24–50, explicit | Недостающие цели/ICP/assets/constraints → один batch вопросов; fallback assumption | Может потребовать ответа/входных files; нет API для извлечения product data |
| Read существующего проекта | L:127,174,192, implied | Edit/audit/iteration → определить текущие sizes/layout, править по секциям | Пути и read tools не назначены |
| Read companion | L:18, conditional | Upgrade existing site → использовать `redesign-existing-projects` | Отдельный repo; версия, доставка, доступность не заданы; не скачивался |
| Read credits | L:403, provenance | Ссылка на taste-skill/профиль → объяснение происхождения | Не runtime fetch-инструкция; внешнего чтения для L не требует |
| Write план и copy | L:355–367, explicit | Before code → 7 текстовых артефактов в указанном порядке | Нет путей сохранения и model choice |
| Write приложение | L:116–127,150–351, implied | Build → HTML/CSS/JS/components/tokens/copy со всеми правилами | Framework, entrypoint, файловая структура и permissions не определены |
| Write сопутствующие страницы | L:133,324–333, explicit outcomes | Ship → title/meta/OG, favicon, legal links, branded404, validation, navigation/skip/alt | Может расширять набор маршрутов/ссылок; никаких publish/delete/migration команд |
| Runtime local behavior | L:267–351, explicit | Hover/open/viewport/validation/loading/error → визуальные состояния и reveals | Browser CSS/JS; IO нативный; motion library альтернативна |
| Runtime network | L:57–59,318,330, absent protocol | CTAs, изображения, forms, links/OG нужны как результат | Endpoint для form, аналитика, backend, font/icon CDN и загрузки не указаны. Не доказано ни обязательное сетевое обращение, ни offline delivery |
| Install из L | Весь L:1–431, absent | Нет shell-команд, package install, downloads, MCP/server bootstrap | Нет package manager, lock, version pins; Tailwind/Framer упомянуты, не установлены |
| Install из README: Claude | R:24–33, explicit sample | `mkdir .claude/skills`; clone repo в `/tmp/ai-design-skills`; copy выбранной папки | GitHub network, локальные writes; clone без SHA; **пример не запускался** |
| Install из README: Cursor | R:36–45, explicit sample | Создать `.cursor/rules`; curl raw `main` в markdown rule либо paste Settings | GitHub raw network; mutable branch; в L отдельные resources сейчас отсутствуют |
| Install из README: Codex/others | R:48–64, explicit sample | Copy SKILL в `AGENTS.md` / `.windsurfrules` / `.clinerules` / prompt; Claude.ai upload | Write в project rules либо upload к host; native skill discovery в этом примере не описан; не выполнено |
| Customize из README | R:69–71, explicit sample | Fork repo, изменить design values | Optional fork — внешняя запись; не обязательный build-step и не выполнен |
| Model selection/cost | Весь L и R, absent configuration | Агент пишет план/copy/code | Нет API endpoint, SDK, ключа, обязательной модели, image/video generation, тарифа, бюджета или credit fallback. Расход обычного coding host возможен, сумма неизвестна |
| Validation / recovery | L:127,371–397, explicit checklist | Итерация section-by-section; ручной список на сдаче | Нет test runner, browser runner, performance/visual budget, retry loop, rollback или restore procedure |
| Destructive / external writes | Весь L и R, absent build instruction | Нет deploy, git push/commit, deletes, production DB ops или service restart | README fork/customization — отдельный добровольный пример; не полномочие на deployment |

Исследование само выполнило только публичные GET GitHub/docs и локальные записи в эту task-папку. GitHub REST чтение метаданных — внешний API в обычном HTTP-смысле; **model/image/video API не вызывались**. Публичные GET не подменяются утверждением «вообще не было API».

## 7. Воспроизводимость без внешних API

| Уровень | Что следует из источников | Что не установлено |
|---|---|---|
| Повторить чтение и факт-аудит | Сохранены pinned bytes, дерево, SHA, нумерованные outputs; `node verify-evidence.mjs` работает офлайн | Доверие к первоначальному HTTPS/GitHub ответу; unknown_key подписи не исправлен |
| Применить правила L без model/image/video API | L — текст, собственных вызовов нет; готовые локальные fonts/icons/media и browser IO позволяют реализацию без отдельного внешнего сервиса | Нужен исполняющий кодовый агент либо человек; качество, token cost и битовая идентичность результата не определены |
| Запустить готовый landing полностью офлайн | Источник не требует CDN, remote fonts, remote forms либо analytics | Не поставлены app, fonts/icons/media, build pipeline; полностью автономный build/run **не продемонстрирован** |
| Повторить тот же дизайн «один в один» | Указаны некоторые concrete values и порядок секций | Нет seed, model pin, полного input brief, фиксированного output, screenshots/evals; поведение модели недетерминировано |
| Получить MP4/GIF по одному L | Такого шага L не содержит | Нельзя приписать export соседнего M самому L |
| Сосед M с Figma input | M:74–86,132 прямо требует authenticated REST для tree/render/layers/fills | Без внешнего Figma API этот exact path не воспроизводится |
| Сосед M с локальной картинкой | M:82 разрешает flat image input; последующие HTML/capture/encode могут выполняться локально при готовых инструментах | Из картинки не всегда извлекаются отдельные слои; source требует назвать предел fidelity; зависимостей/готового runner нет |

Это анализ достаточности описанных зависимостей, не эксперимент построения. Никакой empirical performance, conversion uplift, pixel fidelity или accessibility score в этой задаче не получен.

## 8. Design-to-motion: только объяснение demo/export

В task-тексте упомянуто пересланное видео, но сам файл/URL видео/кадры в hub copy не предоставлены. README также не содержит embedded video/demo artifact. Поэтому нельзя установить, какая версия навыка, модель, входные layers, ручные исправления или montage использованы в пересланном видео.

Для разграничения возможных механизмов прочитаны M:1–139,172–193,298–439,441–465,505–513 плюс headings/URL inventory. **M:140–171,194–297,467–504 целиком не исследованы**; claims об их детальной choreography не делаются. Полный pinned файл сохранён как источник для root, не как указание исполнять его.

| Механизм M | Source:line | Concrete trigger → behavior | Зависимости / лицензия / ограничения |
|---|---|---|---|
| Showcase против website | M:20–52 | Отдельный design без сайта → whole frame empty→intro→stories→dissolve/repeat, page+MP4+2GIF; внутри website → только подходящие visual sections, one-time intro, stories без dissolve, exports по запросу | Browser/code host; E, upstream MIT заявлены M:505–513; website использует live HTML text, showcase exported text |
| Figma ingestion | M:74–86,132 | Figma node → REST nodes geometry, 2x reference PNG, каждый moving layer3x в batches20–25, raw image fills | PAT из secure store; Figma/CDN network и retry/check PNG; **ничего из этого не вызывалось** |
| Flat source fallback | M:82 | Только screenshot → rebuild isolatable parts, назвать неотделимые до анимации | Локальная картинка; идеальная layer separation не обещается |
| Background/fidelity | M:126–137,184–190 | Photo/texture за UI → сохранить точно; still2x сравнить | PSNR goals35dB overall/30dB per container, background45dB; это thresholds, не результаты demo |
| Детерминированная запись | M:172–182,354–393 | Запрос showcase export → self-contained HTML, still/loop/capture, controllable JS clock, fake browser clock, frame PNG + loopTime | Snippet использует `page.clock`, `page.goto`, screenshots; совместимый browser automation runner должен быть предоставлен; package/install/version не указаны |
| Проверки frames | M:340–350 | Перед encoding → overflow по shape mask, seam, empty beat, rest, contact sheet | Image comparisons; не заменяются заявлением «pixel exact»; проверок на demo-файле не было |
| Encode outputs | M:395–417 | После frame checks → x.mp4 H264/yuv420p60fps CRF14–15 ≤1920×1200; GIF960w15–20fps; GIF800×50020fps (12 если heavy) | FFmpeg/libx264/palette filters локально; commands есть, установок нет; ни upload в X, ни model video generation не предписаны |
| Motion/accessibility | M:315–338 | Showcase timing → иные curves/durations; reduce→still | M допускает filter/clip-path, L только transform/opacity; эти rules нельзя объявить одним идентичным контрактом |

Числа длительности цикла, FPS, размеров GIF и PSNR — параметры/цели внутри инструкции, не эмпирическая оценка популярности или качества. Стоимость Figma-плана, лицензии исходных дизайнов/фото, доступность tooling и compute recording не установлены. Действий покупки кредитов или API-моделей в исследованном export-пути нет.

## 9. Codex: официальный механизм и пример README

Официальный источник [O1](https://learn.chatgpt.com/docs/build-skills), локальные строки:

| Факт | O1:line |
|---|---|
| Standalone skills поддерживаются в desktop app, Codex CLI и IDE; manifest содержит name/description | 18–20,48 |
| Сначала metadata/path; полный SKILL загружается при выборе; явный вызов `$`/`/skills`, также matching по description | 33–46,93–103 |
| Repo discovery: `.agents/skills` от CWD до repo root; user: `$HOME/.agents/skills`; admin: `/etc/codex/skills`; system: bundled | 136–149 |
| Поддерживаются symlinked folders; одинаковые name не сливаются | 138–149 |
| `$skill-installer` может скачивать curated/другие repos; установка не обязательна для чтения этого отчёта | 166–176 |
| `agents/openai.yaml` необязателен; implicit matching можно отключить, explicit остаётся | 193–218 |

В R:49–58 вместо native skill folder указан copy в `AGENTS.md`. По [O2](https://learn.chatgpt.com/docs/agent-configuration/agents-md), строки9–15, AGENTS входит в цепочку инструкций до работы; default combined cap32KiB. Следовательно, README описывает способ подключения постоянных project rules, а O1 — выбор task-specific навыка. Отдельной установки в этой задаче не было.

Локальный **проектный** предел из AGENTS.md — строго `<16KiB`, независимо от default Codex. Текущий файл: **16356 B**, до максимально разрешённых16383 остаётся **27 B**. L: **18801 B**, уже сам по себе больше16KiB; простая конкатенация дала бы **35157 B** без separator, также больше32768. Это арифметика по snapshot, не предложение менять cap. Root AGENTS и зависимости не изменены. Этот раздел не проверяет старые инструкции и не дублирует V-1090.

## 10. Проверяемые ограничения и неоднозначности L

1. **Tagline placement:** A2 L:72 допускает typically right after hero, а B11 L:337 требует отдельный момент further down и не directly under hero. Однозначного расстояния или разрешения конфликта нет.
2. **Properties:** L:271 допускает hover color shifts, L:273 говорит animate only transform/opacity. Не определено, должен ли color изменяться мгновенно или допускается color transition как исключение.
3. **IO/rAF:** L:351 явно разрешает rAF-throttled scroll для words, а checklist L:390 говорит reveals use IntersectionObserver. Запрет unthrottled scroll соблюдён в обоих; универсальность IO-checklist сформулирована строже body.
4. **Typography:** L:174 округляет вниз size+paired line-height, L:192 запрещает независимые custom line heights и допускает adjustment «within» matched step. Границы adjustment не численные; tracking table отсутствует.
5. **Radius:** L:223 требует Tailwind radius values, L:225–231 даёт арифметику. Для результата вне scale нет правила snap или приоритета. Gap строго<32, result строго>2; ровно32/2 не входят в формулу.
6. **SEO:** L:131 предлагает noindex *или* non-indexed path, не определяя, чем обеспечена неиндексация пути. Внешние поисковые системы и index verification не рассматриваются.
7. **Demo facts:** A1 запрашивает proof, B8 требует правдоподобия и даже вымышленных brand names/неокруглённых metrics. Отдельного требования factual provenance/fictional label нет. Это важная разница между «похоже на реальный продукт» и доказанным утверждением.
8. **Варианты страницы:** A3 разрешает minimal conversion layout, но A2/B11 сохраняют обязательные блоки; отдельного сокращённого checklist нет.
9. **Enforcement:** frontmatter употребляет broad always/ANY, Part B — non-negotiable. Кроме explicit user override (L:16), это текстовая приоритетность. Никакой программной блокировки нарушений в repo нет.
10. **Существующие callers/данные:** L применяется даже к editing/audit dashboard и snap размеров вниз может изменить уже существующий UI; миграции старых tokens/data, compatibility gates, restore точки и rollback не описаны. В этой задаче никаких callers/данных не меняли.

## 11. Bookmarks, маркетинг и измерения

В R:1–85, L:1–431 и прочитанном inventory M **не приведено число bookmarks** или воспроизводимый benchmark повышения conversion/design quality. Формулировка high converting в L:3 — обещание назначения; README builds/pixel exact — описание заявленного workflow. Из этих формулировок не следуют measured uplift, pass rate или соответствие видео выходу чистого prompt.

Если в пересланном посте/видео было число сохранений, оно не воспроизведено: первичный пост/видео и timestamp метрики не предоставлены. GitHub stars/forks не запрашивались как замена bookmarks. Ни просмотры, ни stars, ни bookmarks сами по себе не измеряют качество лендингов. Проверяемые числа в этом исследовании — байты, строки, SHA, наличие файлов/правил; параметры motion/PSNR остаются нормативными targets источника.

## 12. Короткая таблица для последующего сравнения root

Native html-artifacts SKILL/root отсутствует в hub copy и **не прочитан**. Колонка для него намеренно не заполнена фактами. Машинно читаемая версия: [comparison.tsv](comparison.tsv).

| Ось | landing-page-design на pinned HEAD | Source | Native html-artifacts |
|---|---|---|---|
| Packaging | Один SKILL, 18801B/431line; refs/assets/scripts отсутствуют | L; tree | Не исследован |
| Activation | Любой web UI, включая editing/review/dashboard | L:3,16 | Не исследован |
| Planning | Intake→7 текстовых outputs→постепенный build | L:24–50,355–367 | Не исследован |
| Content | CTA/proof/FAQ/risk; realism без provenance gate | L:52–114,295–305 | Не исследован |
| Design constraints | Font allow/ban, discrete scales, flat palette, fixed hero/text gradient | L:150–265 | Не исследован |
| Motion | Bezier, IO/rAF, навигация, обязательный per-word tagline | L:267–291,335–351 | Не исследован |
| Adaptive / a11y | Mobile menu, wrapping, focus/skip/alt/semantic/reduce; нет breakpoint/contrast matrix | L:48,141,168,275–345 | Не исследован |
| Execution | Нет install/build/test/export runner, model API и model pin | Весь L; tree | Не исследован |
| Evidence | Checklist; нет executable eval и measured outcome | L:371–397; tree | Не исследован |
| License | Elaya MIT + встроенный Leonxlnx MIT; внешние assets отдельно | LIC; L:401–431 | Не исследован |

## 13. Фактически выполненная проверка, coverage и остаток

- `bash .orchestra/tasks/V-1091/inspect.sh` — **exit0**. Сохранён verbatim stdout: [inspection.stdout.txt](evidence/inspection.stdout.txt); stderr пустой. Содержит полное нумерованное L/R/LIC/O1/O2 и ровно указанную выборку M. Проверена неизменность AGENTS, pyproject, uv.lock относительно baseline.
- `node .orchestra/tasks/V-1091/verify-evidence.mjs` — **exit0**. [verification.stdout.txt](evidence/verification.stdout.txt), stderr пустой. Проверены HEAD/tree, отсутствие truncation, sizes/SHA-1 всех GitHub blobs (включая лицензионные тексты), SHA-256 official snapshots относительно сохранённого manifest; manifest обновлён. Арифметика byte limits вычисляется из текущего размера AGENTS и L, без инварианта на конкретный размер AGENTS. Проверок формулировок отчёта/источников и точного числа разделов нет.
- `node .orchestra/tasks/V-1091/check-artifacts.mjs` — **exit0**. [artifacts.stdout.txt](evidence/artifacts.stdout.txt), stderr пустой. Проверены локальные ссылки отчёта, число колонок Markdown/TSV, неизменность трёх baseline-файлов и формы секретов в task artifacts (9 классов паттернов, совпадений нет). Фильтр конечный, не доказательство отсутствия всех мыслимых секретов; приватные env/logs не читались. Публичная SSH SIGNATURE в GitHub metadata не является private key.
- HTTP `curl -fsSL` получения всех источников — **exit0**; байты ответов сохранены. Команды и оговорки о выводе: [commands.md](commands.md).
- Начальная проверка `sha256sum AGENTS.md CLAUDE.md pyproject.toml uv.lock` вернула **exit1**: `sha256sum: CLAUDE.md: No such file or directory`. В предоставленной копии CLAUDE.md отсутствует. Успешные три строки записаны baseline и далее проверены. В рамках research файл/симлинк не создавался; это не заключение о состоянии исходного репозитория root.
- Продуктовый код не менялся; Python, `app`, pytest и provisioned uv не запускались. Обязательного Python check для этих артефактов нет; абсолютный путь импортированного `app` неприменим: import не выполнялся. Системный Python не использован и другой runner не выдаётся за required uv.
- Источниковые shell/JS snippets, Figma, browser capture, FFmpeg, image/video/model API не запускались. Native skill, пост/видео, redesign companion и upstream credit repos остаются непроверенными. Runtime delivery, build/offline page, visual/functional/a11y quality и cost на модели не проверены экспериментом — это выходит за research scope.

В [notes.md](notes.md) выделены неочевидные факты для root. Изменения ограничены `.orchestra/tasks/V-1091/`; Git commit/push, установка навыков/пакетов, изменение зависимостей/правил, рестарты и deployment не выполнялись. Платформе остаётся импортировать артефакты в `task-V-1091/research-landing-skill`; исследователь не создавал Git HEAD локально.
