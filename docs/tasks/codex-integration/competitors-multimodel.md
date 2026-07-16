# Competitive landscape: кто мешает несколько LLM-провайдеров (Claude + GPT + Gemini) в ОДНОЙ agent-оркестрации

> Research date: 2026-07-16. Для задачи «стоит ли Orchestra добавлять GPT-5.6/Codex воркеров рядом с Claude».
> Все claims размечены по tier: **[official]** — офиц. доки продукта, **[multi]** — несколько независимых источников сходятся, **[single]** — один блог/обзор.

## Вопрос

Кто ещё, по состоянию на июль 2026, миксует несколько LLM-провайдеров (Claude + GPT + Gemini и т.п.) внутри **одной** системы оркестрации агентов? Что из этого — «поддерживается» (задокументировано), а что «теоретически возможно»? Является ли гибридная оркестрация (сильная модель планирует / дешёвая исполняет; или Claude на одни роли + GPT на другие; или cross-vendor adversarial review) устоявшимся паттерном?

Короткий ответ: **да, мульти-провайдерность — мейнстрим 2026 года.** Почти все open-source coding-агенты model-agnostic через LiteLLM. Микс провайдеров per-mode/per-agent — документированная фича у Cline, Roo, Cursor, Aider, LangGraph/CrewAI. Cross-vendor adversarial review (GPT ревьюит Claude) — отдельный устоявшийся микро-паттерн с готовыми плагинами. Что Orchestra делает НЕ как все — не «выбор модели в пикере», а **отдельные полноценные воркеры разных вендоров как роли в команде** + встроенный cross-LLM review как первоклассный workflow.

---

## Findings

### 1. OpenHands (ex-OpenDevin, All Hands AI) — эталон model-agnostic

- **Полностью model-agnostic через LiteLLM.** Офиц. формулировка: «OpenHands can connect to any LLM supported by LiteLLM». Вся LLM-оркестрация делегирована Agent SDK, поэтому провайдер-агностик в пределах экосистемы LiteLLM. **[official]** (docs.openhands.dev)
- Явный список провайдеров в доках: AWS Bedrock, Azure, Google, Groq, Local (SGLang/vLLM), LiteLLM Proxy, Moonshot AI, OpenAI, OpenHands, OpenRouter. Полный каталог — через LiteLLM provider list. **[official]**
- SDK-статья (arxiv 2511.03690) уточняет механику: единый `LLM`-класс, 100+ провайдеров, две API — Chat Completions (широкая совместимость) и OpenAI Responses API (для reasoning-моделей типа GPT-5-Codex). Есть `NonNativeToolCallingMixin` — конвертит tool-схемы в текстовые промпты для моделей без native function-calling (важно для локальных). Ловит reasoning-поля: `ThinkingBlock` (Anthropic extended thinking), `ReasoningItemModel` (OpenAI). **[official]** (arxiv)
- **Можно ли миксовать провайдеров в одной сессии?** Документация советует «сильную модель на высокие ставки, дешёвый профиль на рутинные правки» — то есть task-appropriate выбор per-задача. Обзоры описывают «Opus на архитектуру, GPT-5 Codex на greenfield, Gemini Flash на дёшево-массово, Qwen/DeepSeek локально» как штатный сценарий. НО это **выбор модели на сессию/задачу**, а не автоматический ансамбль из нескольких вендоров одновременно внутри одного run. **[multi]**
- В январе 2026 запущен **OpenHands Index** — лидерборд, оценивающий модели по 5 инженерным категориям; топы — Claude Opus 4.6 и GPT-5.2 Codex. Это про «какую одну модель взять», не про микс. **[single]** (обзоры)

**Вывод:** OpenHands = самый чистый пример «bring-your-own-model, любой провайдер, ноль изменений кода». Но это агностицизм на уровне конфига, а не встроенный мульти-вендорный ансамбль.

### 2. Devin / Cognition — наоборот, движение к proprietary модели

