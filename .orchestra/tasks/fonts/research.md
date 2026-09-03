# Шрифты для экранного чтения — research

Дата: 2026-07-11. Задача: подобрать шрифт/типографику для dashboard/tool UI (RU+EN), без "усталости глаз".

## Главный вывод исследований (2024–2025)

Нет единого "лучшего шрифта". VSS 2024 (50 участников, 8 шрифтов) и APPLY Lab (2025, eye-tracking) показывают: **оптимальный шрифт зависит от задачи** (беглое чтение / сканирование / длинные тексты), и **индивидуальные различия читателей больше влияют на скорость чтения, чем выбор шрифта** (UCF Readability Consortium; сопоставимый вывод — исследование Nielsen/возрастное восприятие шрифта). Предпочтение шрифта пользователем НЕ коррелирует со скоростью чтения.
Практический вывод: гнаться за "идеальным" шрифтом бессмысленно — важнее x-height, line-height, размер, контраст.

## 1. Топ-5 шрифтов для экранного чтения (по исследованиям, не мнениям)

| Шрифт | Почему | Источник |
|---|---|---|
| **Verdana** | Многократно признан самым читаемым для экрана в сравнительных исследованиях (vs Times New Roman, Courier New); широкие апертуры, большой x-height | Boyarski et al.; сравнительное исследование serif/sans/mono |
| **Inter** | Высокий x-height, открытые апертуры (в отличие от Helvetica), variable font с optical size axis под мелкий текст. Прямых RCT нет, но дизайн-обоснование сильное + де-факто стандарт UI (414 млрд запросов/год на Google Fonts) | Figma blog, дизайн-анализ (не controlled study) |
| **Noto Sans** | Спроектирован специально под Latin+Greek+Cyrillic одновременно — safe default для RU+EN без "докручивания" кириллицы | Google/Noto project docs |
| **Open Sans** | Нейтральный, хорошо читается на мелких размерах, полноценная кириллица, часто рекомендуется в RU UX-источниках | RU UX guides |
| **Merriweather / Source Serif Pro** | Serif-варианты — в VSS 2024 показали лучший результат для glance-reading (Merriweather) и sentence-reading (Source Serif Pro) соответственно. Полезно для long-form текста, не для UI | VSS 2024 poster |

**Кириллица — важный нюанс**: контролируемых исследований именно кириллических начертаний почти нет (основной корпус — латиница). Практика: те же принципы (открытые апертуры, x-height) применимы, но кириллица имеет более сложные/тяжёлые формы букв (Ж, Ф, Щ) → на мелких размерах предпочтительны шрифты с явной кириллической доработкой (Noto Sans, PT Sans, Open Sans), а не латинские шрифты с "прикрученной" кириллицей.

## 2. Оптимальный размер шрифта для dashboard/tool UI

- **16px (1rem)** — стандартный baseline для основного текста (консенсус, включая Material Design)
- **14px** — минимум для второстепенного/плотного UI-текста
- **12px** — только для caption/footnote/метаданных, никогда для основного контента для чтения
- WCAG **не задаёт** жёсткий минимум в px — требует резинового масштабирования до 200% без потери контента (SC 1.4.4). Используй `rem`, не `px`
- Контраст: 4.5:1 для обычного текста, 3:1 для крупного (≥18.66px bold / ≥24px regular)

Источники: A11Y Collective, WCAG 1.4.4/1.4.10, Material Design guidelines.

## 3. Inter vs другие sans-serif — правда или маркетинг?

- **Нет крупных peer-reviewed исследований**, напрямую сравнивающих Inter с Roboto/Helvetica/Arial по скорости чтения — это ключевой пробел.
- Обоснование читаемости Inter — дизайнерское (x-height, открытые апертуры, optical sizing), а не экспериментальное.
- Reddit/индустрия любят Inter из-за повсеместного использования (GitLab, Mozilla, NASA), но популярность ≠ доказанная эффективность.
- Verdana имеет БОЛЬШЕ экспериментальных доказательств screen-legibility, чем Inter, просто она визуально устарела для современного UI.
- **Вывод**: Inter — разумный default (variable font, широкая языковая поддержка, оптическая настройка под мелкий текст), но не "научно доказанный лучший" — это индустриальный консенсус, не результат RCT.

