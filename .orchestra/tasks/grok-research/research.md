# Research: Grok 4.5 + Grok CLI — стоит ли интегрировать в Orchestra?

**Дата:** 2026-07-11
**Автор:** research-grok (full-cycle Phase 1)
**Статус:** RESEARCH DONE — awaiting approval

---

## Question (Step 0)

- **Контекст:** Orchestra — AI-оркестратор (Python/FastAPI/Claude SDK/MCP), работает **из РФ через прокси**. Уже интегрирован Codex CLI (GPT-5.6 Sol) для cross-LLM review через MCP tool `codex_review`.
- **Change under test:** Добавить Grok 4.5 (через Grok Build CLI / API) как ещё один cross-LLM инструмент — либо review-tool (аналог `codex_review`), либо backend для воркеров, либо executor (Grok кодит, Claude ревьюит).
- **Baseline:** Существующая интеграция Codex CLI (Sol $5/$30, Terra $2.50/$15).
- **Measurable outcome:** Качество кодинга Grok (SWE-bench Pro и др.), цена API, **доступность из РФ**, стоимость интеграции vs добавленная ценность поверх Codex.

## Hypotheses considered (Step 1)

- **H1** — Grok 4.5 конкурентен в кодинге → стоит добавить как *третье мнение* рядом с Codex.
  *Falsifier:* бенчмарки ниже Sonnet 5 / GPT-5.6, ИЛИ нет CLI/subprocess-пути, ИЛИ недоступен из РФ.
- **H2** — Grok мало что добавляет поверх Codex (избыточен, доп. сложность, RF-блок) → не стоит.
  *Falsifier:* заметно дешевле/лучше ИЛИ уникально доступен.
- **H3** (tail) — Grok нельзя использовать напрямую из-за санкций, но *паттерн* fable-advisor (architect→lanes) ценен сам по себе для Orchestra, независимо от Grok.

**Итог по гипотезам:** H2 подтверждается ключевым блокером (RF/OFAC). H1 частично верна по качеству, но разбивается о доступность. **H3 — самый ценный вывод:** паттерн полезен, конкретно Grok — нет.

---

## Findings (атомарные утверждения с источниками)

### 1. Grok 4.5 — что это, когда вышел
- **CONFIRMED** — Grok 4.5 выпущен **8 июля 2026** (public rollout 9 июля), построен на 1.5T V9 foundation model, co-trained с Cursor (xAI/SpaceX купили Cursor за ~$60B в июне 2026). [1][2][3]
  *Тир: multi-secondary (TechCrunch + x.ai news + несколько блогов), согласованно.*
- **CONFIRMED** — Позиционируется Маском как "Opus-class model, но быстрее, токен-эффективнее и дешевле". [1][3]
- **LIKELY** — 1M+ context window "coming soon" (анонс, не релиз на 2026-07-11); на данный момент Grok Build — 256K контекст. [3][4]
  *Тир: single primary (анонс Маска), не зарелижено → LIKELY.*

### 2. Grok CLI — есть, subprocess-friendly
- **CONFIRMED** — "Grok Build" = официальный CLI-агент от xAI. Установка: `curl -fsSL https://x.ai/cli/install.sh | bash`. Auth: browser ИЛИ `export XAI_API_KEY="xai-..."`. [4][5]
- **CONFIRMED** — **Headless mode `grok -p "..."`** + `--output-format streaming-json` → вызывается из subprocess/скриптов. Есть ACP (Agent Client Protocol) для orchestration-аппов. Модель через `-m`, кастом-модели в `~/.grok/config.toml`. [5]
  *Тир: primary (docs.x.ai). Это ровно та механика, что у Codex CLI — subprocess wrapper реалистичен.*
- **CONFIRMED** — Grok Build **распознаёт CLAUDE.md и AGENTS.md без изменений**, понимает Anthropic skill-формат, подхватывает уже настроенные MCP-серверы. Миграция с Claude Code почти бесшовная. [5]
- **NB** — есть ещё community `superagent-ai/grok-cli` (open-source, TypeScript/Bun, не аффилирован с xAI). [community repo]

### 3. Pricing
- **CONFIRMED** — Grok 4.5 API: **$2/M input, $6/M output, $0.50/M cached input**. Server-side tools (web/X search, code exec) биллятся отдельно $5/1000 calls. Batch-скидки для 4.5 на старте НЕТ. [1][6][7]
- **CONFIRMED** — Free tier: **у API free tier'а нет** (billing с первого токена) по eesel AI; источники конфликтуют — AI Pricing Guru говорит про limited prototyping tier + периодические кредиты до $150/мес через data-sharing. **Проверять в консоли, не полагаться.** [6][7]
  *Counter-evidence: источники расходятся → confidence на "free tier" = UNCERTAIN.*
