# #502 — площадки и черновики промо Orchestra

Публикует юзер сам. Здесь только разведка и готовые к копированию тексты. Ничего не отправлено,
никуда не написано, аккаунты не создавались.

Всё измерено 02.09.2026. Источник чисел про Orchestra — публичный README (раздел «Built by
Itself») и `gh api`; ничего сверх этого в черновиках не называется.

---

## 0. Что можно называть публично (и чего нельзя)

**Можно — проверено:**

| Факт | Чем подтверждён |
|---|---|
| 598 сессий агентов (577 воркеров, 21 оркестратор), 5 593 суб-агента, 250 877 сообщений, 7 047 ходов, 781 задача в 19 проектах | README:130–136, замер обеих БД 02.09 |
| Вторая инсталляция считается отдельно: 469 сессий, 5 043 суб-агента, 660 задач в 9 проектах | README:138 |
| Четыре рантайма воркеров за одним контрактом: Claude Code, Codex, Grok, OpenRouter Harness | `app/runtime_registry.py:330`, `BUILTIN_RUNTIMES` |
| Изоляция: git worktree на воркера, squash-merge в main | README «Git Worktree Isolation» |
| Ревью чужой моделью до мержа | README «Cross-Model Review» |
| Вектор-память признана deprecated по своему же замеру: 0 уникальных побед против 6 у `rg` на 18 вопросах | README «Project Memory» |
| Лицензия AGPL-3.0 + коммерческая | README «License» |
| Звёзд у репозитория — 3 | `gh api repos/DrSeedon/orchestra` |
| У Orca (stablyai/orca) 59 404 звезды на 02.09 | `gh api repos/stablyai/orca` (было «53k» — устарело) |

**Нельзя:** имена клиентов и проектов заказчиков, внутренние пути, любые цифры расходов и
подписок, «10x/революционный/бомба», сравнения «мы лучше Orca». Про Seedon — только то, что уже
есть в публичном README.

**Честная граница, которая должна быть в каждом тексте:** это один человек и один рабочий контур,
а не команда и не продукт. У соседей по нише — десятки тысяч звёзд и десктопные приложения, у нас
— архитектура и работающая инсталляция. Сравнение вести устройством, а не популярностью.

---

## 1. Разведка площадок

### 1.1 Целевая площадка из повода: @deksden_notes

Проверено чтением `t.me/s/deksden_notes` (20 постов) и трёх страниц истории (`?before=1186|1146|1106`).

| Что | Наблюдение |
|---|---|
| Автор, тема | DEKSDEN notes, 2 980 подписчиков. Описание канала: «Мои заметки на разные темы, уровень — "для продолжающих". Vibe Coding → AI SWE, AI Coding Tools, Agents: Claude Code, Codex…» |
| Свои посты | Строго один формат: `⚪️ Заголовок` → 2–6 коротких абзацев → `🔗 подпись : ссылка` → подпись `@deksden_notes`. Часто вопрос читателям `❓`, дополнения `Upd 1️⃣`. Длина 115–2 000 знаков, медиана ≈300 |
| Темы своих постов | Почти целиком новости инструментов: ресеты Codex, лимиты Claude, GLM в Vibe Code, Muse Code, Ollama pricing. То есть канал живёт быстрыми новостями |
| **Гостевые посты — есть, и у них ДРУГАЯ форма** | Найдено три: «База знаний» (`github.com/al322se/knowledge-base`), «Rejudge — независимая проверка для ИИ-агентов» (`github.com/syabro/rejudge`), «KeySwitcher» (`github.com/uginy/keySwitcher`) |
| Признаки гостевого поста | Нет `⚪️` в начале, нет подписи `@deksden_notes`. Заголовок — просто название или вопрос-боль. Рассказ от первого лица («выкатываю ещё один свой инструмент в паблик», «я написал и выложил в Open Source»). Ссылки на репозиторий сразу под заголовком или в конце. Подпись автора своим каналом («Ваш, @syabro_notes») — опционально. В конце теги: `#opensource`, иногда `#mit`, `#macos`, `#ai` |
| Длина гостевых | 1 231 / 1 733 / 2 242 знака. То есть **1,5–2,3 тыс. знаков — норма**, это заметно длиннее обычных постов канала |
| Структура гостевых | Проблема → почему существующее не подошло → что сделал → перечень возможностей списком → планы/установка → теги |
| Реакция автора на чужие проекты | Публикует как есть, своим комментарием не спорит; обсуждение уходит в комментарии к посту |