## 4. Оптимальный line-height

- Консенсус: **1.4–1.6×** размера шрифта
- Ниже 1.4× — текст "слипается", читать сложнее (Baymard Institute)
- Выше 1.7× — текст "разваливается", теряется связность строк
- WCAG рекомендует **минимум 1.5** для основного текста (доступность)
- Для узких колонок (dashboard-панели, сайдбары) — ближе к верхней границе (1.5–1.6)
- Line-length (тесно связано): 50–75 символов на строку, ~66 CPL — оптимум (Ruder; Visible Language 2005 literature review)

## 5. Специальные шрифты для снижения усталости глаз (long-reading)

- **Luciole** (ScienceDirect, peer-reviewed, 145 читателей 6-35 лет, включая слабовидящих) — показал небольшое преимущество перед Arial/Verdana/Eido/OpenDyslexic в предпочтениях слабовидящих читателей. Реальный научный результат, не маркетинг
- **Atkinson Hyperlegible** — фокус на различении похожих символов (I/l/1, 0/O), разработан Braille Institute
- **ACT Easy Regular** (PLOS One 2026) — лучший результат в MNREAD-тесте при симуляции слабого зрения (20/90)
- Для здорового зрения без спец. условий — **разница между "обычным" хорошим UI-шрифтом (Inter/Noto/Verdana) и спец. accessibility-шрифтом статистически не доказана**, спец-шрифты нужны конкретно для low-vision/дислексии
- Усталость глаз (asthenopia) физиологически изучена слабо — большинство рекомендаций (контраст, line-height, 20-20-20) снижают *усилие* чтения, но не "лечат" усталость медицински

## Рекомендация для Orchestra dashboard

1. Оставить **Inter** как основной UI-шрифт (уже используется, `hybrid font` решение из session notes) — индустриальный стандарт, обоснованный дизайн под мелкий текст, хорошая поддержка кириллицы
2. Body text — **16px**, плотный UI (таблицы, лейблы) — не ниже **14px**, caption/timestamps — 12px допустимо
3. `line-height: 1.5` для основного текста, `1.4` для плотных таблиц/списков допустимо
4. Использовать `rem`, не `px`, для соответствия WCAG 1.4.4
5. Контраст ≥4.5:1 — уже отдельно проверено в frontend design audit (session notes 07-11)

## Источники

- [VSS 2024: Readability Research Posters](https://readabilitymatters.org/articles/vss-2024-readability-research-posters-published)
- [Font Matters: Investigating Typographical Components of Legibility — IJRISS](https://rsisinternational.org/journals/ijriss/articles/font-matters-investigating-the-typographical-components-of-legibility/)
- [Assessment of newly designed fonts for visual accessibility — PLOS One 2026](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0345068)
- [New study shows font readability is very individual — Readable](https://readable.com/blog/new-study-shows-font-readability-is-very-individual/)
- [Luciole, a new font for people with low vision — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0001691823001026)
- [Typeface features and legibility research — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0042698919301087)
- [Towards a standardisation of reading charts: Times New Roman vs Helvetica — Ophthalmic and Physiological Optics 2022](https://onlinelibrary.wiley.com/doi/10.1111/opo.13039)
- [Optimal Line Length in Reading — A Literature Review, Visible Language 2005](https://journals.uc.edu/index.php/vl/article/view/5765)
- [Readability: The Optimal Line Length — Baymard Institute](https://baymard.com/blog/line-length-readability)
- [WCAG Minimum Font Size — A11Y Collective](https://www.a11y-collective.com/blog/wcag-minimum-font-size/)
- [The birth of Inter — Figma Blog](https://www.figma.com/blog/the-birth-of-inter/)
- [Inter (typeface) — Wikipedia](https://en.wikipedia.org/wiki/Inter_(typeface))
