# app.js Decomposition — Research

**Дата:** 2026-06-01 · research-only · файл `app/static/js/app.js` (5284 строки, 122 функции)

## TL;DR
Монолит 5284 строки, classic `<script>` (0 import/export), грузится одним тегом после vendor-либ. **Сборщик НЕ нужен** — нативные ES modules (`<script type="module">`) работают в браузере, вендоры (marked/DOMPurify/hljs/diff_match_patch) остаются глобалами на `window`. Главная сложность — **~37 глобальных переменных как session-backbone** (currentScope, selectedAgent, chatLogs, eventSource, streamBubble...). Effort честно: **8-12 рабочих дней** при риске сломать рабочий UI. **Рекомендация: НЕ делать перед OSS-лончем. Сделать Phase 1 (leaf-модули, ~1 день, низкий риск) если очень хочется чистоты, остальное — после лонча.**

---

## 1. Карта модулей (имя → строки → функции → зависимости)

| Модуль | Строки | Funcs | Пишет глобалы | Связность | Сложность |
|---|---|---|---|---|---|
| **api.js** | 4391-4399 | 1 | — | НЕТ | ⭐ leaf |
| **tool-renderers.js** (Grep/WebSearch/Diff) | 3717-4118 | 10 | — (чистые DOM-билдеры) | НЕТ | ⭐ leaf |
| **usage.js** (бар + спарклайны) | 4400-4709 | 10 | `_usageData,_sparkData,...` | низкая | лёгкий |
| **modal.js** (+ models + dropdowns) | 309-670 | 18 | `_pipelineRoles` | низкая | лёгкий |
| **tasks.js** | 4764-4960 | 7 | `_tasksTabActive,_taskCollapsed` | низкая (читает currentScope) | лёгкий |
| **jobs.js** | 4961-5284 | 10 | `_jobsTabActive,...` | низкая | лёгкий |
| **reboot.js** (overlay) | 4710-4763 | 5 | `_rebootOverlay,_rebootFails` | низкая | лёгкий |
| **files.js** (файл-браузер) | 4119-4333 | 10 | `pastedImages` | средняя (currentScope, pastedImages) | средний |
| **utils.js** (marked-хуки, autolink) | 1-308 | 8 | `drafts` | низкая | лёгкий |
| **agent-list.js** (рендер сайдбара) | 1238-1384 | 2 | — | низкая (read-only глоб.) | лёгкий |
| **agent-select.js** | 1045-1237 | 7 | `selectedAgent,streamBubble,...` | ВЫСОКАЯ (сетит 6+ глоб.) | трудный |
| **orchestrator-picker.js** | 671-1044 | 16 | `currentScope,selectedAgent,orchData,_pipelineRoles` | ВЫСОКАЯ | трудный |
| **sse.js** (SSE-хендлер) | 210-247 | 1 | `eventSource,localMessages,chatLogs[*]` | ВЫСОКАЯ | трудный |
| **chat-pending.js** (send/optimistic UI) | 1386-1442 | 4 | `pendingUserMsgs,pendingBubble,...` | средняя | средний |
| **chat-render.js** (`addChatEntry`) | 1863-3163 | 1 ГИГАНТ | `streamBubble,streamContent,scrollAfterLoad` | ОЧЕНЬ ВЫСОКАЯ (читает 12+ глоб.) | ⛔ самый трудный |

## 2. Глобалы по тирам связности (главный вызов декомпозиции)

**TIER 1 — session-backbone (тяжелее всего вынести):**
`currentScope`, `selectedAgent`, `chatLogs[*]`, `eventSource`, `streamBubble`, `streamContent`. Один писатель на каждый, но читаются ПОВСЮДУ. Это ядро состояния сессии — при выносе в модули нужен **общий state-контейнер** (один модуль `state.js` экспортирует объект/геттеры), иначе модули не увидят общий `selectedAgent`.

**TIER 2 — средние:** `pendingBubble`, `pastedImages`, `contextCache`, `agentColors`, `_pipelineRoles`, `orchData`.

**TIER 3 — лёгкие (self-contained):** `_tasksTabActive`, `_jobsTabActive`, таймеры, `_usageData`, `_sparkData`, `drafts`, `_taskCollapsed`. Каждый живёт в своей панели.

## 3. Точка входа / связность
- Грузится в `dashboard.html:214` `<script src="/static/js/app.js">` ПОСЛЕ вендоров (marked, purify, diff_match_patch, highlight).
- Старт: `DOMContentLoaded` → ~25 listener'ов + init (loadModels, loadProfilesDropdown, initFilePanel, initUsageBar, initHeartbeat).
- `window.*` экспортов почти нет: `window.compactMode` + onclick-хендлеры (`switchLeftTab`). HTML-разметка дёргает несколько функций по onclick — при модуляризации их надо явно вешать на `window` или перейти на addEventListener.
- **Hot path связности:** `selectOrchestrator → connectSSE → SSE-loop → addChatEntry` (8+ мутаций глобалов). Это нельзя разрезать наивно.

