# V-663: skillry.dev/ai-videos/opus-5-5 — из чего сделаны 389 «вирусных видео Opus 5.5»

Исследование класса B, только чтение. Источники: пересланное владельцем видео
`data/uploads/ssstwitter.com_1790652010923.mp4` (31 с, покадрово разобрано в
`frames/`), сырой HTML страницы skillry.dev (`skillry_opus55_raw.html`, 586 КБ,
скачан напрямую curl'ом 29.09, HTTP 200) и распарсенные из него 389 карточек
(`skillry_opus55_entries.json`). Сама страница — Next.js-стрим с эмбеднутым JSON
по каждому видео (`slug`, `authorHandle`, `prompt`, `promptTruncated`,
`promptPartial`, `category`, `techTags`), это первичные данные сайта, а не
пересказ WebFetch — числа по категориям (`motion 223 / interactive 68 / 3d 51 /
explainer 47`) совпадают с навигацией на странице день в день, что подтверждает,
что парсинг попал в реальные данные, а не в шум.

## Что на самом деле показывает пересланное видео

`ssstwitter.com_1790652010923.mp4` — это НЕ рендер одного из 389 роликов, а
скринкаст того, как кто-то листает саму галерею skillry.dev (скачан через
твиттер-даунлоадер ssstwitter, отсюда имя файла). На кадрах: шапка сайта,
сетка превью 389 карточек по категориям, и один открытый пример (`@twoclipping`,
motion/svg) с панелью «Original / Remake» и раскрытым полем Prompt. Именно из
этого кадра видно, что промпты у части роликов — структурированные,
XML-размеченные тексты, а не одна строка.

## Технологии рендера (агрегация по 389 карточкам, поле `techTags`)

| tech | штук | доля |
|---|---|---|
| canvas | 288 | 74% |
| threejs | 130 | 33% |
| svg | 125 | 32% |
| shader (GLSL) | 95 | 24% |
| gsap | 59 | 15% |
| css | 39 | 10% |
| audio (Web Audio API) | 36 | 9% |
| particles | 26 | 7% |
| playable (реально интерактивная игра, не просто запись) | 21 | 5% |
| pixel | 15 | 4% |
| webgl | 9 | 2% |
| physics | 9 | 2% |
| ai-image (сгенерированные картинки как ассеты) | 9 | 2% |

Вывод по механике: 100% роликов — это самодостаточные HTML/CSS/JS-страницы
(Canvas 2D, SVG, Three.js/WebGL/GLSL-шейдеры, GSAP для таймлайнов, изредка
Web Audio для звука), которые Opus 5.5 пишет как код, а не «видео» в смысле
покадровой генерации пикселей моделью. Remotion, Manim, After Effects или
запись реального экрана нигде не упомянуты и не встречаются в тегах.
Дальше HTML-сцену кто-то превращает в файл `.mp4` (в карточках есть
`durationSeconds`, `width`, `height`, `originalPreviewUrl`/`remakePreviewUrl` —
то есть на сайт заливают именно видеофайл, не iframe). Как именно происходит
запись (headless-браузер + запись вкладки, судя по повсеместной практике для
такого контента — например через Playwright с `record_video_dir`) — на странице
не описано ни разу; это моя гипотеза по типовой практике жанра, не факт с сайта,
и я явно помечаю её как непроверенную.

Часть карточек (`playable`, 21 шт.) — не видео, а встроенная интерактивная
Canvas/Three.js-игра поверх той же техники; сайт сам это не афиширует отдельно
от «видео», это видно только по тегу.

## Промпты: 3–5 дословных примеров

Дословно из поля `prompt` в данных страницы (декодировано из JS-escape, без
перевода):

1. **`@twoclipping`, motion/svg** — структурированный, с XML-тегами (сайт режет
   его на 2711 символов, `promptTruncated:true`, обрывается на «Springs eve…»):
   ```
   <inputs>
   Ask me for: 8 to 12 UI states I want the shape to become (e.g. button,
   loader, player, slider, toggle, tabs, chart, command palette, toast),
   pure black and white or one accent color, and a royalty-free song around
   120 BPM (e.g. Mixkit, free for commercial use).
   </inputs>

   <direction>
   Dribbble-level UI motion. One shape, never cut: every state is the same
   element morphing its size, radius and color while its content swaps with
   a short blur. A cursor drives every change with real clicks and drags.
   Light warm-gray canvas, black and white components, one clean UI font
   (Geist). Springs eve…
   ```

2. **Шаблон «шоурил моушн-дизайнера»** — встречается почти дословно у **87 из
   389** карточек (22% всей подборки), с косметическими вариациями под свой
   продукт/сайт:
   ```
   make a dynamic 15-second motion graphics video that shows what an
   incredible motion designer you are, like it's your showreel for a
   résumé. go all out.
   ```

3. **`@stephanferraro`, explainer/threejs** (бенчмарк-стиль отчёта, не просто
   промпт):
   ```
   Claude Opus 5.5 on our AI coding benchmark: build a fully autonomous 3D
   water simulation from an empty repo - procedural mountains, rain,
   streams, lakes. TypeScript + Three.js, no physics engine.

   One prompt, zero corrections, ~21 min. 23/23 tests green.
   https://github.com/AiondaDotCom/ai-sim-benchmark
   ```

4. **`@mandelduck`, interactive/threejs** (категория «игры»):
   ```
   can you make a 3d game where you walk around and spot cats inside of a
   van gogh painting? we can start with stary night and its town
   ```

5. **`@explorations_iq`, explainer/threejs** — честная оговорка о ручной
   доводке, а не идеальный one-shot:
   ```
   Opus 5.5 generated this simulation of molecular orbitals in about ~20
   minutes. I had to prompt for some structures and resonance but I can see
   the promise of instant educational simulations for any advanced topic
   ```

## Что делает Opus сам, а что — инструменты

Модель пишет весь код сцены (Canvas/SVG/Three.js/GLSL/GSAP/Web Audio) одним
файлом по короткому текстовому промпту — это подтверждено самими промптами
(п.1–5 выше) и заявлениями авторов («one prompt, zero corrections», «$0
additional cost», «one HTML file»). Рендер в видеофайл, хостинг превью
(`media.skillry.dev/...mp4`) и сама витрина «оригинал/remake» — работа сайта
Skillry, не модели: `@skillry_dev` в атрибуции «Remake» — это их собственный
повторный прогон промпта для витрины, отдельный от оригинального поста автора.

Важная оговорка про честность промптов: у **110 из 389** карточек
(`promptPartial:true`) поле `prompt` — это НЕ инструкция для модели, а текст
твита с фразами вида «prompt in the replies», «Prompt in next post» (например,
`@cyrilxbt`: «this entire physics engine is one HTML file… prompt in the
replies 👇» — сам промпт на странице не приведён). То есть заявленные «389
промптов, которые можно скопировать» на практике — это максимум ~279 реально
рабочих промптов, а из них 87 — один и тот же мем-шаблон под копирку. Маркетинг
страницы («copy the exact prompt the creator used») правдив только частично.

## Лицензия

Блок «Code's here, MIT licensed» встречается ровно у одной карточки
(`@nybobs`, физика твёрдых тел, WebGPU) — это лицензия автора на СВОЙ
GitHub-репозиторий, а не общая лицензия Skillry на промпты/код витрины. У
остальных карточек — только атрибуция автора и ссылка на исходный пост в X;
общего заявления «все промпты свободны для реиспользования» на странице нет
(проверено по `/terms`, `/privacy`, `/third-party-notices` в навигации — сайт
разводит эти страницы по ссылкам, отдельно копирайта на промпты не декларирует).
Публиковать чужой дословный промпт как «наш» в открытых материалах — вопрос
атрибуции автора твита, не техническая лицензия.

## Сопоставление с тем, что уже есть у нас

**Скилл `html-artifacts`** (`.claude/skills/html-artifacts/SKILL.md`, единый
для Orchestra/Claude Code/Codex) — уже покрывает ровно тот же технический слой:
самодостаточный `.html` с inline CSS/JS/SVG, допускает Three.js «при
необходимости встроить в файл с лицензией», честные данные, hover-интерактив.
**Вердикт: уже есть.** Разница в цели, не в технологии: наш скилл делает
статичные/интерактивные объясняющие артефакты для чтения владельцем в
браузере (дашборды, схемы, ELI5), а не «вирусные ролики» для соцсетей —
никаких изменений в скилл переносить не нужно, техника (Canvas/SVG/Three.js/
GSAP, честные данные, один файл) там уже прописана лучше, чем то, что видно
на skillry.dev (у них нет правил честности данных/единиц, которые есть у нас).

**Рендер HTML-анимации в MP4 и отправка в Telegram** — вот это у нас
технической опоры пока нет. `send_file`/`send_files` умеют отправлять готовый
файл, но пайплайна «HTML/Canvas-анимация → запись во время выполнения →
.mp4» в проекте нет; `webapp-testing` даёт Playwright для тестирования, но не
документирует запись видео. **Вердикт: брать, но точечно.** Цена переноса
невысокая: у Playwright есть встроенная запись контекста
(`browser.new_context(record_video_dir=...)`), достаточно короткого скрипта
поверх уже одобренного `html-artifacts`-файла и ffmpeg для финальной
упаковки/обрезки. Смысл — не «вирусные ролики», а анимированные
видео-объяснялки к отчётам владельцу (например, показать динамику деградации
метрики или последовательность шагов инцидента как короткое видео вместо
серии скриншотов) и материал для будущих демонстраций. Это НЕ реализовано в
рамках этой задачи (задача read-only), только зафиксировано как возможное
расширение с низкой ценой.

**Сам подход «387 копий одного мем-промпта выдают за 389 уникальных примеров»**
— не техника, которую стоит перенимать: это маркетинговый приём Skillry (SEO
под «viral Opus 5.5 prompts»), а не сигнал о технологии. Вердикт: **не брать**,
информационно к сведению — при взгляде на подобные подборки в будущем сразу
проверять реальную уникальность промптов через дедупликацию текста, а не
доверять заявленному числу «X вирусных видео».

## Ограничения этого исследования

Не проверялось: как именно Skillry технически записывает HTML-сцену в .mp4
(сайт этого не публикует, а частный технический блог по теме не искался —
не требовалось для вердиктов выше). Не открывались все 389 карточек построчно
— вывод о технологиях и структуре опирается на агрегацию по `techTags`,
`category`, `promptTruncated/Partial` из данных самой страницы, а образцы
промптов — на прямую выборку и её ручную проверку по исходному HTML. Домены
`skillry.dev` и `media.skillry.dev` не проверялись на благонадёжность сверх
того, что содержимое соответствует заявленному (a именно: числа по категориям
сошлись, данные структурны и внутренне непротиворечивы).

## Файлы-свидетельства

Сырьё большого объёма в git не кладу — оно временное и легко переснимается заново
(curl/ffmpeg), поэтому лежит вне репозитория, в `/tmp/v663-evidence/` (не переживёт
перезагрузку/tmpfs-очистку; это ожидаемо, в отчёте выше все нужные выдержки уже
приведены дословно):

- `skillry_opus55_raw.html` — сырой HTML страницы (curl, 29.09, HTTP 200)
- `skillry_opus55_entries.json` — 389 карточек, распарсенные из HTML
  (`slug`, `author`, `prompt`, `promptLength`, `truncated`, `partial`,
  `category`, `techTags`)
- `frames/f1_001.png`, `f1_020.png` — общий вид галереи
- `frames/f1_011.png`, `f1_012.png` — раскрытая панель промпта (`@twoclipping`)