- **CONFIRMED** — Consumer: free / SuperGrok $30/мес / SuperGrok Heavy $300/мес (Grok Build доступен SuperGrok и X Premium+ подписчикам). [6]

**Pricing-таблица (API, per 1M tokens):**

| Модель | Input | Output | Cached in | Примечание |
|---|---|---|---|---|
| **Grok 4.5** | $2 | $6 | $0.50 | дешевле всех в своём тире [1][6] |
| GPT-5.6 Sol | $5 | $30 | — | наш текущий Codex [задачный контекст] |
| GPT-5.6 Terra | $2.50 | $15 | — | [задачный контекст] |
| Claude Sonnet 5 | $2→$3 | $10→$15 | — | intro до 31.08.2026, +42% токенов из-за нового токенайзера ≈ $2.84/$14.20 эффективно [8] |
| Claude Opus 4.8 | $5 | $25 | — | [проект] |
| Claude Fable 5 | $10 | $50 | — | [проект] |

Grok 4.5 — **самый дешёвый output** в тире ($6 против $15–30). Плюс 4.2× токен-эффективность на SWE-bench Pro (15 954 output-токенов против 67 020 у Opus 4.8). [1]

### 4. Качество кодинга — конкурентен, но не лидер
**SWE-bench Pro** (наименее контаминированный бенч, actively-maintained repos):

| Модель | SWE-bench Pro | Источник |
|---|---|---|
| Fable 5 | 80.3–80.4% | [лидер] [9] |
| Opus 4.8 | 69.2% | [9] |
| **Grok 4.5** | **64.7%** | [8][9] |
| Sonnet 5 | 63.2% | [8][9] |
| GPT-5.5 | 58.6% | [9] |

- **CONFIRMED** — Grok 4.5 ≈ Sonnet 5 на SWE-bench Pro (64.7 vs 63.2 — статистическая ничья). Подтверждено **двумя независимыми источниками** (aireiter + codingfleet/технекст-сводка). [8][9]
- **CONFIRMED** — Grok лидирует на **agentic/terminal** бенчах: Terminal Bench 2.1 83.3% vs Sonnet 76.1%; лидирует на SWE Marathon (long-horizon). [8][9]
- **LIKELY** — Grok слабее на "curated/reviewable" задачах: DeepSWE 1.1 — Grok 53% vs Opus 59% vs GPT-5.5 67% vs Fable 70%. [9]
- **UNCERTAIN** — прямое сравнение Grok 4.5 vs **GPT-5.6 Sol** (наш Codex) тонкое: релизы разошлись на ~день, большинство бенчей сравнивают с GPT-**5.5**. Один independent Rails-бенч: Grok 4.5 = 87/100 (Tier A), GPT-5.6 Sol = 92/100, Fable 5 ≈ 94. → **GPT-5.6 Sol немного выше Grok в этом тесте.** [9]
  *Тир: single independent benchmark → UNCERTAIN, но направление устойчивое.*

**Важная оговорка (counter-evidence на все бенчи):** большинство цифр vendor-reported, scaffold решает. Для Grok 4 xAI self-report 72–75% на SWE-bench Verified, независимый vals.ai (SWE-agent scaffold) — 58.6%. Разрыв огромный. SWE-bench Verified контаминирован (OpenAI отозвал в фев 2026). Поэтому опираюсь на **Pro**, не Verified. [9]

### 5. fable-advisor plugin — паттерн, который реально ценен
- **CONFIRMED** — `DannyMac180/fable-advisor` = Claude Code plugin, "architect pattern": **Fable 5 = judgment/specs/verification** (эмитит меньше всего токенов), делегирует имплементацию в дешёвые lanes:
  - **default lane: Grok 4.5** через Grok CLI — рутинный кодинг, когда спека полностью определяет вывод;
  - **optional lane: GPT-5.6 Sol** через Codex CLI — correctness-critical, "гонка" против Grok для сравнения;
  - **judgment: Fable 5** — архитектура, requirements, приёмка. [fable-advisor repo]
- **CONFIRMED** — Философия: "дорогая модель эмитит меньше всего токенов (judgment+specs), дешёвые lanes — больше всего (код)" → **~90% экономии токенов** vs всё на Fable. Cross-vendor review by default (разные семейства ловят разные слепые зоны). [fable-advisor repo]
- **Механизм:** Claude Code subagent routing (модель на агента через frontmatter), пятичастный spec-контракт для "context-free delegation". Требует: Claude Code ≥2.1.170 + Fable 5, `grok login` для Grok lane, Codex CLI для GPT lane. [fable-advisor repo]

