# Дизайн-система дашборда Orchestra

Один источник правды для цветов и общих компонентов дашборда. Витрина всех компонентов
собирается из настоящего CSS: `.orchestra/tasks/V-876/showcase.html`
(`python3 .orchestra/tasks/V-876/build_showcase.py`).

## Где что живёт

| Файл | Что в нём |
|---|---|
| `app/static/css/design-system.css` | Токены (`:root`) и компоненты `ds-*`. Грузится первым из наших стилей — в дашборде и на странице входа. |
| `app/static/js/theme.js` | Какой токен у модели / поставщика / статуса. Грузится до `utils.js`. Цветов не хранит. |
| `app/static/css/style.css` | Стили конкретных экранов. Цвета — только через `var(--…)`. |
| `tailwind.config.js` | Шкала slate для разметки шаблонов; токены повторяют её значения. |

Правило: **у цвета со смыслом один источник — токен.** Новый hex в `style.css` или JS — второй
источник, и он разойдётся с первым. Именно так и было до V-876: Opus в списке агентов был
оранжевым (запасной цвет поставщика, потому что ключ `claude-opus-5[1m]` в `_MODEL_COLORS`
устарел), в «Инфо» — серым, а Luna, Sol и Astra в списке — одинаково зелёными.

## Палитра

### Модели — один цвет на всех экранах

| Семейство | Токен | Цвет | Узнаётся по id/псевдониму |
|---|---|---|---|
| Opus | `--model-opus` | `#fb923c` оранжевый | `opus` |
| Sonnet | `--model-sonnet` | `#38bdf8` голубой | `sonnet` |
| Haiku | `--model-haiku` | `#4ade80` зелёный | `haiku` |
| Fable | `--model-fable` | `#fb7185` розово-красный | `fable`, `mythos` |
| Luna | `--model-luna` | `#2dd4bf` бирюзовый | `luna` |
| Sol | `--model-sol` | `#f472b6` розовый | `sol`, `codex` |
| Astra | `--model-astra` | `#c084fc` фиолетовый | `astra` |
| Spark | `--model-spark` | `#e879f9` фуксия | `spark` |
| Grok | `--model-grok` | `#e2e8f0` белый | `grok` |

Семейство определяет `modelFamily(id)` по полному id (`claude-opus-5-5[1m]`), псевдониму
(`opus`, `luna`) или подписи (`Opus 5.5`). Поэтому новая версия модели получает свой цвет
без правки кода. Модель без семейства (OpenRouter, GigaChat…) красится цветом поставщика.

### Поставщики и пулы квот

Цвет поставщика = цвет его флагманской модели: Claude (`--provider-anthropic`) — оранжевый,
Codex (`--provider-openai`) — бирюзовый, Grok (`--provider-x-ai`) — белый. Плюс
`--provider-openrouter`, `--provider-gigachat`, `--provider-deepseek`, `--provider-unknown`.
Вторая линия того же пула на графике (окно 7 д рядом с 5 ч) — светлая пара `*-soft`.

Полосы графика лимитов (quota-lines): Sol — `--model-sol`, Luna — `--model-luna`,
Spark — `--model-spark`, Claude — `--provider-anthropic`.

### Статусы агента

| Статус | Иконка | Токен цвета / фона |
|---|---|---|
| running | ⚡ | `--status-running` / `--status-running-bg` |
| waiting | 📆 | `--status-waiting` / `-bg` |
| idle | ☕️ | `--status-idle` / `-bg` |
| broken | ⛔ | `--status-broken` / `-bg` |
| error, stopped, starting | ● | `--status-error`, `--status-stopped`, `--status-starting` |

Иконка несёт смысл, цвет его дублирует: idle и waiting по одному оттенку не различить.
Подпись всегда переведена: `T(status)`.

### Поверхности, текст, смысл, акцент

- Поверхности: `--bg` → `--surface` → `--surface-2` → `--surface-3`; границы `--border-soft`,
  `--border`, `--border-strong`.