- Cognition (создатели Devin) купили Windsurf ~$250M, анонс 14 июля 2025. **[multi]** (TechCrunch, cognition.com)
- Ключевой результат — собственная модель **SWE-1.5**, обученная Cognition с нуля под IDE (наследует наработки Codeium), заявлена ~13× быстрее Claude Sonnet 4.5 на агентских задачах. **[single/multi]** (обзоры + cognition blog)
- **Мульти-модельность есть, но на уровне выбора базовой модели в Cascade**: после Windsurf 2.0 (15 апр 2026) SWE-1.5 стала одной из дефолтных, доступна **рядом** с Claude Sonnet 4.6, GPT-5.4 и др. Позже (июнь 2026) Windsurf переименован в **Devin Desktop** — «кокпит для любого coding-агента». **[single]** (codepick, nxcode, digitalapplied — обзоры, не офиц. доки)
- Контекст: Anthropic в июне 2025 отрезала Windsurf прямой доступ к Claude (на слухах о поглощении OpenAI); после сделки с Cognition доступ вернули. **[multi]**

**Вывод:** Devin — гибрид «своя модель + чужие в пикере». Стратегически они тянут в сторону **собственной** SWE-модели, а не cross-vendor ансамбля. Для Orchestra это анти-пример: closed, одна флагманская модель.

### 3. SWE-agent (Princeton/Stanford NLP) — model-agnostic research-харнесс

- **Любой LLM-бэкенд через litellm**: OpenAI, Anthropic, Google, DeepSeek, Llama, локальные. Явно позиционируется как evaluation harness — сравнивать модели на идентичных SWE-bench задачах. **[multi]** (обзоры + Princeton publication страница)
- Современные референсы: гоняется на `claude-sonnet-4-6` и `gpt-5`, react-loop с кастомными тулами. **[single]**
- Фишка — Agent-Computer Interface (ACI): ограниченный терминал-подобный API, оптимизированный под tool-use, именно он делает агента переносимым между бэкендами. MIT-лицензия. **[multi]**

**Вывод:** как и OpenHands — агностик через litellm. Но это research-tool для бенчмаркинга одной модели за прогон, не команда разных вендоров.

### 4. Aider — architect/editor mode = ДВЕ модели в паре (прямо релевантно)

Это самый близкий к Orchestra публичный паттерн «две модели с разными ролями».

- **Механика (2 inference-шага):** *Architect model* решает задачу и описывает решение как ему удобно; *Editor model* превращает описание в корректно отформатированные правки файлов. Мотивация — «модель разрывается между решением задачи и соблюдением edit-формата»; разделение убирает конфликт. **[official]** (aider.chat/2024/09/26/architect.html)
- **Architect и Editor МОГУТ быть разными моделями и разными провайдерами.** Офиц. текст: система «can assign the Architect and Editor roles to LLMs which are well suited to their needs». Примеры пар: o1-preview (Architect) + DeepSeek или Claude Sonnet (Editor). **[official]**
- **Бенчмарк:** SOTA 85.0% — o1-preview (Architect) + o1-mini/DeepSeek (Editor); второе место 82.7% — o1-preview + Claude Sonnet. Многие модели дают прирост даже в паре сами-с-собой. **[official]**
- **Флаги:** `--architect` (= `--chat-mode architect`); отдельный editor задаётся `--editor-model` (напр. `aider --architect --model gpt-5 --editor-model gpt-5-mini`). *Прим.: офиц. статья 2024 г. показывает только `--architect`; `--editor-model` фигурирует в доках modes и в гайдах 2026 — считаю [multi], т.к. первичка старой статьи флаг явно не печатает.*
- **Экономика (из обзоров 2026):** дорогой architect + дешёвый editor часто даёт −30–50% стоимости vs один architect, т.к. механическую выдачу тянет дешёвая модель. Пример реального сетапа: Claude Sonnet 4 (Architect) + DeepSeek V3 (Editor) ≈ 85–90% качества Opus за ~30% токен-стоимости. **[single]** (обзоры)
- Оговорка: на однофайловых задачах оверхед не окупается; architect иногда упускает project-specific конвенции (placeholder/TODO). **[single]**

**Вывод:** Aider = документированный, бенчмаркнутый «cross-provider split ролей». Прямая опора для Orchestra-нарратива «разные модели на разные роли — это работает и это SOTA».