**→ Это ровно та архитектура, к которой Orchestra уже близка** (Opus-оркестратор → воркеры). Ценность паттерна не зависит от Grok — lanes можно заполнить чем угодно доступным.

### 6. ⛔ БЛОКЕР: Grok недоступен из РФ (OFAC)
- **CONFIRMED** — **Grok API и app явно недоступны из РФ** из-за санкций США и OFAC-compliance (export controls). Не rollout-задержка, а **юридический hard-block** привязанный к export-control law. Официальный ответ Grok в X: "Grok app currently unavailable in the Russian Federation due to international sanctions... US export controls." [10][11]
  *Тир: primary (заявление самого xAI) + secondary (Grokipedia/press). CONFIRMED.*
- **CONFIRMED** — Grok 4.5 запущен в 47 странах, EU исключён (AI Act, до середины июля 2026). РФ — исключён по санкциям, отдельно от EU-кейса. [1][10]
- **Counter-nuance:** блок со стороны **xAI** (comply с US-санкциями), НЕ со стороны РФ-регулятора (РФ официально не блокирует иностранные LLM). Т.е. VPN/прокси из "supported country" технически обходит IP-фильтр — **но это нарушает ToS xAI и потенциально применимое право (sanctions bypass).** [10][11]
  *Это тот же класс проблемы, что был у Fable 5 (banned USA export-control 2026-06-15). Прямая аналогия в CLAUDE.md.*

---

## Confidence per finding (сводка)

| Finding | Confidence | Reason (tier) |
|---|---|---|
| Grok 4.5 вышел 08.07.2026, Cursor-trained | CONFIRMED | multi-secondary согласованно |
| Grok CLI headless subprocess-friendly | CONFIRMED | primary (docs.x.ai) |
| Pricing $2/$6/$0.50 | CONFIRMED | primary (pricing page) + multi-secondary |
| API free tier | UNCERTAIN | источники конфликтуют |
| Grok 4.5 ≈ Sonnet 5 (SWE Pro 64.7 vs 63.2) | CONFIRMED | 2 независимых источника |
| Grok < GPT-5.6 Sol в кодинге | UNCERTAIN→LIKELY | 1 independent bench, direction устойчив |
| fable-advisor architect-pattern | CONFIRMED | primary repo |
| **РФ-блок Grok (OFAC)** | **CONFIRMED** | primary (xAI statement) |

---

## Рекомендация

### ⛔ НЕ добавлять Grok как рабочий backend/executor в Orchestra. Причины (в порядке веса):

1. **RF/OFAC hard-block (killer).** Grok API недоступен из РФ по санкциям США. Обход через VPN/прокси из "supported country" = **нарушение ToS xAI + потенциально sanctions-law**. Orchestra и так живёт на прокси, но здесь прокси — не про блокировку РФ-регулятором (как с Anthropic), а про **обход US export controls**, что юридически иной и опаснее класс. Плюс аккаунт/ключ xAI на РФ-резидента — риск бана. Это тот же грабли, что с Fable 5 (export-control ban).

2. **Избыточность поверх Codex.** У нас уже есть GPT-5.6 Sol (Codex) как cross-LLM review. Grok 4.5 **не превосходит** GPT-5.6 Sol в кодинге (87 vs 92 на independent Rails-бенче; на SWE Pro сравнение с 5.6 тонкое). Второе мнение от Grok ≈ то же семейство ценности, что уже даёт Codex — маргинальный прирост diversity не оправдывает риск+сложность.

3. **Grok сильнее в скорости/цене, а не в качестве.** Его реальное преимущество — 4.2× токен-эффективность и дешёвый output. Но Orchestra на Max-подписке — доллары виртуальные, цена API нерелевантна (см. CLAUDE.md pricing policy). Мы оптимизируем КАЧЕСТВО, не стоимость. Значит главный плюс Grok для нас **обнуляется**.

### ✅ Что ЦЕННО и стоит забрать (H3):

**Паттерн fable-advisor "architect → lanes" — а не Grok.** Orchestra уже реализует его в зачатке (Opus-оркестратор эмитит judgment, воркеры эмитят код). Стоит:
- формализовать "cross-vendor review by default" — у нас это `codex_review` (Sol/Terra). Достаточно **одного** cross-vendor lane (Codex), второй (Grok) не нужен из-за (1).
- при желании расширить diversity — брать доступные из РФ модели (DeepSeek через прокси уже пробовали, Gemini), не Grok.

**Если РФ-блок когда-нибудь снимут / появится легальный путь** — Grok заходит тривиально: `grok -p` subprocess wrapper 1:1 как Codex, CLAUDE.md/MCP/skills распознаются из коробки. Интеграция — часы, не дни. Но не сейчас.

