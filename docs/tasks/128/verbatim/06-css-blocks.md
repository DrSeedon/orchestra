# `visualize.css` — разбор на смысловые блоки

Номера строк — по `docs/tasks/119/extracted/upstream-visualize.css` (18 391 Б, 793 строки,
Apache-2.0, © OpenAI). Значения ниже приведены дословно; это и есть та «конкретика»,
которую #119 сознательно не переносил.

Всего в файле 101 правило. Что из них — контракт для агента, помечено в самом файле
комментарием `/* Agent-facing contract; keep in sync with SKILL.md. */` (строка 5).

---

## 1. Токены цвета — 25 штук, помечены как контракт (строки 6–36)

```css
--background:  light-dark(rgb(255 255 255), rgb(24 24 24));
--foreground:  light-dark(rgb(26 28 31),    rgb(255 255 255));
--card:        color-mix(in oklab, var(--foreground) 5%, transparent);
--popover:     light-dark(rgb(255 255 255), rgb(45 45 45));
--primary:     light-dark(rgb(51 156 255),  rgb(131 195 255));
--primary-foreground: light-dark(rgb(255 255 255), rgb(13 13 13));
--secondary:   light-dark(rgb(255 255 255 / 96%), rgb(54 54 54 / 96%));
--muted:       color-mix(in srgb, var(--foreground) 10%, transparent);
--muted-foreground: light-dark(rgb(26 28 31 / 49.4%), rgb(255 255 255 / 49.8%));
--accent:      light-dark(rgb(229 242 255), rgb(13 39 63));
--destructive: light-dark(rgb(226 85 7),    rgb(255 133 73));
--border:      light-dark(rgb(26 28 31 / 8%), rgb(255 255 255 / 8.2%));
--input:       light-dark(rgb(26 28 31 / 11.8%), color-mix(in oklab, rgb(0 0 0) 10%, transparent));
--ring:        light-dark(rgb(51 156 255),  rgb(131 195 255 / 76%));
```

Три приёма, которых у нас нет ни одного:

1. **Каждый токен объявлен один раз на обе темы** через `light-dark()`. Нет дублирующего блока.
2. **Производные цвета через `color-mix`**, а не хексом: `--card` и `--muted` выведены из
   `--foreground`. Смена одной переменной перекрашивает всё согласованно.
3. **Полупрозрачные проценты с десятыми** (`49.4%`, `8.2%`, `11.8%`) — подобраны, а не круглые.

## 2. Ручной оверрайд темы (строки 79–85)

```css
:root[data-theme="light"] { color-scheme: light; }
:root[data-theme="dark"]  { color-scheme: dark;  }
```

Три строки дают переключатель темы поверх системной.

## 3. Шкала кеглей — ЗАКРЫТЫЙ именованный набор (строки 30, 43–48)

```css
--font-size-base:    14px;
--font-size-normal:  max(11px, var(--font-size-base));
--font-size-tooltip: calc(var(--font-size-base) - 1px);
--font-size-small:   max(11px, calc(var(--font-size-base) - 2px));
--font-size-h1:      calc(var(--font-size-normal) * 1.7142857143);
--font-size-h2:      calc(var(--font-size-normal) * 1.4285714286);
--font-size-h3:      calc(var(--font-size-normal) * 1.2857142857);
```

Шесть имён, и других кеглей в файле нет. Обратите внимание на `max(11px, …)` — нижний
предел читаемости, который нельзя случайно продавить.

Веса и интерлиньяж — тоже закрытым набором (строки 49–53):

```css
--font-weight-normal: 430;      /* нецелый вес: чуть плотнее обычного 400 */
--font-weight-medium: 500;
--line-height-normal:  calc(var(--font-size-normal)  * 1.5);
--line-height-tooltip: calc(var(--font-size-tooltip) * 1.4285714286);
--line-height-small:   calc(var(--font-size-small)   + 4px);
```

Заголовки (строки 126–145) берут `line-height: 1.25` для h1/h2 и `1.3` для h3–h6,
а вес — всегда `--font-weight-medium`, никогда `bold`.

## 4. Ритм отступов — 2px-сетка, НЕ токенизирована (весь файл)

Токенов отступов в файле нет вообще. Но множество фактически использованных значений закрыто:

```
padding / gap:  2, 3, 4, 5, 6, 8, 10, 12, 16, 24 px
```

Высоты контролов — тоже закрытый набор: `28px` (кнопка, поле, селект, слайдер),
`26px` (кнопка выбора файла), `20px` (переключатель, ползунок-бегунок),
`16px` (шарик переключателя), `14px` (чекбокс, радио), `72px` (минимум textarea).

## 5. Радиусы — от одной базы (строки 54–59)

```css
--radius:      12.5px;
--radius-sm:   calc(var(--radius) * 0.6);    /*  7.5px */
--radius-md:   calc(var(--radius) * 0.8);    /* 10px   */
--radius-lg:   var(--radius);                /* 12.5px */
--radius-2xl:  calc(var(--radius) * 1.6);    /* 20px   */
--radius-full: 9999px;
```

Плюс `corner-shape: superellipse(1.5)` рядом с каждым скруглением (8 вхождений) —
скругление «как у iOS», а не циркульная дуга.

Отдельно: в текстовой инструкции gpt-5.5 сказано «Cards are kept at 8px border radius or
less», а в CSS карточка — `--radius-2xl` = 20px. Инструкция и дизайн-система расходятся;
это их противоречие, не наше.

