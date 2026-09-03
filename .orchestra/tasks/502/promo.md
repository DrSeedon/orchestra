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
| 598 сессий агентов (577 воркеров, 21 оркестратор), 250 877 сообщений, 7 047 ходов, 781 задача в 19 проектах | README:130–136, замер обеих БД 02.09 |
| **Суб-агентов 197**, а не 5 593: в таблице `subagents` 5 593 строки, но 96,5% из них — фоновые bash-команды (`task_type='local_bash'`) | README:133 после правки 02.09, замер `select task_type, count(*)` на обеих базах, #503 |
| Вторая инсталляция считается отдельно: 469 сессий, 660 задач в 9 проектах | README:138 |
| Время жизни воркера: медиана 0,8 ч, p90 **130,6 ч**, максимум **531,8 ч**, дольше суток жили 81 из 431 завершённых; медиана 77,5 ходов на сессию | `sessions` боевой БД, #503 |
| Время жизни суб-агента в нашем же контуре: медиана **12,5 с**, p90 75,1 с, максимум 587,2 с, дольше 10 минут — **0,0%** | `subagents` боевой БД, #503 |
| Субагенты Claude Code имеют свой контекст, `SendMessage` между собой, вложенность до трёх уровней и опциональный `isolation: worktree` | `code.claude.com/docs/en/sub-agents`, 02.09, #503 |
| Субагент не пересекает границу вендора: у Claude Code это Claude, у Codex — Codex | обе документации, #503 |
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

### 2.0 Рамка всех текстов (решение юзера 03.09.2026)

Прежние две рамки сняты: «оркестратор устроен так-то» — слабая, «ADE/harness, опередивший
Orca» — недоказуемая и неверная (матрица #503: мы не впереди Orca, мы в другой нише и по
половине столбцов позади).

**Рабочая рамка — три пункта, все из замеров #503:**
1. **Исполнитель живёт неделями, а не секундами.** Воркер: медиана 0,8 ч, p90 130,6 ч,
   максимум 531,8 ч, 81 сессия дольше суток, медиана 77,5 ходов. Суб-агент на наших же
   данных: медиана 12,5 с, p90 75,1 с, дольше 10 минут — 0,0%. Это разные классы сущностей.
2. **Граница вендора.** Субагент принадлежит своему вендору, поэтому ревью чужой моделью
   внутри него структурно невозможно. У нас «написал Codex — проверяет Claude» — обычный ход.
3. **Ревью — обязательный гейт мержа**, а не просьба к помощнику.

**Обязательная честность в каждом тексте:** за 2026 год субагенты забрали часть прежних
отличий — свой контекст, переписка между собой, вложенность, опциональная worktree-изоляция.
Это не ослабляет текст: читатель, знающий матчасть, проверит первым делом именно это. И везде
остаётся фраза о том, где субагенты объективно лучше нас.

### 2.1 @deksden_notes — ВАРИАНТ А (действующий)

```
Orchestra — агенты, которые живут неделями, а не один ход

https://github.com/DrSeedon/orchestra

Год назад я перестал успевать быть диспетчером у собственных агентов: нарезать задачи, помнить кто что делает, сводить ветки. Диспетчер оказался такой же работой для агента — так появилась Orchestra.

Главное отличие видно в цифрах, а не в описании. Померил по своей же базе:

• воркер Orchestra — медиана жизни 0,8 ч, p90 130,6 ч, максимум 531,8 ч (22 дня), 81 сессия прожила дольше суток, медиана 77,5 ходов на сессию
• суб-агент в том же контуре — медиана 12,5 с, p90 75,1 с, дольше 10 минут ноль случаев

То есть это не «субагент, только подольше». Субагент разгружает контекст одного разговора, воркер — отдельный процесс со своей задачей, веткой и историей, переживающий рестарт платформы.

Второе отличие — граница вендора. Субагенты Claude Code это Claude, субагенты Codex это Codex; ревью чужой моделью внутри них невозможно по устройству. У меня воркер — сессия любого из четырёх рантаймов (Claude Code, Codex, Grok, свой OpenRouter-харнесс), поэтому «написал Codex — проверяет Claude» обычный ход. Ревью при этом стоит гейтом на мерже: работа не попадает в main мимо него, и мержит не тот агент, который писал код.

Что это даёт по нагрузке на человека. Повод посчитать — пост на r/ClaudeAI: у автора 10 727 сообщений на 343 сессии, 31 на сессию. У меня за месяц — 1 157 сообщений человека на 1 067 сессий агентов, примерно одно на сессию, при одинаковой доле исправлений (30–38% против его 33%). Оговорка обязательная: в мои сессии входят воркеры, которых человек не видит вовсе — в этом и смысл, но сравнивать надо именно так.

Честно про то, что изменилось: за 2026 субагенты забрали часть прежних отличий — свой контекст, SendMessage между собой, вложенность до трёх уровней и worktree-изоляцию опцией. И там, где надо «сходи посмотри в двадцати файлах и вернись», субагент дешевле моего воркера — это правильный инструмент для такой задачи.

Векторную память пометил deprecated после собственного замера: 0 уникальных побед против 6 у обычного rg на 18 вопросах.

Границы: это один человек с агентами и один рабочий контур, а не команда и не продукт. AGPL-3.0, ставится через uv, нужен свой Claude Code CLI. Вопросы — в комментариях.

#opensource #agpl
```

