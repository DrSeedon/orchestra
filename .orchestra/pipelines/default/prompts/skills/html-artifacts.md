---
name: html-artifacts
description: Оформить ответ самодостаточным .html вместо markdown, когда нужны вёрстка, цвет, схемы или интерактив. Триггеры — артефакт, отчёт, дашборд, сравнение, схема, слайды, план, пост-мортем, визуализация, «покажи наглядно», ответ длиннее ~100 строк.
---

# HTML Artifacts

Генерируй `.html`, когда содержимое выигрывает от вёрстки, цвета, схем или интерактива.
Markdown — для коротких ответов, кода, команд и одноразовых сводок.

## Обязательное

1. **Один файл** — CSS в `<style>`, JS в `<script>`, графика инлайновым SVG или data-URI
2. **Работает офлайн** — внешний CDN только для Chart.js/uPlot и только если нужны графики
3. **Две шрифтовые семьи, обе локальные.** Веб-шрифты и CDN шрифтов запрещены — но одна
   семья на весь артефакт запрещена тоже. Заголовки и текст берут РАЗНЫЕ семьи из набора:
   `ui-serif, Georgia, "Times New Roman", serif` · `ui-sans-serif, system-ui, sans-serif` ·
   `ui-rounded, "Segoe UI", sans-serif` · `ui-monospace, SFMono-Regular, Menlo, monospace`.
   Начертания тоже разные: текст 430, заголовки 500, шапка таблицы 600 — не один 400 на всё
4. **Тёмная и светлая** — `color-scheme: light dark` на `:root`, значения через
   `light-dark(светлое, тёмное)`; дублирующий `@media (prefers-color-scheme)` не нужен
5. **`@media print`** — белый фон, чёрный текст, элементы управления скрыты, `print-color-adjust: exact`
6. **Адаптивность** — `<meta name="viewport">`, сетки `auto-fit` + `minmax`
7. **Язык пользователя** во всём тексте
8. **Читается за 5 секунд** — заголовок, абзац сути, дальше содержание
9. **Durable source** — факты в Markdown/JSON, HTML это представление; редактор выгружает состояние обратно
10. **Проверь рендером, а не глазами по коду** — если есть JS, открой headless: страница не
    пустая, консоль чистая. `const top/left/name` на верхнем уровне роняют скрипт целиком

## Костяк

Вставь целиком и **меняй только пять ручек** сверху. Всё ниже «система» скопируй как есть:
там уже выбрано, выбирать нечего. Кегли, радиусы и отступы бери ТОЛЬКО из этих наборов —
седьмого кегля не существует, `calc()` со своим множителем не изобретай.

```css
/* костяк производен от visualize.css, (c) OpenAI, Apache-2.0;
   изменено: убран внешний JS, добавлены печать и вторая шрифтовая семья */
:root{
  color-scheme: light dark;
  /* ── ручки: пять решений под предмет артефакта ─────────────────────── */
  /* --accent объяви здесь САМ, двумя тонами под предмет: light-dark(для светлой, для тёмной).
     Готового значения тут нет намеренно — иначе все артефакты снова станут одного цвета.
     Без этой строки костяк не работает: на неё завязаны кольцо фокуса, бейдж и серия --s1 */
  --fs: 15px;                              /* 14–16 */
  --radius: 12px;                          /* 12 обычно, 4 строгим темам, 0 схемам */
  --font: ui-sans-serif, system-ui, sans-serif;        /* текст */
  --font-head: ui-serif, Georgia, serif;               /* заголовки — ДРУГАЯ семья */
  /* ── система: копируется как есть ──────────────────────────────────── */
  --bg: light-dark(#fff, #181818);
  --ink: light-dark(#1a1c1f, #f2f2f0);
  --mut: color-mix(in srgb, var(--ink) 48%, transparent);
  --card: color-mix(in oklab, var(--ink) 5%, transparent);
  --border: color-mix(in srgb, var(--ink) 12%, transparent);
  --ring: var(--accent);
  --bad: light-dark(#c0341a, #ff7a63);
  --fs-sm: max(11px, calc(var(--fs) - 2px));
  --fs-h3: calc(var(--fs) * 1.29);
  --fs-h2: calc(var(--fs) * 1.43);
  --fs-h1: calc(var(--fs) * 1.72);
  --r-sm: calc(var(--radius) * .6);
  --r-lg: calc(var(--radius) * 1.6);
  --shadow: 0 1px 2px -1px rgb(0 0 0 / 8%);
  --s1: var(--accent);                     /* серии графиков и категорий */
  --s2: light-dark(#c26a1f, #f59a56);
  --s3: light-dark(#2f7d46, #74d58b);
  --s4: light-dark(#b8457f, #f08fc0);
  --s5: light-dark(#6b57c4, #aa91ef);
  --s6: light-dark(#1f7a72, #5acbc2);
  /* отступы только из ряда: 2 4 6 8 12 16 24 40 */
}
*{box-sizing:border-box}
body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);
     font:430 var(--fs)/1.5 var(--font);letter-spacing:0}
h1,h2,h3{margin:0;font-family:var(--font-head);font-weight:500;line-height:1.25}
h1{font-size:var(--fs-h1)} h2{font-size:var(--fs-h2)} h3{font-size:var(--fs-h3)}
small,.sm{font-size:var(--fs-sm)} .mut{color:var(--mut)}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 24px 10px 0;border-bottom:1px solid var(--border);
      text-align:start;vertical-align:top;overflow-wrap:anywhere}
th{font-weight:600;border-bottom-color:color-mix(in srgb,var(--ink) 16%,transparent)}
tbody tr:last-child :is(th,td){border-bottom:0}
.num{text-align:end;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;scrollbar-width:thin}
.card{padding:12px;border-radius:var(--r-lg);background:var(--card)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(max(180px,24%),1fr));gap:12px}
.badge{padding:3px 8px;border-radius:9999px;font-size:var(--fs-sm);
       background:color-mix(in srgb,var(--accent) 15%,transparent)}
code{padding:1px 6px;border-radius:var(--r-sm);font-size:.92em;
     font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
     background:color-mix(in srgb,var(--ink) 10%,transparent);
     box-decoration-break:clone;-webkit-box-decoration-break:clone;overflow-wrap:anywhere}
:is(a,button,summary,input,select,[tabindex]):focus-visible{
     outline:2px solid var(--ring);outline-offset:2px}
:is([aria-pressed="true"],[aria-selected="true"]){background:var(--accent);color:var(--bg)}
svg{display:block;max-width:100%;height:auto}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
@media print{
  :root{color-scheme:light}
  body{padding:0;background:#fff;color:#000}
  .no-print{display:none}
  tr,li{break-inside:avoid}
  *{print-color-adjust:exact;-webkit-print-color-adjust:exact}
}
```