**Вывод по форме:** пост должен быть от первого лица, 1 500–2 200 знаков, с одной ясной мыслью,
списком из 4–6 пунктов, ссылкой на репозиторий и `#opensource` в конце. `⚪️` не ставить — это
маркер постов самого Дениса.

**Риски:** тема канала — новости инструментов, а не архитектурные лонгриды; пост длиннее 2,5 тыс.
знаков или без конкретики выпадет из ленты по стилю. Второй риск — Денис сам делает Memory Bank и
базы знаний для агентов; наш раздел про deprecated-вектор он прочитает предметно, поэтому цифра
«0 против 6» должна быть в тексте, а не в комментариях.

### 1.2 Остальные площадки (все проверены сегодня)

| Площадка | Ссылка | Чем подтверждена живость | Форма подачи | Риски |
|---|---|---|---|---|
| **awesome-cli-coding-agents** (EN) | `github.com/bradAGI/awesome-cli-coding-agents` | 1 137★, последний push 31.08.2026 | PR одной строкой в раздел `Harnesses & orchestration → Session managers & parallel runners`. Формат жёсткий: имя+ссылка, `⭐ N`, описание в 1–2 строки, сортировка по звёздам | Требования: CLI-интерфейс, автономное чтение/запись кода, живой репозиторий — проходим. С 3★ строка встанет в самый хвост раздела, рядом с проектами на 0–1★. Это нормально: список принимает такие |
| **awesome-harness-engineering** (EN) | `github.com/ai-boost/awesome-harness-engineering` | 3 950★, push 02.09.2026 (сегодня) | Бул-строка с развёрнутым описанием на 2–4 предложения: не «что это», а «какой приём harness-инженерии показывает» | Список концептуальный: берут за идею, а не за факт существования. Заявка «просто ещё один оркестратор» будет отклонена — заходить надо приёмом (ревью другой моделью как гейт мержа, worktree-изоляция, отозванный вектор) |
| **awesome-multi-agent-orchestrators** (EN) | `github.com/Agent-Analytics/awesome-multi-agent-orchestrators` | 74★, push 02.09.2026 (сегодня), сайт `openorchestrators.org` | PR правит `src/data/orchestrators.ts`: rank, name, summary, tags, directory note, ссылки. В CONTRIBUTING дословно: «Keep the copy factual and concise. Avoid marketing language» | Список маленький, но по теме точнее всех: берут только тех, у кого мульти-агентность — сам продукт, а не побочная фича. Требуют локальный превью сайта перед PR |
| **Hacker News, Show HN** (EN) | `news.ycombinator.com/showhn.html` | Правила прочитаны 02.09 | Заголовок начинается с `Show HN:`; первым комментарием — рассказ автора. Дословно из правил: «Show HN is for something you've made that other people can play with», «It needn't be complicated or look slick» | Дословный запрет: «Please don't ask friends to upvote or comment». Второй риск наш: правила просят «easy to try, ideally without barriers such as signups» — а Orchestra требует подписки Claude Max и установленных CLI. Это надо честно написать в первом же комментарии, иначе прилетит в комментариях |
| **Habr** (RU) | `habr.com/ru/hubs/artificial_intelligence/articles/` | Свежие статьи 02.09.2026 03:49, 01.09 21:10 и далее — хаб живой | Статья-разбор, не анонс. Работает формат «что не получилось и почему», с числами и кодом | Аудитория проверяет числа и не любит рекламу инструмента. Заходить надо разбором одного решения (например, отозванного вектора или ревью чужой моделью), а репозиторий упоминать по ходу |
| **GitHub Topics** (EN) | `github.com/topics/agent-orchestration`, `/coding-agents`, `/agent-harness` | Топики существуют, списки обновляются | Не пост, а настройка: у `DrSeedon/orchestra` сейчас **ноль topics** (`gh api repos/DrSeedon/orchestra -q .topics` → пусто) | Никакого риска, чистая потеря видимости. Делается за минуту |

### 1.3 Проверить не удалось — в список НЕ включаю

- **Reddit** (r/AI_Agents, r/LocalLLaMA, r/ClaudeAI). С этого сервера Reddit отдаёт `403` на
  `www.reddit.com`, `old.reddit.com` и на `.json`-эндпоинт; зеркало `rxddit.com` отвечает
  редиректом. То есть подтвердить свежесть постов и текущие правила самопиара я не могу, а
  вторичные пересказы правил в поиске противоречат друг другу. Черновик ниже (§2.6) даю, но
  площадку помечаю как непроверенную: перед отправкой нужно открыть сайдбар сабреддита из
  браузера и убедиться, что промо-посты там разрешены и что аккаунту хватает кармы.