Длина 2 267 знаков (посчитано по файлу; редакция 03.09 с замером нагрузки на человека) — внутри диапазона гостевых постов канала
(1 231–2 242). Резать при необходимости абзац «Что ещё в коробке».

### 2.2 @deksden_notes — ВАРИАНТ Б (ОТВЕРГНУТ юзером 02.09, оставлен как история)

Не использовать. Ссылается на редакцию варианта А ДО переписывания 03.09 (#505) — сам текст Б
намеренно не трогался. Заменял первые два абзаца прежнего варианта А:

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

### 2.3 Как заходить — ЧЕРЕЗ ЛИЧКУ @deksden (ОТМЕНЯЕТ решение 02.09)

**Поправка 03.09.2026, основание — публичная политика канала, объявленная самим автором:**
дословно «Авторы OpenSource - пишите в личку @deksden , сделаем "гостевой" пост в канал с
презентацией вашего проекта - это всегда пожалуйста!». Тем же сообщением он ограничил чат:
«НЕ СВЯЗАННЫЕ с тематикой обсуждения лучше сразу переводить в личку», «Не очень бы хотелось
применять административные меры».

Поэтому прежний порядок «постим прямо в чат, дальше договоримся там» (решение юзера 02.09,
§2.8) ОТМЕНЁН владельцем площадки: пост в чат теперь читается как ровно то поведение, против
которого он выступил. Рабочий порядок — личка, одна короткая строка + текст §2.1 отдельным
сообщением.

Строка для лички:

```
Здравствуйте! Увидел, что вы предлагаете гостевые посты авторам опенсорса. Сделал оркестратор
ИИ-агентов, выложил под AGPL. Ниже текст в формате ваших гостевых постов — скажите, если надо
короче или иначе.
```

### 2.3-old Прежний порядок (архив, НЕ применять)

Порядок: постим текст §2.1 прямо в чат канала, дальше договариваемся там. Отдельного письма
Денису не нужно — перед постом достаточно одной строки, чтобы было видно, что это заявка в
рубрику, а не самореклама в чужой ленте:

```
Сделал оркестратор агентов, выкладываю в опенсорс. Видел, что у вас выходили гостевые посты
про инструменты (Rejudge, KeySwitcher, knowledge-base) — если тема подходит каналу, вот пост
в том же формате; скажите, если надо короче или иначе.
```

Дальше сразу текст из §2.1 отдельным сообщением, чтобы его можно было забрать целиком без
редактуры.

### 2.4 Hacker News — Show HN

Заголовок (72 знака, начинается с обязательного `Show HN:`):

```
Show HN: Orchestra – coding agents that live for weeks, not for one turn
```

URL: `https://github.com/DrSeedon/orchestra`

Первый комментарий (правила HN просят рассказать самому автору):

```
I built Orchestra because I became the bottleneck in my own agent setup: splitting the work,
assigning it, remembering who was doing what, merging the branches. That dispatcher job turned
out to be a job an agent can do.

The difference from subagents is measurable, so here are the measurements from my own database
rather than an argument. An Orchestra worker: median lifetime 0.8 h, p90 130.6 h, max 531.8 h
(22 days), 81 sessions ran longer than a day, median 77.5 turns per session. A subagent in the
same setup: median 12.5 s, p90 75.1 s, and not one of them lived past ten minutes. These are two
different classes of thing. A subagent takes noisy work off one conversation; a worker is a
process with its own task, branch and history that survives a platform restart and comes back on
the same native thread.

The second difference is the vendor boundary. Claude Code subagents are Claude, Codex subagents
are Codex, so review by another vendor's model is structurally impossible inside them. In
Orchestra a worker is a session of any of four runtimes — Claude Code, Codex, Grok, or an
in-process OpenRouter harness — so "Codex wrote it, Claude reviews it" is an ordinary step.

Third: that review is a merge gate, not a favour you ask an assistant. Work does not reach main
without it, and the agent that wrote the code is not the one that merges it.

What honestly changed in 2026: subagents took over part of what used to be my differentiators —
their own context window, SendMessage between agents, nesting several layers deep, and optional
git worktree isolation. And for "go read twenty files and come back", a subagent is cheaper than
one of my workers; that is the right tool for that job.

Scale, from the primary installation: 598 agent sessions (577 workers, 21 orchestrators), 197
spawned sub-agents, 781 tasks across 19 projects. A second installation on another server is
counted separately and never added in.

One thing I removed rather than added: semantic memory. The vector path is still in the code but
deprecated — on an 18-question holdout from this repository it scored 0 unique wins against 6 for
plain `rg`.

Honest limits: one person, one working installation, not a team and not a product. It is not
zero-friction — you need your own Claude Code CLI and a subscription, so this is not a
click-and-play demo. AGPL-3.0, commercial license available.

Happy to answer anything about the merge gate, the worktree isolation or the cross-model review.
```

**Риск, который надо принять сознательно:** правила Show HN просят «make it easy to try, ideally
without barriers such as signups». Подписка и CLI — это барьер. Он назван в комментарии прямо,
что снимает претензию «продают невозможное», но не снимает возможных минусов в тредe.

### 2.5 Пулл-реквесты в awesome-списки

**(а) bradAGI/awesome-cli-coding-agents** — раздел `Harnesses & orchestration → Session managers
& parallel runners`, строка ставится по числу звёзд (сейчас — в конец раздела):

```markdown
- **[Orchestra](https://github.com/DrSeedon/orchestra)** `⭐ 3` — Self-hosted orchestrator for long-lived workers rather than per-turn helpers: each worker is a CLI session in its own git worktree that survives restarts (measured p90 lifetime 130.6 h against 75.1 s for subagents in the same setup), workers message each other directly, and every merge is gated by a review from a *different vendor's* model — Claude Code, Codex, Grok and an OpenRouter harness sit behind one backend contract. AGPL-3.0.
```

Заголовок PR: `Add Orchestra to Session managers & parallel runners`
Текст PR:
```
Adds Orchestra — an orchestrator for agents that live for days, not for one turn: workers are
CLI sessions persisted in SQLite, each in its own git worktree, and a merge is gated by review
from a different vendor's model (Claude Code, Codex, Grok, OpenRouter harness behind one
contract). Meets the inclusion requirements: drives CLI/terminal agents autonomously,
reads/writes code and runs commands, repo is active. Placed at the end of the section per the
star sort (3 stars). Disclosure: I am the author.
```

**(б) ai-boost/awesome-harness-engineering** — здесь берут за приём, поэтому строка про идею, а не
про продукт:

```markdown
- [Orchestra](https://github.com/DrSeedon/orchestra) — Harness built on the premise that the unit of work should outlive the conversation: workers are CLI sessions persisted in SQLite, each in its own git worktree, and the author measured them against subagents in the same setup — p90 lifetime 130.6 h and median 77.5 turns per worker, against a subagent median of 12.5 s with none surviving ten minutes. Two decisions are worth stealing regardless of the tool: the merge is gated by a review from a *different vendor's* model, which subagents cannot do because a subagent belongs to its own vendor; and project memory is deliberately lexical — the vector path is deprecated after an internal A/B where embeddings scored 0 unique wins against 6 for plain `rg` on an 18-question holdout, a rare published negative result on agent memory.
```

Заголовок PR: `Add Orchestra (workers that outlive the conversation, cross-vendor merge gate, negative result on vector memory)`

**(в) Agent-Analytics/awesome-multi-agent-orchestrators** — правится `src/data/orchestrators.ts`,
копирайт по их CONTRIBUTING без маркетинга. Поля для записи:

```
name:    Orchestra
url:     https://github.com/DrSeedon/orchestra
summary: Self-hosted orchestrator for workers that outlive a single conversation: each worker is
         a CLI session persisted in SQLite with its own git worktree and branch, workers message
         each other directly, and every merge is gated by a review from a different vendor's
         model.
tags:    multi-agent coordination, long-lived agent sessions, git worktree isolation,
         cross-vendor review, self-hosted, AGPL-3.0
note:    Runtimes are mixable per worker (Claude Code, Codex, Grok, OpenRouter harness) behind one
         backend contract, which is what makes cross-vendor review possible — a subagent belongs
         to its own vendor and cannot be reviewed by another. Measured on the author's own
         installation: worker p90 lifetime 130.6 h against 75.1 s for subagents in the same setup.
         Includes a task manager, a Telegram bridge and a FastAPI/HTMX dashboard.
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
I measured my agents against subagents: 130 hours vs 75 seconds, and what that changes
```

Тело:
```
Disclosure up front: I built this and I run it daily.

I kept being told my orchestrator is "just subagents with extra steps", so I measured both in the
same setup, from my own database:

- Orchestra worker: median lifetime 0.8 h, p90 130.6 h, max 531.8 h (22 days), 81 sessions ran
  longer than a day, median 77.5 turns per session.
- Subagent in the same setup: median 12.5 s, p90 75.1 s, zero of them lived past ten minutes.

That is not "the same thing but longer". A subagent exists to take noisy work off one
conversation. A worker is a process with its own task, branch and history, persisted in SQLite,
that survives a restart of the platform and resumes on the same native thread.

The second difference is the one people miss: a subagent belongs to its vendor. Claude Code
subagents are Claude, Codex subagents are Codex — so having another vendor's model review the
work is structurally impossible inside them. In my setup a worker is a session of any of four
runtimes (Claude Code, Codex, Grok, an in-process OpenRouter harness), and that review is a merge
gate: nothing reaches main without it, and the agent that wrote the code does not merge it.

Being fair about 2026: subagents took over a lot of what used to be the gap — their own context
window, messaging between agents, nesting several layers deep, optional git worktree isolation.
And when the job is "go read twenty files and report back", a subagent is cheaper than one of my
workers and is the right tool.

Other design decisions, in case they are useful even if you never run it:

- Isolation is a git worktree per worker; merges are squash, one commit per task.
- Workers message each other directly (worker A tells worker B "endpoint is ready, here is the
  schema") instead of relaying through me.
- Memory is lexical on purpose. I shipped a vector path, measured it against plain `rg` on an
  18-question holdout from my own repo, got 0 unique wins for vectors against 6 for grep, and
  marked the vector path deprecated instead of quietly keeping it as a feature.

Scale so far, from the installation's own database: 598 agent sessions, 197 spawned sub-agents,
781 tasks across 19 projects.

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

## 2.8 РЕШЕНИЯ ЮЗЕРА — что отменено и что заменено

### Решение 03.09.2026 (#505): новая рамка, все черновики переписаны

Дословно: «Да согласен». Отменены ОБЕ прежние рамки — «как устроен оркестратор» (слабая) и
«ADE/harness, опередивший Orca» (недоказуемая и неверная: матрица #503 показала, что мы не
впереди Orca, а в другой нише, и по половине столбцов позади). Действующая рамка — §2.0:
время жизни исполнителя, граница вендора, ревью как гейт мержа, плюс обязательное признание
того, что субагенты за 2026 год забрали часть прежних отличий.

Переписаны: §2.1 (вариант А), §2.3 (заход в чат вместо письма в личку), §2.4 (Show HN и первый
комментарий), §2.5 (все три PR), §2.6 (Reddit). Не трогался §2.2 — он отвергнут 02.09.

**Числовая поправка, обязательная к соблюдению:** в постах стоит **197 суб-агентов**, а не
5 593. Строка README исправлена после находки #503: 96,5% строк таблицы `subagents` — фоновые
bash-команды. Публиковать 5 593 как «суб-агентов» — повторить ту же ошибку публично.

### Решения 02.09.2026

Три решения приняты, черновики выше читать с этими поправками:

1. **Берём ВАРИАНТ А** (без акцента «наш человек»). Вариант Б в §2.2 остаётся в файле как
   отвергнутая альтернатива, использовать его не надо. Основание — совет того же читателя,
   который подал идею: «понятно что у Дениса никто не пишет "я из России и пишу на русском
   языке"».

2. **В личку Денису не пишем.** Сопроводительное сообщение §2.3 отменено в своём назначении:
   пост публикуется прямо в ЧАТ канала, дальше договариваются там. Дословно: «у Дениса даже не
   надо ничего ему в личку кидать, просто написать пост в чат. дальше уже договоритесь».

3. **Формулировку «опередил Orca» использовать ЗАПРЕЩЕНО, пока нет матрицы.** Совет читателя
   был «писать надо о том, что ты сделал ADE/harness, опередивший Orca и т.п.», но подтверждения
   у нас нет: сравнение по пунктам заведено отдельной задачей #503 и ещё не сделано. До её
   результата любая формула превосходства — заявка без доказательства, а публично отозванное
   утверждение дороже ненаписанного.

Отложено, решает юзер: заводить ли свой канал с чатом (совет того же читателя — тогда репост
в чужой канал приходит с меткой своего) и добавлять ли в пост замер нагрузки на человека
(31 сообщение на сессию против 1, см. docs/tasks/502/finding-human-load.md).

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
