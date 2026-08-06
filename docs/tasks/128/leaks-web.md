# #128 — что нашлось в вебе и что из этого можно цитировать

Юзер сказал: «промпты сливали по-любому». Искали. Главный результат неожиданный:
**основной дизайн-блок сливать не понадобилось — OpenAI опубликовала его сама.**

Каждая находка ниже помечена по одному правилу: совпало с нашими байтами → источник годный;
не совпало → «НЕ ПОДТВЕРЖДЕНО», фактом не считается и в предложение по переносу не идёт.

---

## 1. ПОДТВЕРЖДЕНО. Официальная публикация OpenAI, не утечка

`https://developers.openai.com/api/docs/guides/frontend-prompt.md` — 7 410 Б, HTTP 200,
скачано 06.08.2026. Целиком лежит в `verbatim/07-openai-official-frontend-prompt.md`.

Сверка с байтами бинаря (`@openai/codex@0.146.0`, шаблон `gpt-5.5`), команда — в шапке того файла:

```
правил «- » в официальном доке : 24
правил «- » в моём извлечении   : 24
совпало дословно                : 21
расходятся                      : 3 — только редактурой (двойной пробел, «as it leads to»
                                  → «because overlap can lead to», перестроенная фраза про workflows)
```

**Что это меняет:** цитировать 21 правило можно из публичного дока вендора, а не из
дизассемблированного бинаря. Это снимает вопрос о правомерности цитирования целиком.

## 2. ПОДТВЕРЖДЕНО. Тот же текст в репозитории утечек — ценна только обвязка

`https://github.com/asgeirtj/system_prompts_leaks/blob/main/OpenAI/Codex/gpt-5.5.md` (19 766 Б),
дубль в `codex-full.md`. Совпадает построчно с п.1. Единственное, чего нет в публичном доке:

```
You are Codex, a coding agent based on GPT-5. You and the user share one workspace,
and your job is to collaborate with them until their goal is genuinely handled.

{{ personality }}
```

То есть `{{ personality }}` — реальный плейсхолдер шаблона; в `old/gpt-5.2-codex.md:9` он
описан явно как «Body source: instructions_template (with `{{ personality }}` placeholder —
pluggable)». Это подтверждает нашу же механику извлечения: мы читали именно `instructions_template`.

## 3. ПОДТВЕРЖДЕНО. Старая редакция того же блока — и она противоречит новой

Официально: `https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide`,
раздел `# Frontend tasks`. В утечках — одинаково дословно в семи файлах
(`gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex-spark`, `codex-auto-review`, `old/gpt-5.3-codex`,
`old/gpt-5.2-codex`, `old/gpt-5.1-codex-max`). Наш экземпляр — `verbatim/02-gpt-5.4-frontend-tasks.md`.

Проверяемый факт: слова `slop` нет ни в `gpt-5.5.md`, ни в официальном `frontend-prompt.md`
(`grep -c slop` = 0 на скачанном файле, проверено в этой сессии). Блок не дополнен — он **заменён**.

| | ≤ 5.4 (старое) | 5.5 (новое) |
|---|---|---|
| фон | «use gradients, shapes, or subtle patterns to build atmosphere» | «You do not add discrete orbs, gradient orbs, or bokeh blobs» |
| hero | — | «never use a gradient/SVG hero page» |
| шрифты | «avoid default stacks (Inter, Roboto, Arial, system)» | ни слова про семьи; «letter spacing must be 0» |
| тон | «bold, and a bit surprising» | «quiet, utilitarian, and work-focused» (для SaaS/CRM) |

**Это важно для нас практически.** Наш скилл собран из ОБОИХ поколений сразу: запрет
градиентных пятен — из 5.5, а «меняй шрифтовую пару, композицию» — по духу из 5.4.
При этом жёсткое «системные шрифты, без веб-шрифтов» — наше собственное, и оно прямо
противоположно единственному правилу OpenAI про типографику.

## 4. НЕ ПОДТВЕРЖДЕНО. ChatGPT Canvas (`canmore`), ~2024

`https://github.com/asgeirtj/system_prompts_leaks/blob/main/OpenAI/Old/tool-canvas-canmore.md`
(2 888 Б; копии — `edoardoavenia/chatgpt-system-prompts/canmore.md`, датасет Nymbo на HuggingFace
со снимком «ChatGPT-4o with Canvas 10.03.2024»).

Пересечений с нашими якорями — ноль. Другой продукт, другой год. Приводится как контекст,
фактом о Codex не считается. Дословно, весь визуальный кусок:

> - Varied font sizes (eg., xl for headlines, base for text).
> - Framer Motion for animations.
> - Grid-based layouts to avoid clutter.
> - 2xl rounded corners, soft shadows for cards/buttons.
> - Adequate padding (at least p-2).
> - Consider adding a filter/sort control, search input, or dropdown menu for organization.

Отметить стоит одно: canvas требует `2xl rounded corners` и `soft shadows`, а Codex 5.5 —
`Cards are kept at 8px border radius or less`. Прямой конфликт между двумя продуктами
одного вендора. Ещё одно основание не собирать скилл из разных поколений чужих промптов.

## 5. Отрицательные результаты (тоже результат)

- `codex-inline-vis` — 0 хитов в вебе и 0 в клоне `system_prompts_leaks` (17 МБ, все вендоры).
- `Agent-facing contract; keep in sync with SKILL.md` — 0 хитов там же.
  Значит серверный `SKILL.md` из Находки 5 (#119) публично не всплывал, и наш вывод «его нет
  в доступе» держится.
- `OpenAI/Codex/gpt-5.6-sol.md` в утечках frontend-секции **не содержит вовсе**
  (`grep -iE "frontend|design|palette|orbs|slop"` = 0) — независимое подтверждение находки #119:
  наши Sol-воркеры дизайн-правил не получают.
- Отдельного публичного «ChatGPT artifacts HTML design prompt» (аналога Claude artifacts)
  у OpenAI нет — эту роль занимает canvas из п.4.

## 6. Побочно, но полезно как точка сравнения

`system_prompts_leaks/Anthropic/claude-design.md:214`:

> **Avoid AI slop tropes:** incl. but not limited to aggressive gradient backgrounds,
> emoji (unless explicitly part of the brand), …

Anthropic и OpenAI-5.5 сошлись на запрете градиентных фонов и эмодзи — то же, что стоит
в наших антипаттернах. Это не источник для переноса, но показывает, что наш запретительный
слой совпадает с обоими вендорами. Отличается не он, а то, что у них есть СВЕРХ него.