### Формат (если бы добавляли — на будущее):
- **cross-review tool** `grok_review` (аналог `codex_review`): bg-job `grok -p "review diff" --output-format streaming-json`, wrapper с `XAI_API_KEY`. Наименьший, изолированный.
- НЕ как основной executor воркеров (мы на Claude-подписке, зачем платить xAI per-token).

---

## Risks / ограничения

| Риск | Тяжесть | Комментарий |
|---|---|---|
| RF/OFAC блок API | 🔴 killer | обход = нарушение US-санкций + ToS, бан ключа/аккаунта |
| Per-token billing (нет подписки) | 🟡 | против нашей "только подписка, никаких API-ключей" policy (CLAUDE.md) |
| Избыточность vs Codex | 🟡 | маргинальный diversity-прирост |
| Free tier неясен | 🟢 | UNCERTAIN, проверять в консоли — но нерелевантно при (1) |
| 256K контекст (1M "soon") | 🟢 | меньше Claude 1M, но для review хватает |
| Vendor-reported бенчи | 🟢 | scaffold решает, опираться на Pro не Verified |

## Affected files (если бы имплементировали)
- `app/mcp_stdio.py` — новый tool `grok_review` (по образцу `codex_review`)
- `~/.local/bin/grok` — wrapper с `XAI_API_KEY` + `HTTPS_PROXY` (как codex wrapper)
- `.env` — `XAI_API_KEY` (нарушает "no API keys" policy)
- pipeline prompts — упоминание grok-debate skill

**Вывод:** механически интеграция дешёвая, но **юридический RF-блок + policy "только подписка" + избыточность поверх Codex** = не добавлять. Забрать сам паттерн (architect→lanes), который у нас уже есть.

---

## Second opinion (Codex) — ЗАБЛОКИРОВАН тулингом

Запускал `codex_review(mode=exec, target=research.md)` **дважды** (bg-ba20facbdb, bg-7d477ec9c4). Оба раза bg-job рапортовал "Codex exec done", но **output-файл не был записан** в worktree (`docs/tasks/grok-research/codex-review-research.md` отсутствует). Это известный баг `codex_review` CWD (упомянут в CLAUDE.md session notes несколько раз, "runs in main repo not worktree" — до конца не пофикшен). Codex отработал, но результат не персистится по пути worktree → прочитать нечем. Баг зарепорчен через `report_bug`.

**Митигация:** ключевые выводы стоят на собственных доказательствах (2 независимых источника на бенчи, primary xAI statement на RF-блок, primary docs на CLI). RF/OFAC-блокер и policy "только подписка" — не мнение, а факты, которые Codex не опроверг бы. При появлении рабочего пути к Codex — до-прогнать debate по load-bearing выводам (redundancy vs Codex — единственный пункт, где адверсариальное мнение реально добавило бы; помечен как решение, не факт).

## Sources (все открыты в этой сессии)

1. https://x.ai/news/grok-4-5 — офиц. анонс Grok 4.5 (через WebSearch-сводку + pricing)
2. https://techcrunch.com/2026/07/08/spacexai-releases-grok-4-5-which-elon-describes-as-an-opus-class-model/
3. https://explainx.ai/blog/grok-4-5-public-launch-spacexai-july-2026
4. https://x.ai/cli — Grok Build CLI
5. https://docs.x.ai/build/overview — **fetched**: install, headless `-p`, ACP, config.toml, CLAUDE.md/MCP recognition
6. https://www.eesel.ai/blog/grok-4-5-pricing + https://mem0.ai/blog/xai-grok-api-pricing — pricing, free-tier конфликт
7. https://docs.x.ai/developers/rate-limits — tier-based RPS/TPM, HTTP 429
8. https://aireiter.com/blog/grok-4-5-vs-claude-sonnet-5 — **fetched**: SWE Pro 64.7 vs 63.2, Terminal Bench, pricing, рекомендация
9. https://technext24.com/reviews/spacexai-grok-4-5-openai-gpt-5-6-analysis/ + https://codingfleet.com/blog/swe-bench-pro-leaderboard-2026/ + https://akitaonrails.com/2026/07/09/llm-benchmark-grok-4-5-gpt-5-6-sol/ — бенчи, Rails independent bench, vals.ai caveat
10. https://x.com/grok/status/1965450653750476820 — **офиц. заявление xAI**: Grok недоступен в РФ (санкции/export controls)
11. https://grokipedia.com/page/Grok_API — OFAC, Russia sanctions, blocked regions
12. https://github.com/DannyMac180/fable-advisor — **fetched**: architect-pattern, 3 lanes, spec-контракт, 90% token saving
