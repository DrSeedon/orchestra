# #85 — Self-improvement без внешнего detection pipeline: A vs B

> Аналитика + рекомендация. НЕ эксперимент. Контекст: юзеру не понравился regex-gate + Haiku-классификатор
> как отдельная обвязка (см. эксперимент #85 — `docs/experiments/85/report.md`). Хочет, чтобы агент
> САМ замечал коррекции и предлагал правила.

## TL;DR
**Рекомендация: A→B поэтапно, начать с A (prompt-only).** Так делают все: Anthropic (Auto memory),
Windsurf (Cascade memories), Cursor (Memories), claude-reflect, OpenClaw skills. Промпт-инстинкт
«заметил коррекцию → предложи правило» ставится за 0 кода и сразу даёт сигнал, надёжен ли он на
наших данных. **Tool (B) добавляется только когда A докажет, что агент реально замечает коррекции**
— B решает проблему структуры и approval, но НЕ проблему «заметит ли вообще».

Ключевой факт из наших логов (проверено): **все 14 настоящих коррекций пришли через 1–8 строк после
вывода агента, в той же сессии.** То есть коррекция почти всегда в контексте агента → A технически
реализуем (агент видит, что его поправили). Это снимает главный риск варианта A.

---

## Prior Art — как делают другие (реальные механизмы, не теория)

Изучено через web research (источники внизу). **Сходимость поражает: все пришли к одному паттерну —
два слоя: «auto working-memory» (агент пишет сам) → «durable rules» (юзер ревьюит и промоутит).**

### Anthropic — Claude Code Auto memory + Dreaming (самый авторитетный пример)
- **Механизм: НЕ хук, НЕ tool. Промпт/agent-decided.** Агент сам решает, что сохранить, на основе
  «будет ли это полезно в будущей сессии». Пишет в plain markdown `~/.claude/projects/<proj>/memory/MEMORY.md`.
- **Нет approval-степа** при записи — агент пишет молча, юзер ревьюит постфактум через `/memory`.
- **Два слоя:** `CLAUDE.md` (юзер пишет, rules) vs Auto memory (Claude пишет, learnings). Оба грузятся
  в контекст каждой сессии (Auto memory — первые 200 строк / 25KB).
- **Критичное признание из их же доков:** *«Claude treats them as context, not enforced configuration…
  there's no guarantee of strict compliance, especially for vague or conflicting instructions.»*
  → Промпт-память **не гарантирует** исполнение. Для жёсткого enforcement они рекомендуют **hook**, не промпт.
- **Триггеры записи (из доков):** «Claude makes the same mistake a second time», «You type the same
  correction you typed last session». Т.е. сигнал — повтор коррекции, не одиночная.
- **Dreaming (research preview, май 2026):** scheduled-процесс ревьюит до 100 прошлых сессий, извлекает
  паттерны, мёржит дубли, удаляет устаревшее, пишет «playbooks». **НЕ меняет веса** — чисто memory curation.

### claude-reflect (BayramAnnakov) — ближайший аналог к нашей задаче
- **Механизм: hook + regex → manual `/reflect` review.** Ровно то, что юзер отверг как «обвязку», но
  посмотрим на их выводы:
- `capture_learning.py` — хук на каждый промпт, ловит regex-паттерны (`"no, use X"`, `"don't use Y"`,
  `"actually…"`, `"remember:"`) → кладёт в очередь.
- **AI semantic validation НЕ на лету, а на `/reflect`** — фильтрует false-positives из regex,
  ставит confidence 0.60–0.95. **Это в точности наш двухступенчатый вывод из эксперимента #85.**
- **Approval обязателен:** юзер на `/reflect` видит таблицу → Apply / Edit / Skip → синк в CLAUDE.md.
- **Явно фильтруют:** questions, one-time instructions, context-specific requests, vague feedback.
  ← Те самые категории, на которых наш Haiku галлюцинировал в #85.

### Windsurf — Cascade Memories
- **Механизм: агент авто-генерит memory во время диалога** («if it encounters context it believes is
  useful»), плюс manual «create a memory of …». **Не хук** — agent-decided, как у Anthropic.
- Memories **workspace-scoped**, retrieved by relevance (не грузятся все подряд). **Не жрут кредиты.**
- **Корректировки — explicit use-case:** *«we tried that approach and it broke X, do not propose it again.»*
- **Lifecycle: memory (working notepad) → promote в `.windsurfrules` (durable, team-shared).** Тот же два-слоя.
- Maintenance-проблема честно названа: memories копятся, часть устаревает/противоречит — нужна чистка.

### Cursor — Memories / Automations
- Memories персистят контекст между сессиями; Automations имеют memory-tool, «agents learn from past runs».
- Bugbot «learns from PR feedback over time» (~80% issues resolved).
- **Авто-генерация rules из фидбэка — заявлена как emerging trend, НЕ shipped.** Т.е. даже Cursor пока
  не доверяет полностью автоматическому извлечению правил. Сегодня — персистентная память + ручные rules.

### Devin (Cognition) — Knowledge Base + Playbooks
- **Knowledge items с явными триггерами** + Playbooks (reusable workflows из успешных сессий).
- **Кодификация фидбэка — ручная и рекомендуемая:** «pick three things your team always corrects in code
  review, write one knowledge item for each». Не авто-извлечение — человек пишет.
- **Review feedback loop:** Devin отвечает на PR-комменты, Autofix чинит флагнутые баги.
- Session analysis: «understand why a session succeeded/failed, extract learnings, dedup knowledge».
  ← Аналог Dreaming, но по запросу.

### OpenClaw self-improving-agent skills (open-source, peterskoett/hiveminderbot/leohuang8688)
- **Механизм: skill + prompt-injection + опциональные хуки.** `.learnings/` директория с
  `LEARNINGS.md` / `ERRORS.md` / `FEATURE_REQUESTS.md`.
- Структурированные записи: priority, status, area, summary, suggested action.
- **Триггеры:** «command fails unexpectedly» ИЛИ «user corrects the agent».
- **Хуки opt-in**, не форсятся (UserPromptSubmit / PostToolUse в `.claude/settings.json`).
- Safety-принцип: never overwrite, no secrets, короткие summary вместо raw-логов.

### Сводка паттернов prior art
| Продукт | Detection | Запись | Approval | Durable-слой |
|---------|-----------|--------|----------|--------------|
| Claude Auto memory | agent-decided (prompt) | авто, молча | постфактум `/memory` | CLAUDE.md (ручной промоут) |
| claude-reflect | **hook+regex → AI на review** | очередь | **обязателен `/reflect`** | CLAUDE.md |
| Windsurf | agent-decided | авто | постфактум | `.windsurfrules` промоут |
| Cursor | agent-decided + automations | авто | — | ручные rules (авто = trend) |
| Devin | ручная кодификация + PR loop | ручная | по сути review | Knowledge Base |
| OpenClaw skills | prompt + opt-in hooks | авто в `.learnings/` | зависит | промоут в memory |

**Три вывода для нас:**
1. **Никто не доверяет полностью авто-извлечению.** Все ставят human-review между «агент предложил» и
   «правило в durable-памяти». Вариант B с approve-workflow — мейнстрим, не оверинжиниринг.
2. **Detection — почти всегда agent-decided через промпт, а не отдельный pipeline.** Это ровно вариант A.
   Юзер интуитивно прав: индустрия ушла от внешних детекторов к «агент сам замечает».
3. **Confidence/auto-извлечение без ревью — то, что даже Cursor называет «ещё не готово».** Совпадает
   с нашим #85 (confidence бесполезен как фильтр, 53% мусора без ревью).

---

## Анализ вариантов

### Критерий 1 — Reliability (реально ли агент будет это делать)

**Вариант A (prompt-only):**
- ⚠️ **Главный риск — агент забьёт/забудет.** Подтверждено первоисточником: Anthropic прямо пишет про
  свою же Auto memory — *«no guarantee of strict compliance»*. Промпт = контекст, не enforcement.
- ✅ **НО технически возможно:** наши логи показывают, что коррекция приходит через 1–8 строк после
  вывода агента (gap проверен на 14 настоящих коррекциях) — агент **видит** её в активном контексте.
  Это не случай «коррекция в новой сессии, агент не в курсе».
- ⚠️ **Деградация в длинном turn:** если между выводом и коррекцией куча tool_calls (gap=8 был у
  оркестратора), инструкция «предложи правило» конкурирует с основной задачей и проигрывает.
- ⚠️ **Шумность канала:** из #85 — в одном TG-канале мешаются коррекции, задачи, DONE-репорты, вставки
  UI. Агент в варианте A сам должен отличить «меня поправили» от «мне дали новую задачу». Haiku в #85
  это НЕ умел (0/12 null на не-коррекциях). Оркестратор Opus, вероятно, лучше, но не проверено.

**Вариант B (MCP tool):**
- ✅ **Tool в списке = постоянное напоминание.** Tool-в-промпте надёжнее инструкции-в-промпте: агент
  видит `propose_improvement` в доступных тулах каждый turn. Но это **не гарантия вызова** — агент всё
  равно решает сам, когда дёрнуть (та же проблема agent-decided).
- ✅ **Approval-workflow убирает риск мусора:** даже если агент предложит чушь из не-коррекции (как в
  #85), юзер reject'ит — в durable-память попадёт только одобренное. **B защищает от слабого detection.**
- ⚠️ **B не чинит «заметит ли вообще»** — если агент не распознал коррекцию, он не вызовет tool. Detection
  остаётся agent-decided в обоих вариантах.

**Вывод по reliability:** A и B имеют **одинаковый detection-риск** (оба agent-decided). B добавляет
только защиту на этапе записи (approval). Значит — сначала проверяем detection дёшево через A.

### Критерий 2 — Cost
- **A:** 0 кода, 0 дополнительных вызовов, 0 токенов сверх ~5 строк промпта. Бесплатно.
- **B:** ~50 строк MCP + ~20 строк промпт (разовый код). Рантайм: tool-определение в контексте каждого
  агента (~100–200 токенов/сессия) + inject-сообщение при вызове. Дёшево, но не ноль.
- Prior art: Windsurf/Anthropic auto-память **не жрёт кредиты** — потому что это промпт, а не вызов.
  B ближе к этому, чем отвергнутый Haiku-классификатор (тот был +1 LLM-вызов на сообщение).

### Критерий 3 — UX
- **A:** агент пишет правило текстом в чат → **юзер должен руками скопировать в CLAUDE.md/memory.**
  Трение. Легко проигнорировать. Нет single source of truth.
- **B:** структурированное предложение в том же чате → approve/reject (текст или кнопка) → **авто-patch
  в файл.** Резко меньше трения. Юзер не покидает диалог. Это UX-преимущество — главная причина для B.
- Prior art подтверждает: claude-reflect/Devin специально строят review-UI (таблица Apply/Edit/Skip),
  потому что «агент написал в чат, скопируй сам» не масштабируется.

### Критерий 4 — Complexity
- **A:** тривиально. Риск — раздувание промпта (ещё одно «обязательно сделай X», которых уже много →
  context rot, агент игнорит). Anthropic советует <200 строк промпта для adherence.
- **B:** умеренно. MCP tool, inject-механизм (у нас уже есть — `send_message` инжектит mid-turn),
  patch-в-файл с safety (never overwrite, append, no secrets — из OpenClaw best practices). Approval-
  state. Всё это в Orchestra **уже частично есть** (inbox, inject, file-patch паттерны).

---

## Можно ли A→B поэтапно? — Да, и это рекомендуемый путь

**Фаза A (сейчас, 0 кода):** вшить в промпт оркестратора/воркера блок:
```
Если юзер тебя поправил (сказал «нет, не так», «переделай», переформулировал уже выданную задачу,
раскритиковал твой вывод) — В КОНЦЕ ответа предложи ОДНО правило на будущее в формате:
📝 ПРАВИЛО: Когда <X> → делай <Y>, не <Z>.
Только если это обобщаемо. Разовую мелочь — не предлагай. Не выдумывай правило, если тебя не правили.
```
Замеряем неделю: **как часто агент реально предлагает правило на реальной коррекции? как часто
галлюцинирует на не-коррекции?** Это бесплатный сбор данных по главному риску (detection).

**Решение о Фазе B (после A):**
- Если A показывает, что **агент стабильно замечает коррекции** (предлагает на ≥70% реальных, мусорит
  редко) → строим B: оборачиваем уже работающий промпт-сигнал в `propose_improvement` для структуры +
  approval + авто-patch. Detection уже доказан, B добавляет только «трубопровод».
- Если A показывает, что **агент часто забивает или мусорит** → B сам по себе не спасёт (detection-то
  тот же agent-decided). Тогда — либо усиливать промпт-сигнал, либо вернуться к идее лёгкого regex-
  префильтра (но уже зная из #85, что чистый regex даёт 0.42 precision).

**Почему именно так:** A и B делят один detection-механизм. Бессмысленно писать 70 строк кода под B,
не зная, работает ли detection. A отвечает на этот вопрос за 5 строк промпта и ноль денег. Это
ровно «pit of success» — сначала дешёвый сигнал, потом инвестиция.

---

## Рекомендация (чёткая)

### ✅ A→B поэтапно. Начать с A немедленно.

1. **Сейчас:** Вариант A — промпт-блок «заметил коррекцию → предложи правило текстом». 0 кода, 0 cost.
   Цель — не само обучение, а **измерить detection-надёжность агента на живых данных** (тот же вопрос,
   что прайс-арт ставит во главу угла).
2. **Через ~неделю работы A:** оценить — агент замечает коррекции и предлагает вменяемые правила?
   - **Да** → строить B (`propose_improvement` tool + approval + patch). У нас уже есть inject/inbox/
     file-patch — кода реально ~50–70 строк. B даёт структуру и убирает UX-трение «скопируй сам».
   - **Нет/редко** → не лить код в B; диагностировать, почему агент не замечает (промпт-конкуренция?
     шум канала?), чинить detection до того как автоматизировать запись.

### Чего НЕ делать
- ❌ Сразу прыгать в B без фазы A — рискуешь построить approval-pipeline для detection, которого нет.
- ❌ Возвращаться к отдельному Haiku-классификатору на каждое сообщение (отвергнут юзером + #85 показал,
  что он галлюцинирует без ревью; индустрия тоже не доверяет авто-извлечению без human-review).
- ❌ Авто-патчить в durable-память без approve — НИКТО из prior art так не делает (Anthropic пишет в
  отдельный auto-слой, не в CLAUDE.md; промоут в rules — всегда через человека).

### Дизайн-нюансы для будущего B (из prior art, бесплатные уроки)
- **Два слоя, как у всех:** предложение → auto-память воркера (`docs/workers/{name}.md`, у нас уже есть!)
  → промоут в `project_claude` только по явному approve. Не патчить CLAUDE.md напрямую.
- **Approval обязателен** (claude-reflect/Devin/Windsurf — все через ревью).
- **Confidence не использовать как авто-фильтр** (#85 + Cursor «ещё не готово»).
- **Safety:** never overwrite, append-only, no secrets (OpenClaw best practice).
- **Дедуп/чистка позже** (аналог Dreaming) — когда правил накопится, а не в MVP.

---

## Sources
- [Claude Code memory docs (Auto memory, Dreaming)](https://code.claude.com/docs/en/memory)
- [claude-reflect (hook+regex → /reflect review)](https://github.com/BayramAnnakov/claude-reflect)
- [Windsurf Cascade Memories](https://docs.windsurf.com/windsurf/cascade/memories)
- [Cursor 2026 memory/automations overview](https://dev.to/pockit_tools/mastering-cursor-rules-the-ultimate-guide-to-cursorrules-and-memory-bank-for-10x-developer-alm)
- [Devin Knowledge Base & Playbooks](https://docs.devin.ai/work-with-devin/advanced-capabilities)
- [Devin 2025 performance review (review feedback loop)](https://cognition.ai/blog/devin-annual-performance-review-2025)
- [OpenClaw self-improving-agent skill](https://github.com/openclaw/skills/blob/main/skills/pskoett/self-improving-agent/SKILL.md)
- [peterskoett/self-improving-agent (.learnings/)](https://github.com/peterskoett/self-improving-agent)
- Internal: experiment #85 (`docs/experiments/85/report.md`) — regex gate 0.42 precision, Haiku 100% on
  genuine corrections, confidence useless as filter, corrections appear at gap=1–8 rows in context.