- **vc.ru, Product Hunt, X/Twitter** — не проверял и не предлагаю: первое даёт нецелевую
  аудиторию, второе требует продуктовой упаковки и аккаунта, третье зависит от личного аккаунта
  юзера. Решение по ним — его, не моё.

---

## 2. Черновики

### 2.1 @deksden_notes — ВАРИАНТ А (без акцента «наш человек»)

> Первый абзац — единственное отличие от варианта Б. Дальше текст общий.

```
Orchestra — оркестратор, где агентами управляет агент, а не человек

https://github.com/DrSeedon/orchestra

Год назад я перестал успевать быть диспетчером у собственных агентов: нарезать задачи,
раздавать, помнить кто что делает, сводить ветки. Получилось так, что диспетчер — тоже
работа для агента. Так появилась Orchestra.

Что это: оркестратор ставит задачу воркерам, каждый воркер — отдельная CLI-сессия в
собственном git worktree. Человек формулирует цель и апрувит; кого спавнить, что резать,
когда звать ревью и что мержить — решает оркестратор.

Как устроено:

• Воркер = свой worktree + своя ветка, мерж squash-ем. Двое в одном репозитории не дерутся
  за файлы, конфликты структурно редкие
• Агентская почта: воркеры пишут друг другу напрямую, без человека-ретранслятора
• Ревью чужой моделью — обязательный шаг перед мержем. Написал Codex — смотрит Claude, и
  наоборот; у разных моделей разные слепые зоны
• Четыре рантайма за одним контрактом: Claude Code, Codex, Grok и свой OpenRouter-харнесс.
  Модель выбирается на воркера, не на проект
• Свой таск-менеджер с приоритетами и оплатами, TG-мост с топиками на агента, дашборд на
  FastAPI + HTMX + SSE
• Память проекта — файлы и грепы. Векторный поиск в коде остался, но помечен deprecated:
  на своих же 18 вопросах он дал 0 уникальных побед против 6 у обычного rg. Оставлять его
  рекомендованным было бы нечестно

Сколько наработано: по собственной БД — 598 сессий агентов (577 воркеров, 21 оркестратор),
5 593 суб-агента, 781 задача в 19 проектах. Вторая инсталляция считается отдельно и никогда
не складывается с первой.

Граница честности: это один человек с агентами и один рабочий контур, а не команда и не
продукт. Рядом в нише есть среды на десятки тысяч звёзд, где за флотом смотрит человек;
у меня ставка другая — смотрит оркестратор, человек ставит цель.

AGPL-3.0, ставится через uv, нужен свой Claude Code CLI. Вопросы — в комментариях, отвечу.

#opensource #agpl
```

Длина ≈2 100 знаков — попадает в диапазон гостевых постов канала (1 231–2 242).

### 2.2 @deksden_notes — ВАРИАНТ Б (с акцентом «сделал наш человек»)

Заменяет первые два абзаца варианта А, остальное — без изменений:

```
Orchestra — оркестратор, где агентами управляет агент, а не человек

https://github.com/DrSeedon/orchestra

Пишу из России, инструмент делал для себя и на своей подписке, а не в стартапе с
инвестициями. Год назад я перестал успевать быть диспетчером у собственных агентов:
нарезать задачи, раздавать, помнить кто что делает, сводить ветки. Диспетчер оказался
такой же работой для агента — так появилась Orchestra.
```

Дальше — с абзаца «Что это:» из §2.1 дословно.

**Решать юзеру.** Аргумент за Б: повод пришёл именно с этой формулировкой, и в русскоязычном
канале она читается как факт биографии. Аргумент за А: канал технический, и упоминание страны
не добавляет ни одного факта о самом инструменте — если Денис возьмёт пост в рубрику
`#opensource`, там ни у одного из трёх предыдущих гостей такой рамки нет.

### 2.3 Сопроводительное сообщение Денису (в чат канала)

```
Денис, привет. Я делаю Orchestra — оркестратор агентов с открытым кодом: оркестратор сам режет
задачу, спавнит воркеров (каждый в своём git worktree), гоняет ревью на другой модели и мержит.
Заметил, что у вас выходили гостевые посты про инструменты (Rejudge, KeySwitcher, knowledge-base),
и подумал, что тема попадает в канал.

Готов пост на 2к знаков в вашем формате, с ссылкой на репозиторий и без маркетинга — прикладываю
ниже. Если формат не подходит или нужно короче, скажите, перепишу.

https://github.com/DrSeedon/orchestra
```