## 4. addChatEntry — отдельная проблема
Одна функция 1863-3163 (~1300 строк) с инлайновым if/else диспетчером по типу события (user_message, text, stream, status, tool, tool_result, subagent_*, image, +15 типов tool-рендеров). **Это не "вынести в файл" — это рефакторинг**: разбить на (а) чистые tool-рендеры в реестр `{toolName: renderFn}` + (б) тонкую обёртку-вставку в DOM. Самая дорогая и рискованная часть.

---

## 5. Bundler или ES modules?
**ES modules без сборщика.** Обоснование:
- Вендоры уже глобалы на `window` (DOMPurify ×57, marked ×26, hljs, diff_match_patch) — модулям не нужен import для них, берут с `window`.
- Build-тулинга в проекте НЕТ (нет package.json/vite/webpack), статика отдаётся напрямую `StaticFiles`. Добавлять webpack/vite = новая инфра, watch, CI, билд-шаг — против "плоско, минимум абстракций".
- Нативный путь: `<script type="module" src="/static/js/main.js">`, main.js делает `import {...} from './chat-render.js'`. Браузер сам тянет (HTTP/2 multiplexing, dev — норм; для prod опц. позже добавить минификацию, но не обязательно для ~10 юзеров).
- ⚠️ Один нюанс: модули грузятся async/defer по умолчанию — порядок init надо явно контролировать через import-граф, а не порядок `<script>`. Для onclick-хендлеров в HTML — вешать на `window` в main.js или переписать на addEventListener.

## 6. Effort
| Фаза | Модули | Время | Риск |
|---|---|---|---|
| 1 | api, tool-renderers, usage, modal, tasks, jobs, reboot, utils | ~1-1.5 дня | НИЗКИЙ |
| 2 | files, agent-list, chat-pending | ~2 дня | СРЕДНИЙ |
| 3 | state.js контейнер + agent-select + orchestrator-picker + sse | ~3 дня | ВЫСОКИЙ |
| 4 | addChatEntry → реестр рендеров + обёртка (рефакторинг) | ~3-4 дня | ОЧЕНЬ ВЫСОКИЙ |
| — | интеграция, ручное тестирование всего UI | ~2 дня | ВЫСОКИЙ |
| **Итого** | ~14 модулей | **8-12 раб. дней** | средний→высокий |

Нет тестов на фронт (UI/CSS — вне TDD), значит вся верификация = ручной прогон всех панелей. Это и есть главный риск: легко тихо сломать SSE-стриминг или tool-рендер, и заметить только глазами.

---

## 7. Рекомендация: НЕ делать перед OSS-лончем (или только Phase 1)

**Почему не сейчас:**
- Монолит **работает**. Декомпозиция — чистый рефакторинг без новой функциональности для юзера. "Не рефакторь то, что не сломано" перед лончем.
- Высокий риск тихих регрессий в SSE/чате (нет автотестов фронта) — ровно перед моментом, когда нужна стабильность для первых OSS-пользователей.
- 8-12 дней — большой кусок, который не двигает лонч.
- Для OSS-восприятия "один app.js на 5к строк" — да, выглядит монолитно, но это НЕ блокер контрибьюшена: файл размечен секциями, читаем. Многие успешные OSS-проекты стартовали с монолита.

**Что МОЖНО сделать дёшево, если хочется чистоты к лончу (Phase 1 only, ~1 день, низкий риск):**
Вынести только leaf/pure-модули, которые НЕ трогают session-backbone:
`api.js`, `tool-renderers.js`, `usage.js`, `reboot.js`, `utils.js`. Это снимет ~1200 строк из монолита (5284 → ~4000) без касания опасных глобалов. main.js остаётся с core-логикой (чат, SSE, агенты). Низкий риск, заметное улучшение читаемости.

**Когда делать полную декомпозицию:** ПОСЛЕ лонча, когда (а) появятся реальные контрибьюторы, которым мешает монолит, (б) будет время на ручное регресс-тестирование, (в) возможно появится smoke-тест фронта (Playwright) чтобы ловить регрессии. Тогда Phase 2-4 по порядку.

**Что НЕ делать никогда здесь:** не тащить webpack/vite ради этого. ES modules нативно достаточно.

---

## Приоритет порядка (если решат делать полностью)
1. Phase 1 leaf-модули (безопасно в любой момент)
2. `state.js` — контейнер для TIER-1 глобалов (фундамент, без него остальное не разрезать)
3. Панели (files, tasks, jobs, agent-list) — читают state, не пишут backbone
4. agent-select + orchestrator-picker — пишут backbone через state.js API
5. sse.js — отдельный модуль, эмитит события
6. chat-render (addChatEntry) — последним, как рефакторинг в реестр рендеров

Ключевой инсайт: **сначала state.js, потом всё остальное**. Без центрального контейнера состояния вынос TIER-1 глобалов превратится в циклические import'ы.