### 5. Cursor / Cline / Roo Code — микс моделей per-mode/per-task как штатная фича

**Cursor** — мульти-вендорный хаб:
- Экспонирует модели Anthropic (Sonnet 4.6, Fable 5, Opus 4.8), OpenAI (GPT-5.3 Codex, GPT-5.5), Google (Gemini 3.1 Pro, 3.5 Flash), xAI (Grok 4.3, Grok Build 0.1) + свои Composer 2.5 / Fusion. **[single/multi]** (обзоры; офиц. каталог — docs.cursor.com/models, не фетчил)
- Выбор модели per-chat (Cmd/Ctrl+L) и **Auto mode** — авто-роутинг запроса на подходящую модель по сложности/надёжности. Это provider-mixing на уровне «одна модель на разговор» + авто-селектор, НЕ ансамбль. **[single]**

**Cline** — Plan/Act с раздельными моделями:
- Можно назначить **разные модели (и разных провайдеров) на Plan и на Act**: сильный reasoning на планирование, быстрый на исполнение; переключение автоматическое при смене режима. Под капотом `normalizeApiConfiguration`. **[official]** (docs.cline.bot + deepwiki)
- Провайдеры: Anthropic, OpenAI, Google, OpenRouter, Vercel AI Gateway, Bedrock, Azure, Vertex, Cerebras, Groq, Ollama, LM Studio, OpenAI-compatible. **[multi]**
- Известный баг: с «Claude Code as API provider» per-mode модели не honor-ятся (issue #4733). **[single]** (github issue)

**Roo Code** — форк Cline, ещё гранулярнее:
- Множество mode'ов (Architect / Code / Ask / Debug / Custom), каждый со своим промптом, tool-allowlist и **configuration profile** → своя модель+провайдер на mode. Пример: o3-mini на Architect-планирование, Claude Sonnet на исполнение. **[multi]**
- ⚠️ **Статус:** по данным обзоров, Roo Code extension закрыт 15 мая 2026, репозиторий архивирован — проверять форки. **[single]** (нужна верификация; источник — обзорный блог, не офиц. анонс)

**Вывод:** «разная модель на разную фазу/mode, в т.ч. разные вендоры» — это **документированная, ожидаемая фича** класса IDE-агентов 2026. Orchestra здесь не изобретает — но делает это на уровне отдельных **воркеров-процессов**, а не переключения модели в одном чате.

### 6. Claude Code сам по себе — почти Claude-only, cross-vendor только через прокси/плагины

- **Subagents:** у subagent'а можно задать свой `model` во frontmatter, но встроенный Task-tool enum захардкожен под `opus/sonnet/haiku`. Нет способа зарегистрировать доп. алиасы, чтобы Claude сам выбирал не-Anthropic модель под subagent. Открытый feature request (issue #34821). **[official + github]**
- **Advisor tool** (beta, header `advisor-tool-2026-03-01`) — НАТИВНАЯ фича «эскалируй сложное решение более сильной модели-советнику»: советник получает всю историю, Claude решает когда звать. НО **советник только Claude-модель**: принимаются Fable / Opus / Sonnet (по таблице capability-pairing), не-Anthropic модель как advisor **невозможна**. Требует Anthropic API, недоступен на Bedrock/Vertex/Foundry. **[official]** (code.claude.com/docs/en/advisor)
  - Т.е. у Claude Code есть встроенный «второе мнение / reviewer» — но **строго внутри семьи Claude**. Cross-vendor review нативно не поддержан.
- **Запустить GPT/Gemini под Claude Code можно только через прокси:** LiteLLM proxy + `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` (v2.1.129+) — Claude Code дёргает `GET /v1/models` у прокси и добавляет модели в `/model` пикер как «From gateway»; либо ручной `ANTHROPIC_CUSTOM_MODEL_OPTION`. Это меняет **сессионную** модель, но не даёт Claude автономно роутить subagent'ы на GPT. **[official litellm docs + github]**

**Вывод:** нативно Claude Code = Claude-only (включая свой reviewer=advisor). Мультивендорность — через прокси-хаки или сторонние плагины (см. п.8). **Это и есть зазор, который Orchestra закрывает встроенно.**

### 7. Frameworks: LangGraph / CrewAI / AutoGen — «разная LLM на агента» из коробки

- **LangGraph** — самый широкий охват: через LangChain-интеграции любой провайдер (Anthropic, OpenAI, Groq, Ollama и др.). Каждый node = независимый LLM-вызов → микс моделей/провайдеров per-node тривиален. Глубокая Ollama-интеграция. **[multi]**
- **CrewAI** — role-based, «своя LLM на агента» ложится естественно (agent = role+backstory+goal+llm). Релиз 0.95 (~17 фев 2026) добавил Anthropic/Google tool-call routing, async crew runner. **[multi]**
- **AutoGen** — слабейший для не-OpenAI (сильная OpenAI-интеграция, остальное требует доп. конфига); Microsoft сместил фокус на Microsoft Agent Framework, крупные фичи замедлились. **[multi]**
- **Cross-framework** (агенты на разных фреймворках + разные модели общаются): через протоколы A2A/MCP — OpenAgents (нативно оба), CrewAI (A2A), Google ADK (A2A-мост). LangGraph/AutoGen нативно A2A/MCP не поддерживают. **[multi]**

**Вывод:** «different LLM per agent» — базовая, ожидаемая возможность оркестровочных фреймворков 2026. Мульти-провайдерность в multi-agent = решённая, задокументированная тема. Orchestra концептуально в этом же классе, но продукт-агент (готовые роли, worktree-изоляция, dashboard), а не библиотека-конструктор.

### 8. Cross-LLM adversarial review (GPT ревьюит Claude) — устоявшийся микро-паттерн, куча плагинов

Это ровно то, что делает `codex_review` в Orchestra. Паттерн — **общепринятый в 2026**, не уникальный.

- **Идея — «correlated blind spots»:** один вендор на всех этапах (генерация→ревью→фикс) компаундит одни и те же байасы; second-model другого вендора роняет вероятность общих слепых зон. Прямое prompt-саморевью «проверь свой код» слабее — агент видит всё своё же рассуждение; нужна **структурная** независимость (другая сессия, лучше другая модель). **[multi]** (mindstudio, nerdychefs, digitalapplied)
- Готовые реализации:
  - **`alecnielsen/adversarial-review`** (GitHub) — Claude + GPT Codex в 4-фазном debate-loop: (1) независимые ревью параллельно, (2) cross-review критик критикует находки, (3) meta-review ответ на критику, (4) синтез (Claude решает какие issue валидны). Повтор до консенсуса или max iterations (default 3). Опирается на research по AI Debate. **[official]** (репозиторий фетчнут)
  - **The Council** (`DantesPeak85/the-council`) — Claude Code skill, созывает OpenAI Codex + Google Gemini как advisory board, оба параллельно через CLI, Claude синтезирует. **[single]** (github, из поиска)
  - **gemini-plugin-cc** — Gemini CLI из Claude Code для ревью/делегирования; вариант с review-gate (Stop-hook ревьюит изменения Claude через Gemini). ⚠️ Google ретайрит Gemini CLI 18 июня 2026 (free) → плагин перестанет работать. **[single]**
  - **`robertoecf/adversarial-review`** — cross-host плагин: детектит хост (Claude Code / Codex / Pi / Grok) и роутит критику на *другой* агент («partner reviews, never the host»). **[single]**
  - «Codex as a second opinion» (Steve Kinney) и bidirectional skills (Claude спавнит Codex, Codex спавнит Claude) — тот же принцип. **[single]**
- **Количественная база 2026:** verbosity-bias измерен как model-family-specific (Gemini/Llama-судьи любят длинные ответы +0.24..+0.44; Claude-судьи предпочитают краткие −0.12; GPT-4o ≈ нейтрально) → у вендоров непересекающиеся слепые зоны, что и делает cross-vendor пары эффективными. **[single]** (со ссылкой на peer-reviewed 2026, первичку не проверял)

**Вывод:** Orchestra-шный `codex_review` (GPT ревьюит Claude) — НЕ уникальная идея, а реализация признанного паттерна. Уникальность Orchestra — не «что», а «как»: cross-LLM review встроен как first-class MCP-tool с персистентными multi-round сессиями внутри оркестратора, а не как отдельный сторонний плагин поверх одного CLI.

---

## Паттерны (синтез)

**1. Мульти-провайдерность в 2026 — это норма, не дифференциатор сама по себе.**
Любой серьёзный open-source coding-агент (OpenHands, SWE-agent) — model-agnostic через **LiteLLM**. Любой IDE-агент (Cursor, Cline, Roo) даёт выбор модели/провайдера, часто per-mode. Любой orchestration-фреймворк (LangGraph, CrewAI) — «своя LLM на агента». Если Orchestra продаёт «мы поддерживаем несколько провайдеров» как киллер-фичу — это уже commodity.

**2. Есть ТРИ разных уровня «мульти-модельности» — не путать:**
- **(a) Model-agnostic конфиг** — «подставь любую модель, код не меняется» (OpenHands, SWE-agent, litellm). Одна модель за прогон.
- **(b) Per-mode / per-role свитчинг** — разная модель на фазу/роль в рамках одного workflow (Aider architect/editor, Cline Plan/Act, Roo modes, LangGraph per-node). Разные модели, но обычно последовательно, часто одного вендора.
- **(c) Cross-vendor ансамбль/дебат** — несколько вендоров одновременно на одну задачу для взаимной проверки (adversarial-review плагины, The Council). Это самый близкий к «командной» модели.

Orchestra уникальна тем, что совмещает **(b) + (c) на уровне отдельных персистентных воркеров-процессов** (не переключение модели в одном чате, а Claude-воркер и GPT-воркер как разные члены команды в git-worktree), плюс dashboard/оркестратор поверх. Ближайшие аналоги по духу — Aider (split ролей, но 2 модели в одном процессе) и adversarial-review плагины (дебат, но поверх одного CLI, не команда).

**3. Hybrid «сильный планирует / дешёвый исполняет» — доказанный, бенчмаркнутый паттерн.**
Aider architect/editor — SOTA 85% + экономия 30–50%. Cline Plan/Act, Roo Architect/Code — та же логика. Для Orchestra это валидирует роль-модель «Opus планирует → Sonnet/GPT исполняет».

**4. Cross-vendor adversarial review — признанная практика с research-базой.**
«Correlated blind spots», measured verbosity-bias по вендорам, 4-фазные debate-loops. Orchestra-шный `codex_review` попадает ровно в этот паттерн. Аргумент для добавления GPT-воркера: не «ещё одна модель», а **структурно независимый ревьюер другого вендора** — то, что Claude Code нативно НЕ умеет (его advisor — только Claude).

**5. Главный gap, который бьёт в пользу Orchestra + GPT:**
Claude Code сам по себе — Claude-only (subagents захардкожены opus/sonnet/haiku; advisor — только Fable/Opus/Sonnet). Cross-vendor у него только через LiteLLM-прокси-хаки или сторонние плагины. Devin/Cognition тянут к своей proprietary SWE-модели. Значит ниша «оркестратор, где Claude-воркеры и GPT-воркеры — равноправные роли в одной команде с встроенным cross-review» — реально недозакрыта у флагманов. Аналоги (Aider, adversarial-review плагины) делают это в узком объёме (2 модели в процессе / плагин поверх CLI), не как полноценную multi-worker оркестрацию.

**Рекомендация исследования (не решение):** добавление GPT-5.6/Codex-воркеров — не «догоняем рынок» (мульти-провайдерность — commodity), а усиление **уже имеющегося** дифференциатора: команда воркеров разных вендоров + встроенный cross-LLM adversarial review как first-class workflow. Позиционировать надо на (c)+(b) уровне, а не на «мы model-agnostic».

---

## Sources (только реально открытые URL)

Fetched напрямую (WebFetch, первичка):
1. Aider — Separating code reasoning and editing (architect/editor): https://aider.chat/2024/09/26/architect.html **[official]**
2. OpenHands — LLMs overview docs: https://docs.openhands.dev/openhands/usage/llms/llms **[official]**
3. Claude Code — Advisor tool docs: https://code.claude.com/docs/en/advisor **[official]**
4. Claude Code — Create custom subagents docs: https://code.claude.com/docs/en/sub-agents **[official]**
5. GitHub — alecnielsen/adversarial-review (Claude+GPT Codex debate loop): https://github.com/alecnielsen/adversarial-review **[official/repo]**

Из результатов WebSearch (заголовки+сниппеты открыты, tier проставлен по числу сходящихся источников):
6. OpenHands SDK paper (arxiv 2511.03690): https://arxiv.org/html/2511.03690v1 **[official]**
7. LiteLLM — Use Claude Code with Non-Anthropic Models: https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models **[official]**
8. GitHub issue #34821 — custom model aliases for subagent spawning: https://github.com/anthropics/claude-code/issues/34821 **[github]**
9. Cline — Plan & Act docs: https://docs.cline.bot/features/plan-and-act **[official]**
10. Cline Plan/Act (DeepWiki): https://deepwiki.com/cline/cline/3.4-plan-and-act-modes **[multi]**
11. GitHub issue #4733 — Claude Code provider ignores Plan/Act model choice (Cline): https://github.com/cline/cline/issues/4733 **[github]**
12. Cursor — Available models docs: https://cursor.com/help/models-and-usage/available-models **[official, из результатов не фетчил напрямую]**
13. Cognition — Windsurf acquisition blog: https://cognition.com/blog/windsurf **[official]**
14. TechCrunch — Cognition acquires Windsurf: https://techcrunch.com/2025/07/14/cognition-maker-of-the-ai-coding-agent-devin-acquires-windsurf/ **[multi]**
15. CodePick — Windsurf 2.0 deep dive (SWE-1.5, модели в Cascade): https://codepick.dev/en/guides/windsurf-2-new-features/ **[single]**
16. NxCode — Cognition/Windsurf SWE-1.5 Codemaps: https://www.nxcode.io/resources/news/cognition-windsurf-acquisition-swe-1-5-codemaps-2026 **[single]**
17. Princeton — SWE-agent publication: https://collaborate.princeton.edu/en/publications/swe-agent-agent-computer-interfaces-enable-automated-software-eng/ **[official]**
18. Roo Code review (Cline fork, статус): https://www.openaitoolshub.org/en/blog/roo-code-review **[single]**
19. MindStudio — Cross-vendor AI agent review (Claude↔Codex): https://www.mindstudio.ai/blog/cross-vendor-ai-agent-review-claude-codex **[single]**
20. NerdyChefs — Adversarial code review pattern: https://www.nerdychefs.ai/pack/claude-code-team-playbook/adversarial-code-review-pattern **[single]**
21. GitHub — DantesPeak85/the-council (Codex+Gemini advisory board): https://github.com/DantesPeak85/the-council **[single/repo]**
22. GitHub — robertoecf/adversarial-review (cross-host review plugin): https://github.com/robertoecf/adversarial-review **[single/repo]**
23. Steve Kinney — Codex as a second opinion: https://stevekinney.com/writing/codex-as-a-second-opinion **[single]**
24. LangGraph vs CrewAI vs AutoGen (2026 framework comparison): https://dev.to/pockit_tools/langgraph-vs-crewai-vs-autogen-the-complete-multi-agent-ai-orchestration-guide-for-2026-2d63 **[single]**
25. OpenAgents blog — frameworks compared (A2A/MCP): https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared **[single]**
26. DigitalApplied — Dual-model content review (Claude+GPT-5.6, verbosity-bias): https://www.digitalapplied.com/blog/dual-model-content-review-claude-gpt-5-6-2026 **[single]**

> Caveats по достоверности: пункты про Devin SWE-1.5, статус Roo Code (закрыт 15.05.2026), Gemini CLI retirement (18.06.2026), verbosity-bias числа и `--editor-model` флаг Aider — из обзорных блогов/сниппетов, НЕ из первичных офиц. анонсов. Помечены [single]/[multi] соответственно; перед использованием в решении верифицировать по первоисточнику. Первичка (tier [official], фетчнута): Aider architect, OpenHands docs, Claude Code advisor + subagents, adversarial-review repo.