- Текст от яркого к тусклому: `--ink-strong`, `--ink`, `--ink-body`, `--ink-soft`, `--ink-muted`,
  `--ink-faint`, `--ink-faintest`, `--ink-dim`, `--ink-ghost` (неактивный).
- Смысл: `--ok` / `--ok-soft` / `--ok-ink`, `--warn` / `--warn-strong` / `--warn-ink`,
  `--danger` / `--danger-soft` / `--danger-ink`, `--info`. `*-ink` — для текста на тёмном фоне.
- Акцент интерфейса: `--accent` (индиго), `--accent-strong`, `--accent-ink`, `--accent-mute`,
  `--accent-soft` (фон); второй акцент для ссылок и инструментов — `--accent-alt`.
- Радиусы `--r-sm/md/lg/pill`, отступы `--sp-1…4`, шрифты `--font-sans`, `--font-mono`.

## Компоненты

| Класс | Где | Пример |
|---|---|---|
| `.ds-model` | Список агентов, карточки «Инфо», заголовок `get_worker_info` | `modelBadge(id)` |
| `.ds-model.ds-pill` | Карточки чата (`spawn_worker`, поиск) | `modelBadge(id, {pill: true})` |
| `.ds-model-dot` | Вкладки оркестраторов | `style="--ds-c: var(--model-opus)"` |
| `.ds-model-text` | Строки «Модель: …», аналитика, workflow-карточки | `style="--ds-c: …"` |
| `.ds-status[data-status]` | Бейдж статуса в списке агентов | `⚡ выполняется` |
| `.ds-status-dot[data-status]` | Точка статуса без подписи | `●` |
| `.ds-chip[data-tone]` | Нейтральные метки; `ok`, `warn`, `danger`, `accent` | `<span class="ds-chip" data-tone="ok">` |
| `.ds-btn`, `-primary`, `-danger`, `-ghost` | Новые кнопки | `<button class="ds-btn ds-btn-primary">` |
| `.ds-card`, `-title`, `-meta` | Новые карточки | |

Компонентам цвет передаётся через переменную `--ds-c`, а не классом на каждую модель:
незнакомая модель тогда тоже получает цвет (поставщика), а не пропадает.

## Когда что использовать

- **Пишешь название модели** → `modelBadge(id)` (DOM) или `modelBadgeHtml(id)` (строка HTML).
  Нужен только цвет для DOM → `modelColorVar(id)` (вернёт `var(--model-…)`).
- **Рисуешь в canvas, Chart.js или SVG-атрибуте** (`fill="…"`, `stroke="…"`) → `modelColor(id)`,
  `providerColor(p)`, `cssToken('--имя', запасной)`: туда `var()` не подставится, нужен
  вычисленный цвет.
- **Статус агента** → `_STATUS_ICON[status]` + `T(status)` + `.ds-status`; цвет текста —
  `statusColor(status)`.
- **Новый смысл цвета** → новый токен в `design-system.css` и строка здесь, потом использование.
- **Tailwind-классы в разметке** (`bg-slate-800`, `text-slate-500`) остаются: их шкала совпадает
  с токенами поверхностей и текста. Новые классы — пересобрать `bash scripts/build-tailwind.sh`.

## Что осталось на hex

Перевод в V-876 заменил hex, **точно равные** токену (`style.css` ≈200, встроенные стили JS ≈185,
страница входа), — значения не поменялись, поменялся источник. Остались:

- оттенки без токена (единичные `#c8d6e5`, `#0e1723` и т. п. в аналитике и графиках);
- цвета в объектах JS (`{color: '#a78bfa'}` у карточек инструментов чата) и в опциях Chart.js;
- блок `.voice-*` и код голосового ввода в `chat.js` (строки ~150–720) — их ведёт отдельная работа.

Их перевод — по мере правки соответствующих экранов: при касании блока — заменить hex токеном
или завести токен, если смысла нет в палитре.