Тень одна на весь файл и только для высоты; всё остальное состояние — кольцо `--ring`
и фон `--accent`, а не новая тень.

## Палитра выводится из предмета

Фиксированного акцента нет. Подбери `--accent` под тему конкретного артефакта и поясни выбор
комментарием: `/* акцент: <цвет> — <почему он про этот предмет> */`.

Ориентиры, не список для копирования: разбор сбоя — тревожный тёплый; деньги и рост — зелёный;
инфраструктура — холодный синий; юридическое — нейтраль с одним акцентом. Соседние артефакты
одной сессии обязаны отличаться по тону.

- **Не одноцветная палитра.** Не строй интерфейс на вариациях одного семейства. Особенно
  избегай доминирующего фиолетового и фиолетово-синего, а также беж, тёмно-синий и
  коричнево-оранжевый как тему целиком; перед сдачей просмотри цвета и переделай, если
  страница читается как одна из них
- **Серии, категории, статусы** — `--s1…--s6` из костяка, они уже разнесены по кругу и
  подобраны для обеих тем. Не оттенки одного цвета и не свои хексы

## Плотность и композиция

- Отчёт, дашборд, разбор — спокойно и утилитарно, плотно, для сканирования. Без hero и обложек.
  Бытовая или праздничная тема — наоборот, живее: крупнее, теплее, с воздухом
- Карточка не внутри карточки; секции — полосы, а не плавающие карточки
- Без градиентных пятен, шаров и размытых клякс
- Крупный шрифт только настоящим заголовкам; в карточках, панелях и таблицах мельче и плотнее
- Текст помещается в свой элемент на узком и широком экране и не наезжает на соседей
- Фиксированным по формату элементам (плитки, счётчики, иконки, ячейки сетки) задавай размер
  через `aspect-ratio`, треки грида или `min/max`, чтобы ховер и длинная подпись не двигали вёрстку
- Артефакты отличаются не только цветом: меняй композицию, плотность, шрифтовую пару

## Схемы (inline SVG)

`viewBox` вместо размеров · `currentColor` для чернил · текст тегом `<text>` · стрелки через
`<defs><marker>` · основной путь акцентом, ошибочные ветки приглушённо.

Два дефекта, которые видно только на зуме фигуры, а не на полностраничном скриншоте:
стрелка, стартующая ВНУТРИ блока, перечёркивает его же подпись — начинай от края;
`<text>` не переносится — длинная подпись молча вылезает на соседний блок, режь её на
`<tspan>` по строкам или укорачивай.

## Антипаттерны

Эмодзи вместо заголовков · стеклянный блюр · дженерик-админка на Tailwind · всё по центру.
Хорошо — спокойная типографика, сдержанные чернила, максимум два акцента, настоящие схемы.

## Куда сохранять

`artifacts/` или `.orchestra/artifacts/`, имя kebab-case. Сообщи путь; в Orchestra добавь
`send_file(path, caption)`, если артефакт для пользователя.

Версия с примерами по жанрам — `~/.claude/skills/html-artifacts/`, отдельный артефакт, не копия.