### 2.4 Hacker News — Show HN

Заголовок (79 знаков, начинается с обязательного `Show HN:`):

```
Show HN: Orchestra – an orchestrator agent that manages a fleet of coding agents
```

URL: `https://github.com/DrSeedon/orchestra`

Первый комментарий (правила HN просят рассказать самому автору):

```
I built Orchestra because I became the bottleneck in my own agent setup: splitting the work,
assigning it, remembering who was doing what, merging the branches. That dispatcher job turned
out to be a job an agent can do.

How it works: you give the orchestrator a goal. It decomposes the work, spawns workers, routes
their output to a different model for review, and merges what passes. Each worker is a full CLI
session in its own git worktree on its own branch, squash-merged back. Workers message each other
directly instead of relaying through a human. Four runtimes sit behind one backend contract —
Claude Code, Codex, Grok and an in-process OpenRouter harness — so the model that writes the code
is not the model that reviews it.

Some numbers from the primary installation's own database: 598 agent sessions (577 workers,
21 orchestrators), 5 593 sub-agents, 781 tasks across 19 projects. A second installation on
another server is counted separately and never added in.

One thing I removed rather than added: semantic memory. The vector path is still in the code but
it is deprecated — on an 18-question holdout from this repository, vector retrieval scored 0
unique wins against 6 for plain `rg`, so lexical search over a knowledge base written for grep is
the default now.

Honest limits before you try it: this is one person and one working installation, not a team and
not a product. It is not zero-friction to run — you need your own Claude Code CLI and a Claude Max
subscription (Codex/Grok/OpenRouter optional), so it is not a click-and-play demo. AGPL-3.0, with
a commercial license available.

Happy to answer anything about the worktree isolation, the merge gate or the cross-model review
loop.
```

**Риск, который надо принять сознательно:** правила Show HN просят «make it easy to try, ideally
without barriers such as signups». Подписка и CLI — это барьер. Он назван в комментарии прямо,
что снимает претензию «продают невозможное», но не снимает возможных минусов в тредe.

### 2.5 Пулл-реквесты в awesome-списки

**(а) bradAGI/awesome-cli-coding-agents** — раздел `Harnesses & orchestration → Session managers
& parallel runners`, строка ставится по числу звёзд (сейчас — в конец раздела):

```markdown
- **[Orchestra](https://github.com/DrSeedon/orchestra)** `⭐ 3` — Self-hosted orchestrator where an agent, not a human, runs the fleet: it decomposes the goal, spawns workers in isolated git worktrees, routes each result to a different model for review, and squash-merges what passes. Claude Code, Codex, Grok and an OpenRouter harness behind one backend contract; FastAPI dashboard and a Telegram bridge. AGPL-3.0.
```

Заголовок PR: `Add Orchestra to Session managers & parallel runners`
Текст PR:
```
Adds Orchestra — an orchestrator that manages CLI coding agents rather than a UI for a human to
manage them. Meets the inclusion requirements: CLI/terminal agents driven autonomously (Claude
Code, Codex, Grok, OpenRouter harness), reads/writes code and runs commands, repo is active.
Placed at the end of the section per the star sort (3 stars). Disclosure: I am the author.
```

**(б) ai-boost/awesome-harness-engineering** — здесь берут за приём, поэтому строка про идею, а не
про продукт:

```markdown
- [Orchestra](https://github.com/DrSeedon/orchestra) — Harness where the dispatcher itself is an agent: an orchestrator decomposes the goal, spawns workers into isolated git worktrees, and gates every merge behind a review by a *different* model, on the premise that two vendors' models fail differently. Two harness decisions are worth stealing regardless of the tool: isolation is per-worker worktree plus squash merge, so parallel agents cannot corrupt each other's state; and project memory is deliberately lexical — the vector path is deprecated after an internal A/B where embeddings scored 0 unique wins against 6 for plain `rg` on an 18-question holdout, which is a rare published negative result on agent memory.
```

Заголовок PR: `Add Orchestra (agent-run dispatcher, cross-model merge gate, negative result on vector memory)`

**(в) Agent-Analytics/awesome-multi-agent-orchestrators** — правится `src/data/orchestrators.ts`,
копирайт по их CONTRIBUTING без маркетинга. Поля для записи:

```
name:    Orchestra
url:     https://github.com/DrSeedon/orchestra
summary: Self-hosted orchestrator where an agent decomposes the goal and runs the fleet: workers
         are full CLI sessions in isolated git worktrees, they message each other directly, and
         every merge is gated by a review from a different model.
tags:    multi-agent coordination, parallel coding agents, git worktree isolation, cross-model
         review, self-hosted, AGPL-3.0
note:    Runtimes are mixable per worker (Claude Code, Codex, Grok, OpenRouter harness) behind one
         backend contract. Includes a task manager, a Telegram bridge and a FastAPI/HTMX dashboard.
         Single-maintainer project.
```

Заголовок PR: `Add Orchestra to the directory`
В тексте PR обязательно указать, что мульти-агентность — сам продукт, а не побочная фича (их
критерий отбора), и что автор — контрибьютор.

### 2.6 Reddit, r/AI_Agents — ЧЕРНОВИК ДЛЯ НЕПРОВЕРЕННОЙ ПЛОЩАДКИ

Отправлять только после того, как юзер сам откроет сайдбар и убедится, что промо разрешено
(с сервера правила не читаются, см. §1.3).

Заголовок:
```
I built an orchestrator where an agent, not me, assigns the work to other coding agents
```

Тело:
```
Disclosure up front: I built this and I run it daily.

The setup most multi-agent tools give you is a grid where *you* watch the fleet. Mine is the
opposite: the orchestrator decomposes the goal, decides how many workers to spawn, gives each one
an isolated git worktree, routes the result to a different model for review, and squash-merges
what passes. I supply the goal and the approvals I care about.

Concrete design decisions, in case they are useful even if you never run it:

- Isolation is a git worktree per worker, not shared state. Two workers cannot edit each other's
  files; merges are squash, one commit per task.
- Workers talk to each other directly (worker A tells worker B "endpoint is ready, here is the
  schema") instead of relaying through the human.
- The review before merge runs on a different vendor's model than the one that wrote the code.
- Memory is lexical on purpose. I shipped a vector path, measured it against plain `rg` on an
  18-question holdout from my own repo, got 0 unique wins for vectors against 6 for grep, and
  marked the vector path deprecated instead of quietly keeping it as a feature.

Scale so far, from the installation's own database: 598 agent sessions, 5 593 sub-agents, 781
tasks across 19 projects.

Limits: one maintainer, one production installation, and it needs your own Claude Code CLI plus a
subscription — this is not a hosted product. AGPL-3.0.

https://github.com/DrSeedon/orchestra

Happy to answer design questions, especially about the merge gate.
```

### 2.7 Habr — заготовка статьи (тезисы, а не готовый текст)

Отдельный текст под Хабр я НЕ выдаю готовым к отправке намеренно: там формат «разбор с числами»,
и статья, написанная под копирку с телеграм-поста, соберёт минусы. Рабочая тема одна и она у нас
уже оплачена замером:

> «Мы выключили семантический поиск у своих агентов и вернулись к grep: 0 побед вектора против 6»

Каркас: как устроена память агентов у нас (файлы + база знаний под грепом) → зачем ставили вектор
→ как строили слепой holdout на 18 вопросов и почему критерий заморозили коммитом ДО замера →
результат 0/6 → что это НЕ доказывает (мерили одну базу и один тип вопросов, не эмбеддинги как
класс) → что оставили в коде и почему пометили deprecated, а не удалили. Orchestra упоминается по
ходу как контур, где это работает, ссылка одна, в конце.

Если юзер решит, что тема годится, — это отдельная задача с полноценным текстом, а не абзац в
промо-файле.

---

## 3. Порядок, который я бы предложил

1. **GitHub topics** — минута работы, ноль риска: `agent-orchestration`, `coding-agents`,
   `agent-harness`, `multi-agent`, `git-worktree`, `claude-code`, `codex`, `mcp`. Без них
   проект не находится в тематических лентах GitHub вообще.
2. **@deksden_notes** — повод пришёл оттуда, площадка проверена, гостевой формат подтверждён
   тремя примерами.
3. **Два PR в awesome-списки** (`awesome-cli-coding-agents`, `awesome-harness-engineering`) —
   принимаются проектами с 0–1 звездой, живут годами и дают постоянный трафик.
4. **awesome-multi-agent-orchestrators** — точнее всех по теме, но требует локальной сборки сайта
   перед PR.
5. **Show HN** — только после того, как README и Quick Start проверены на чистой машине: HN
   безжалостен к тому, что не запускается с первой попытки.
6. **Reddit** — последним и только после ручной проверки правил сабреддита.