## 6. Тень — механизм состояния, а не глубина (строка 60 + 12 вхождений)

```css
--shadow-sm: 0 1px 2px -1px rgb(0 0 0 / 8%);
```

Одна тень на весь файл, и она почти не про высоту. Из 12 `box-shadow`:
9 — фокусные кольца `inset 0 0 0 1px var(--ring)` / `0 0 0 2px var(--ring)`,
2 — `--shadow-sm` (шарик переключателя и чекбокс), 1 — явное `box-shadow: none` у тултипа.

## 7. Палитра серий — шесть тонов, подобраны для обеих тем (строки 31–36)

```css
--viz-series-1: var(--primary);                                       /* синий  */
--viz-series-2: light-dark(rgb(243 136 59),  rgb(245 154 86));        /* оранж  */
--viz-series-3: light-dark(rgb(93 201 119),  rgb(116 213 139));       /* зелень */
--viz-series-4: light-dark(rgb(235 119 177), rgb(240 143 192));       /* розовый*/
--viz-series-5: light-dark(rgb(155 121 236), rgb(170 145 239));       /* фиолет */
--viz-series-6: light-dark(rgb(58 185 177),  rgb(90 203 194));        /* бирюза */
```

В тёмной теме каждый тон светлее и менее насыщен — это не автоматический сдвиг, а ручная
пара на каждый цвет.

## 8. Состояния фокуса — на каждом контроле (8 селекторов `:focus-visible`)

Два разных приёма, применяются по типу элемента:

```css
.form-control:focus-visible,
.form-select:focus-visible   { border-color: var(--ring); box-shadow: inset 0 0 0 1px var(--ring); }
.btn:focus-visible           { outline: 2px solid var(--ring); outline-offset: 2px; }
.form-check-input:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
.form-switch .form-check-input:focus-visible { box-shadow: 0 0 0 2px var(--ring); }
```

Плюс состояние «выбрано» отдельно от фокуса (строки 759–772):

```css
.btn:not(.btn-primary, .viz-tile):is([aria-pressed="true"], [aria-selected="true"], .is-selected) {
  border-color: var(--primary); color: var(--primary-foreground); background: var(--primary);
}
```

И `.sr-only` (строки 337–346) — стандартный приём скрытия текста для скринридера.

## 9. Таблицы — полноценный компонент (строки 167–230, 14 правил)

```css
.table :is(th, td)  { padding-block: 10px; padding-inline: 0 24px;
                      border-bottom: 1px solid var(--border); vertical-align: top; }
.table thead th     { padding-block: 8px;
                      border-bottom-color: color-mix(in srgb, var(--foreground) 16%, transparent); }
.table tbody tr:last-child :is(th, td) { border-bottom: 0; }
.table.table-sm :is(th, td) { padding-block: 6px; }
.table :is(.text-end, [align="right"]) { text-align: end; font-variant-numeric: tabular-nums; }
.table-responsive { width: 100%; overflow-x: auto; scrollbar-width: thin; }
```

Четыре решения, которые и делают таблицу «дизайнерской»: линии только снизу и только между
строк (последняя без линии), шапка отделена более контрастной линией, числовые колонки —
моноширинными цифрами, узкий экран — горизонтальная прокрутка вместо переноса.

## 10. Тултип (строки 263–291)

```css
.tooltip {
  position: fixed; z-index: 50;
  max-width:  min(20rem, var(--tooltip-available-width,  calc(100vw - 10px)), calc(100vw - 10px));
  max-height: min(var(--tooltip-available-height, calc(100vh - 10px)), calc(100vh - 10px));
  padding: 4px 8px; border: 1px solid var(--border); border-radius: var(--radius-lg);
  background: var(--popover); box-shadow: none;
  font-size: var(--font-size-tooltip); line-height: var(--line-height-tooltip);
  pointer-events: none; user-select: none;
}
```

Позиционирование — на Floating UI с `unpkg.com` (`upstream-visualize.html`), задержка 700 мс,
`aria-describedby`, закрытие по Escape. **Это единственный блок, который нам не переносится
как есть: он тянет внешний JS и ломает наше правило «работает офлайн».**

## 11. Прочее, что стоит заметить

- `.viz-grid` — `repeat(auto-fit, minmax(max(180px, 24%), 1fr))`, то есть минимум колонки
  зависит и от пикселей, и от доли ширины.
- `.viz-badge` — `border-radius: var(--radius-full)`, фон `--accent`, текст `--accent-foreground`.
- `#widget > :not(.card)` (строки 252–261) — принудительно сбрасывает у не-карточек рамки,
  фон и тени. Это машинное исполнение правила «секции не оформляются карточками».
- `code:not(pre code)` — `box-decoration-break: clone`, чтобы фон не рвался на переносе строки.
- `.form-select` рисует стрелку двумя `linear-gradient` 4×4px — без картинки и без SVG.
- `[data-lucide] { stroke-width: 1.6 }` — иконки тоньше дефолтных 2px.
- `svg { display: block; max-width: 100%; height: auto }` — глобально.
- `@media` в файле **нет ни одного**: он живёт внутри чужого вьюера и адаптивность делает
  через `min()`/`max()`/`auto-fit`, а не брейкпоинтами. Печати тоже нет.
