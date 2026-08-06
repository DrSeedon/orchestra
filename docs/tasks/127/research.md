# #127 — Гайд Anthropic по Opus 5 против нашего свода правил

**Phase 1 (research). Ничего не правил:** ни `CLAUDE.md`, ни `pipelines/`, ни глобальные файлы.
**Дата снятия источников: 2026-08-06** (доки живые, формулировки могут измениться).
**Способ снятия:** `curl` на `.md`-версию страницы (`<url>.md`) → сырой markdown без пересказа
модели-суммаризатора. Всё, что ниже в блоках цитат, — байты из ответа сервера.

---

## Question (Step 0)

- **Контекст:** свод правил Orchestra, который читают все агенты: глобальный `~/.claude/CLAUDE.md`,
  проектный `CLAUDE.md`, промпты ролей/модулей в `pipelines/default/prompts/`, скиллы.
- **Изменение под проверкой:** пересказ гайда утверждает, что при миграции на Opus 5 главная
  работа — **удалять** правила (самопроверка, инструменты, «делегируй активнее»), плюс добавить
  краткость и дисциплину скоупа.
- **База сравнения:** текущий свод как есть; почти каждое правило про проверку имеет замер в тексте.
- **Измеримый исход:** для каждого утверждения пересказа — подтверждено дословно / искажено /
  отсутствует; для каждой нашей категории правил — резать / оставить / переформулировать, с
  указанием, на чём основано решение.

## Hypotheses considered (Step 1)

| # | Гипотеза | Фальсификатор | Итог |
|---|---|---|---|
| H1 | Гайд действительно велит удалять правила про проверку, включая наши | Найти в тексте различие между «перепроверь свой ответ» и «предъяви артефакт» | **Опровергнута в сильной форме** — гайд бьёт по конкретному классу инструкций, а не по проверке вообще |
| H2 | Пересказ точен по всем пяти пунктам | Найти пункт, которого в обеих страницах нет | **Опровергнута** — пункт про «подробные инструкции по инструментам» отсутствует в обоих источниках |
| H3 | Наш свод набит именно теми инструкциями, которые гайд называет вредными | `grep` по дословным анти-паттернам гайда даёт ноль совпадений | **Опровергнута** — совпадений 2 (и оба не дословные), см. §5 |
| H4 | Рекомендации переносятся на всех наших воркеров | Показать рантайм, где рекомендация Anthropic неприменима | **Подтверждена как ограничение** — Sol/Spark/Grok читают тот же файл через зеркало `AGENTS.md` |

---

## 1. Дословные выдержки из первоисточников

### 1.1 Prompting Claude Opus 5

Источник: <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5>
(снято 2026-08-06, `.md`-версия, 11 225 байт, HTTP 200)

**Общая рамка — прямо противоречит тезису «главное это удалять»:**

> Claude Opus 5 is built for complex agentic coding and enterprise work, with particular strengths
> in long-horizon agentic tasks. **It performs well out of the box on existing Claude Opus 4.8
> prompts.** The following patterns cover the behaviors that most often require tuning.

**§ Task scope and over-verification (ядро всей задачи):**

> Claude Opus 5 verifies its own work without being told to. If your prompt contains explicit
> verification instructions ("include a final verification step for any non-trivial task," "use a
> subagent to verify"), remove them: instructions like these cause over-verification on Claude
> Opus 5, and removing them reduces wasted tokens with no loss in quality. The same applies to
> legacy harness scaffolding that adds separate verification steps.
>
> Claude Opus 5 can also expand the scope of a task, adding steps that weren't requested or
> applying its own judgment about what the task should be. For narrow tasks, constrain scope
> explicitly:
>
> ```
> Deliver what was asked, at the scope intended. Make routine judgment calls yourself, and check
> in only when different readings of the request would lead to materially different work. If the
> request seems mistaken or a better approach exists, say so in a sentence and continue with the
> task as asked rather than quietly narrowing, widening, or transforming it. Finish the whole
> task, and stop short of actions that are clearly beyond what was asked.
> ```

**§ Self-correction:**

> Claude Opus 5 catches and fixes its own mistakes well without prompting. Avoid instructing
> re-checks it already performs ("double-check your answer," "re-verify before responding"); like
> verification instructions, these compound with the model's own behavior and add cost without
> improving results.
>
> The model also narrates corrections to its earlier statements more than prior models do, which
> can be undesirable in user-facing products.

**§ Controlling subagent spawning:**

> Claude Opus 5 delegates to subagents more readily than prior models. Delegation pays off on
> genuinely independent, sizeable tracks of work, but it multiplies cost and time when applied to
> small tasks. If your harness supports subagents, give explicit guidance on which scenarios
> warrant delegation, or set deterministic caps on how many agents can be launched. For example:
>
> ```
> Delegate to a subagent only for large tasks that are genuinely independent and parallelizable,
> such as a wide multi-file investigation. Do not delegate work you can finish yourself in a
> handful of tool calls, and do not use subagents to verify or double-check your own work. If one
> subagent can complete the task, use one rather than several, and keep spawn counts low.
> ```

**§ Response length and verbosity:**

> Claude Opus 5's default user-facing responses run longer than prior Opus models'. The effort
> parameter controls how much the model thinks rather than how much it says: lowering effort can
> reduce thinking volume without reliably shortening the visible response. To control response
> length, prompt for it explicitly.
>
> A short conciseness instruction is effective. […] In a long system prompt, pair the instruction
> with a short reminder near the end of the prompt:
>
> ```
> <tone_preference>
> Keep outputs reasonably concise.
> </tone_preference>
> ```

**§ Written deliverable length (у нас этого класса правил нет вообще — см. §5.4):**

> Separate from conversational verbosity, files that Claude Opus 5 writes to disk (reports,
> Markdown documents, summaries) are often longer than on prior models. If your product includes
> Claude-authored documents, add explicit length calibration:
>
> ```
> Match the length of written documents to what the task needs: cover the substance, but do not
> pad with filler sections, redundant summaries, or boilerplate.
> ```

**§ User-facing progress updates:**

> Claude Opus 5 narrates readily during agentic work: it tends to announce what it is about to do,
> and its per-message output in agentic sessions is often longer than prior models'. […]
> **Positive examples of the communication style you want tend to be more effective than
> instructions about what not to do.**

**§ Code review and bug-finding (важно для нашего ревью-гейта):**

> Claude Opus 5 reviews code with high precision and recall: it finds real bugs at a high rate per
> pass […] Accuracy holds at lower effort settings, which supports a fast pass at review time and
> a more thorough pass later. **If your review prompt says "only report high-severity issues" or
> "be conservative," the model may follow that instruction literally and report less; ask it to
> report everything and filter in a separate pass instead.**

**§ Running with thinking disabled** — единственное место, где упоминается ещё одно удаление:

> If your system prompt contains a rule instructing the model not to think or not to reason,
> remove it; that kind of instruction increases tag leakage.

**Полный список «удалить» на этой странице — четыре пункта, все процитированы выше:**
(1) explicit verification instructions; (2) legacy harness scaffolding с отдельными шагами
верификации; (3) инструкции на re-check собственного ответа; (4) правило «не думай».
Полный список «добавить» — **семь готовых блоков промпта**: краткость, `<tone_preference>`,
каденция апдейтов, длина письменных документов, дисциплина скоупа, потолок делегирования,
поведение при отключённом thinking.

### 1.2 Migration guide

Источник: <https://platform.claude.com/docs/en/about-claude/models/migration-guide>
(снято 2026-08-06, `.md`-версия, 148 590 байт, 2 772 строки, HTTP 200).
Релевантная секция — `### Migrating to Claude Opus 5 from Claude Opus 4.8`, строки 706–793.

**Recommended changes, пункт 6 (строка 779) — единственный prompt-level пункт про удаление:**

> **Remove carried-over verification instructions and constrain scope:** Claude Opus 5 verifies its
> own work without being told to, so remove explicit verification or self-check instructions
> carried over from prompts tuned for earlier models; leaving them in causes over-verification.
> For narrow tasks, constrain the task scope explicitly. In multi-agent frameworks, give explicit
> guidance on which scenarios warrant delegation or cap the number of subagents, because Claude
> Opus 5 delegates more readily than earlier models.

**Recommended changes, пункт 5 (строка 777):**

> **Re-tune length and verbosity prompts:** Default visible responses and written deliverables run
> longer on Claude Opus 5 than on Claude Opus 4.8, and lowering effort reduces thinking volume
> without reliably shortening the visible response. Prompt explicitly for conciseness or a target
> length.

**Из секции для миграции с 4.6 и старше (строка 743) — нюанс, которого нет в 4.8-секции:**

> Re-baseline response length with existing length-control prompts removed, then tune explicitly.

То есть про длину гайд предлагает **снять старые контролы длины, померить базу заново и настроить
явно** — это не «удалить», а «перекалибровать».

**Про эффорт** (`### Recommended changes`, строка 769 + migration checklist, строка 786):

> **Test `max` effort for capability-critical work** […] It can deliver gains on the most demanding
> tasks but may show diminishing returns from increased token usage and can be prone to
> overthinking on simpler ones. If you run at `xhigh` or `max` effort, set a large `max_tokens` […]
> start at 64k tokens and tune from there.
>
> Re-evaluate your `effort` setting: run a fresh effort sweep on your own evals rather than carrying
> over a setting tuned for an earlier model.

Дополнительно, страница Effort (<https://platform.claude.com/docs/en/build-with-claude/effort>,
снято 2026-08-06):

> Claude Opus 5 supports all five effort levels. **Start with `high`, the default** […] step up to
> `xhigh` for demanding coding and agentic work […] use `low` and `medium` liberally as your primary
> control for token cost and response time wherever your evals show quality holds.
>
> Effort controls thinking volume, not visible response length: on Claude Opus 5, changing effort
> does not reliably shorten responses, so prompt for length instead.

Остальные removals в migration guide — **API-уровневые** (beta-хедеры, `temperature`/`top_p`,
prefill, `thinking: {type:"enabled"}`). К нам не относятся: **работаем на подписке через CLI, API
не трогаем** (`CLAUDE.md` → Pricing). Единственное, что нас касается на уровне рантайма, —
пункт про `thinking: disabled` + `xhigh` = 400. У нас `full-cycle` стоит на `effort: xhigh`
(`pipelines/default/pipeline.yaml:71`), thinking включён → конфликта нет; известный локальный
костыль про auto-downgrade `xhigh→high` для Claude (`CLAUDE.md` → Грабли) касается другого случая.

---

## 2. Приговор пересказу — по пунктам

| # | Утверждение пересказа | Вердикт | На чём основано |
|---|---|---|---|
| 0 | «Главная работа при миграции — не добавлять, а УДАЛЯТЬ устаревшие инструкции» | **ИСКАЖЕНО** | В гайде 4 удаления против 7 готовых блоков на добавление, и рамка страницы прямо гласит: *"It performs well out of the box on existing Claude Opus 4.8 prompts"*. «Главная работа = удаление» — акцент пересказчика, в источнике его нет |
| а | Удалять инструкции про самопроверку: модель верифицирует сама, «перепроверь» вызывает овер-верификацию | **ПОДТВЕРЖДЕНО ДОСЛОВНО** | §Task scope and over-verification + §Self-correction + migration guide п.6. Но объём уже́ пересказа: гайд называет конкретные формулировки, а не «инструкции про проверку» вообще — см. §3 |
| б | Удалять подробные инструкции про использование инструментов | **ОТСУТСТВУЕТ В ИСТОЧНИКЕ** | `grep -i tool` по обеим страницам: 7 упоминаний на prompting-странице, ни одно не является рекомендацией сокращать инструкции по инструментам. Про инструменты гайд говорит ровно противоположное в §Vision: *"tool use is a more cost-effective lever than thinking alone"*. В migration guide «tools» фигурируют только как beta про смену тулов в диалоге |
| в | Старые правила «делегируй активнее» устарели, направление перевернулось, Opus 5 нужен потолок | **ПОДТВЕРЖДЕНО ДОСЛОВНО** | §Controlling subagent spawning: *"delegates to subagents more readily than prior models"*, *"set deterministic caps"*. Формулировка про «переворот направления» подтверждается и в 4.6-секции migration guide: 4.7 спавнил МЕНЬШЕ, чем 4.6, а Opus 5 — больше, чем оба |
| г | Лечить многословность явной инструкцией на краткость | **ПОДТВЕРЖДЕНО ДОСЛОВНО** | §Response length and verbosity + §Written deliverable length + migration guide п.5. Уточнение, потерянное в пересказе: у гайда это ДВА разных рычага — видимый ответ и **файлы на диске**; второй у нас не покрыт вообще |
| д | Ставить дисциплину скоупа | **ПОДТВЕРЖДЕНО ДОСЛОВНО** | §Task scope: *"can also expand the scope of a task"* + готовый блок промпта |

**Чего в пересказе нет, а в источнике есть и нас касается:**
1. Правило про ревью: «only report high-severity / be conservative» модель исполнит буквально и
   найдёт меньше → просить полный список и фильтровать отдельным проходом. У нас ровно такой
   калибровочный блок с «"nit" = skip» (`modules/orchestration.md:40-55`) — риск задокументирован.
2. Отдельная калибровка длины **письменных документов** (не чата).
3. Эффорт: `low`/`medium` — основной рычаг цены; свежий sweep вместо унаследованных значений.
4. Позитивные примеры коммуникации работают лучше запретов («не делай X»).

---

## 3. Главное напряжение: овер-верификация текста ≠ предъявление артефакта

Вопрос из постановки: **гайд ругает просьбу перепроверить свой ответ или требование предъявить
доказательство?** Ответ читается прямо из текста, различие проходит по трём признакам.

**Что гайд называет вредным** (дословные примеры из источника):
`"include a final verification step for any non-trivial task"`, `"use a subagent to verify"`,
`"double-check your answer"`, `"re-verify before responding"`, плюс *"legacy harness scaffolding
that adds separate verification steps"*.

У всех пяти общее:
1. **Объект проверки — собственный вывод модели**, а не состояние внешней системы.
2. **Проверка не порождает нового наблюдения**: перечитывание уже написанного, повторный проход по
   тем же токенам. Отсюда и механизм вреда в тексте гайда: *"these compound with the model's own
   behavior and add cost without improving results"* — компаундится ВНУТРЕННЯЯ процедура, которую
   модель и так делает.
3. **Триггер безусловный** («для любой нетривиальной задачи», «перед ответом») — то есть шаг
   выполняется независимо от того, есть ли риск.

**Чего гайд не говорит нигде на обеих страницах:** не требовать прогонять тесты, не показывать
вывод команды, не открывать первоисточник, не считать числа командой. Более того, соседние секции
тянут в противоположную сторону: *"Vision performance is strongest when the model has tools to
iteratively analyze, crop, and **visually verify** its work, and tool use is a more cost-effective
lever than thinking alone"* — то есть **верификация инструментом гайдом поощряется**, а
отговаривается только верификация размышлением.

Отсюда рабочий критерий для нашей ревизии:

> **Порождает ли правило новое наблюдение, которого у модели не было?**
> Да (прогон, grep, чтение первоисточника, diff, замер) → это добыча данных, гайд её не трогает.
> Нет (перечитай, перепроверь, убедись ещё раз, подумай о своём ответе) → это класс, который гайд
> велит удалять.

Разложение наших правил по этому критерию — в §5.1 и в итоговой таблице.

---

## 4. Инвентаризация наших файлов (числа из прогонов)

### 4.1 Что вообще читают агенты

Команда: `python3 /tmp/count127.py` — правило = строка-буллет (`- `, `* `) или нумерованный пункт;
категория = совпадение регулярки по строке. Регулярки приведены в скрипте, счёт сырой (см.
оговорку ниже).

```
file                                                    chars  rules  verify   tools   deleg  verbos   scope
/home/kesha/.claude/CLAUDE.md                            8764     36       1      14       1       0       0
CLAUDE.md (проектный)                                   32815    148      42      36      32       4       1
pipelines/default/prompts/base.md                        6737     29       1       7       7       2       2
pipelines/default/prompts/roles/full-cycle.md           10568     58       6       3       2       0       1
pipelines/default/prompts/roles/orchestrator.md           578      0       0       0       0       0       0
pipelines/default/prompts/roles/sub-orchestrator.md       923      4       0       0       2       0       1
pipelines/default/prompts/roles/worker.md                4322     32       0       4       3       0       2
pipelines/default/prompts/modules/background-jobs.md     1705     14       0       1       0       0       0
pipelines/default/prompts/modules/git-workflow.md        1969     20       0       4       7       0       2
pipelines/default/prompts/modules/memory-search.md       1094      3       0       0       0       0       0
pipelines/default/prompts/modules/orchestration.md      16650     89       6       4      43       1       3
pipelines/default/prompts/modules/report-format.md       1106      1       0       0       0       0       0
pipelines/default/prompts/modules/research-method.md     8658     51       8       0       0       0       0
pipelines/default/prompts/modules/self-improvement.md    6497     20       1       1       3       0       0
pipelines/default/prompts/modules/task-management.md     1822     15       2       0       3       0       0
pipelines/default/prompts/modules/worker-lifecycle.md     967      4       0       0       1       0       0
pipelines/default/prompts/skills/codex-debate.md         8547     39       3       3       1       0       0
pipelines/default/prompts/skills/grill-me.md             4780     36       4       0       0       0       0
pipelines/default/prompts/skills/html-artifacts.md       4356     24       2       0       0       0       0
pipelines/default/prompts/skills/orchestra-agents.md     7780     12       1       0       2       0       0
pipelines/default/prompts/skills/vps-deploy.md           2115      9       1       0       1       0       0
TOTAL                                                  132753    644      78      77     108       7      12
```

**Оговорка о методе, обязательная к прочтению перед использованием этих чисел:** колонки — это
совпадения по ключевым словам, а не смысловая классификация. Колонка `deleg=43` у
`orchestration.md` — это в основном механика управления воркерами (spawn/merge/kill/branch), а не
призывы делегировать; колонка `verify=42` у `CLAUDE.md` включает всё, где встретилось слово
«провер»/«тест»/«замер». Ручная классификация верификационных правил — в §5.1, и именно она
основание для решений, а не эта таблица.

### 4.2 Эффективный размер промпта на роль

Команда: конкатенация слоёв из `pipeline.yaml` + `wc -c`.

| Роль | Слои `pipelines/` | + проектный `CLAUDE.md` | + глобальный | Итого |
|---|---:|---:|---:|---:|
| orchestrator | 38 577 B | 51 526 B | 13 867 B | **103 970 B** |
| worker | 22 020 B | 51 526 B | 13 867 B | **87 413 B** |
| full-cycle | 38 120 B | 51 526 B | 13 867 B | **103 513 B** |

Тела скиллов сюда не входят: в промпт идёт сгенерированное оглавление, тело агент читает сам
(зафиксировано в `CLAUDE.md` → Грабли, замер 10 424 → 1 080 символов).

### 4.3 Структура проектного `CLAUDE.md` (148 правил / 32 751 символ / 51 526 байт)

| Секция | Правил | Символов | Доля файла |
|---|---:|---:|---:|
| 🪤 Грабли | 72 | 17 903 | **55 %** |
| ✅ ПРОВЕРЬ ПЕРЕД РАБОТОЙ | 10 | 3 876 | 12 % |
| ⚡ PROCESS RULES | 7 | 1 796 | 5 % |
| AI Efficiency | 11 | 1 362 | 4 % |
| Принципы | 11 | 1 338 | 4 % |
| 🔌 ПРОКСИ | 9 | 1 287 | 4 % |
| Agent Determinism | 8 | 1 187 | 4 % |
| Pricing | 7 | 1 036 | 3 % |
| остальные 7 секций | 13 | 2 966 | 9 % |

Разбивка «Граблей» по подблокам:

```
 14 rules   3328 chars  Проверка и доказательства
 12 rules   2305 chars  Codex / Sol
  9 rules   2134 chars  Тесты
  9 rules   2497 chars  Git, файлы, деплой
  6 rules   2240 chars  Shared runtime
  6 rules   1716 chars  Дубли и рассинхрон
  6 rules   1537 chars  Чужая машина
  6 rules    923 chars  Воркеры и оркестрация
  4 rules    945 chars  Модели и лимиты
```

---

## 5. Разбор по пяти категориям гайда

### 5.1 Самопроверка — что у нас реально есть

**Прогон по дословным анти-паттернам гайда** (`grep -rniE "double[- ]?check|re-?verify|verify (your|before)|final verification|verification step|self-check|перепровер|ещё раз провер"` по `CLAUDE.md`, `pipelines/`, глобальному файлу):

**Одно совпадение, и оно ложное** — `CLAUDE.md:178`: «править при остановленном сервере и
ПЕРЕПРОВЕРЯТЬ после рестарта». Объект проверки — состояние БД после рестарта чужого процесса, а не
собственный ответ модели. По критерию §3 это добыча наблюдения.

**Прогон по self-review** (`grep -rniE "self-review|adversarial self|self-verif|самопровер"`) — три
попадания, и вот они действительно в зоне гайда:

| Файл:строка | Текст | Класс |
|---|---|---|
| `roles/worker.md:34` | «**Adversarial self-review.** Before committing, find 2-3 potential bugs or weak spots in your own code. Fix them or flag them in your DONE report.» | **Ровно то, что гайд велит удалять**: объект — собственный вывод, нового наблюдения не порождает, триггер безусловный |
| `roles/full-cycle.md:143` | тот же текст, дубль | то же |
| `roles/full-cycle.md:83` | «After each ticket: check it against its AC (self-verify). If AC fails — fix before moving on.» | Пограничное: AC проверяются прогоном (артефакт), но формулировка «self-verify» приглашает перечитывание |

**Итого: из 78 «верификационных» строк по грепу к классу гайда относятся 2 (плюс 1 пограничная).**
Остальные — три других класса, которых гайд не касается:

1. **Предъявление артефакта** (~30 правил: «Verify artifact, not narrative», «проверять артефакт, а
   не рассказ», «числа из выполненной команды», «мутационная проверка», «прогони ещё 3 раза на
   асинхронном коде», «не цитируй источник, который не открывал»). Каждое порождает новое
   наблюдение. Замеры в тексте самих правил: мутация 5/20 → 15/20 (p=0.0039); 3 из 12 находок
   протухли; самопроверка таблицы вскрыла 3 ошибки в 3 строках; 2 дефекта из 3 нашлись только
   повторным прогоном асинхронного теста.
2. **Проверка предпосылки ДО работы** (10 правил секции «ПРОВЕРЬ ПЕРЕД РАБОТОЙ»: `git log -S` по
   символу, `git check-ignore` на путь из задания, свой шум метрики перед сравнением). Это не
   верификация ответа, а отсечение работы, которая не нужна. Замер: задача #114 закрыта без единой
   правки, потому что фикс уже был в main.
3. **Методология измерения** (шум метрики, порог из пилота, далёкая предметная область, split-half).
   Гайд про это не говорит ничего.

**Вывод по категории:** пересказ в этом месте верен по букве и опасен по объёму. Если применить его
буквально ко всем 78 строкам, мы удалим правила, у которых есть измеренный эффект, ради экономии,
которую гайд обещает только для другого класса инструкций. Резать здесь нужно **две строки, а не
секцию.**

### 5.2 Инструменты

Пункт пересказа отсутствует в источнике (§2). Отдельно: наши 77 «tool»-строк — это в основном
маршрутизация («какой инструмент для чего», «WebSearch первым, Perplexity потом») и запреты
(`rm -rf`, встроенный Agent, `run_in_background`). Гайд не даёт основания их трогать. Более того,
наш запрет на встроенный `Agent` совпадает с рекомендацией гайда *"do not use subagents to verify
or double-check your own work"*, только у нас он жёстче — запрещён вообще.

Замер по логам: за 03–06.08 в живой БД **1 287 записей `subagents`, у всех `task_type = local_bash`**
— то есть фоновые шеллы, а не Task-субагенты. Реальных субагент-делегирований через встроенный тул
ноль. Правило соблюдается.

### 5.3 Делегирование — здесь у нас прямое противоречие с гайдом

Три места толкают агента делегировать больше:

| Файл | Текст | Отношение к гайду |
|---|---|---|
| `modules/orchestration.md:12-15` | «**Step 0.5: Delegate or DIY? (MANDATORY gate).** DIY only when **all** are true: […] Otherwise delegate; **hesitation means the gate failed**» | Противонаправлено. Гайд: *"Do not delegate work you can finish yourself in a handful of tool calls"* |
| `CLAUDE.md` → PROCESS RULES | «Задача появилась → сразу в работу, максимально параллельно. Все воркеры заняты — **спавнить нового**, а НЕ ставить в очередь» | Противонаправлено: явное поощрение роста числа агентов, потолка нет |
| `roles/full-cycle.md` → `<parallelism>` | «Phase 1 research with natural splits → `spawn_worker` 2-3 `worker`-role agents» | Совпадает с гайдом: широкое многофайловое исследование — как раз тот случай, ради которого делегирование окупается. Потолок «2-3» уже стоит |

**Цена делегирования, замер по `turn_usage` (VPS, 03–06.08.2026, покрытие полное — таблица ведётся
с 03.08 06:33):**

| Роль | Сессий | Ходов | Средне ходов | Стоимость (API-equivalent) |
|---|---:|---:|---:|---:|
| worker | 37 | 271 | 7.3 | $796.16 |
| full-cycle | 11 | 178 | 16.2 | $567.38 |
| orchestrator | 4 | 450 | 112.5 | $415.66 |
| sub-orchestrator | 1 | 58 | 58.0 | $36.82 |

Из 48 воркер-сессий **31 прожила ≤3 ходов, суммарно $133.24, в среднем 1.6 хода на сессию**
(≈$4.3 за сессию). Честная оговорка: малое число ходов ≠ пустая работа — один ход Opus 5 может
закрыть задачу целиком (`fix-spawn`: 1 ход, $4.77, задача закрыта). Правильный вывод не «эти
делегирования были лишними», а «**нижняя планка цены делегирования — единицы долларов на сессию,
и она не зависит от размера задачи**»: каждый спавн заново оплачивает ~87–104 КБ промпта. Это ровно
тот механизм, из-за которого гайд советует ставить потолок.

### 5.4 Многословность

- Для **чата** правила есть: `<communication-style>` в `base.md` («Brevity. Don't narrate your tool
  calls»), PROCESS RULES в `CLAUDE.md` («КРАТКОСТЬ — не лей воду»). Совпадает с рекомендацией
  гайда, менять нечего.
- Для **письменных документов правил нет ни одного.** Прогон
  `grep -rniE "filler|padding|boilerplate|match the length|длину документ"` по `CLAUDE.md` и
  `pipelines/` даёт единственное релевантное попадание — `self-improvement.md:98` «Aim for a
  30-second reread», и оно про личный файл памяти воркера, а не про артефакты задач.
- Замер по репозиторию: **259 файлов `docs/tasks/*/{research,report}.md` в main, медиана 10 252 B,
  максимум 61 802 B** (`docs/tasks/3/research.md`). Пять документов больше 52 КБ.

Это **пропуск, а не избыток**: гайд рекомендует добавить калибровку длины письменных артефактов, у
нас её нет, а артефакты — основной продукт `full-cycle`.

### 5.5 Скоуп

Есть и совпадает по духу: «Хирургические правки» (глобальный файл), `<code-quality>` → *"Surgical
changes. Touch ONLY what the task requires"* (`roles/worker.md`, `roles/full-cycle.md`), «Лесенка
перед тем как писать код», «Минимум кода». Чего нет — второй половины формулировки гайда: *"Finish
the whole task"* и *"rather than quietly narrowing"*. Наши правила защищают от расширения скоупа и
молчат про **сужение**. Это кандидат на дополнение одной фразой, не на резку.

---

## 6. Мультирантайм — что нельзя резать «для всех»

Механика, проверенная по коду, а не по памяти:

- `app/workspace.py:400` `sync_agents_md()` — **байт-в-байт копия проектного `CLAUDE.md` →
  `AGENTS.md`** в воркtree, обновляется при каждом (ре)коннекте бэкенда
  (`app/session.py:921-927`). Трекнутый репозиторием `AGENTS.md` не перезаписывается.
- `~/.codex/config.toml` на этом VPS: `project_doc_max_bytes = 65536`. Проектный `CLAUDE.md` =
  **51 526 байт → влезает, запас 14 010 байт (использовано 78.6 %)**. Резать ради лимита сейчас не
  требуется, но запас невелик, а кириллица стоит 2 байта на символ.
- Состав рантаймов по архиву (ноутбук, снимок 03.08.2026): 166 сессий `claude-opus-5[1m]`,
  **94 `gpt-5.6-sol`**, 27 `claude-sonnet-5[1m]`, 18 `claude-sonnet-4-6`, 6 `claude-fable-5[1m]`,
  2 `gpt-5.3-codex-spark`, 1 `grok-4.5`. То есть **не-Anthropic рантаймы — это ~35 % истории**, не
  экзотика.

**Прямой ответ на вопрос задачи.** Рекомендация Anthropic — утверждение о поведении ИХ модели
(«Opus 5 verifies its own work without being told to»). На `gpt-5.6-sol`, `spark` и `grok-4.5`
она не проверена никем: ни Anthropic (не их модель), ни нами (замера нет).

- **Безопасно резать для всех:** только то, что вредно или бессмысленно независимо от рантайма —
  дубликат `Adversarial self-review` в двух файлах имеет смысл свести к одному месту в любом случае.
- **Резать только для Claude-ролей, не для зеркала:** нельзя технически. Зеркало — байтовая копия
  одного файла; отдельной «claude-only» секции в нём не существует. Значит любая резка правил
  самопроверки в проектном `CLAUDE.md` **автоматически применяется к Sol/Spark/Grok**, для которых
  основания нет.
- **Держат качество у не-Anthropic рантаймов и потому не режутся:** правила «предъяви артефакт» и
  «проверь предпосылку» (§5.1, классы 1–3). Наш собственный замер против них: в A/B финальное
  ревью на Spark пропустило реальный double-count, который поймал Sol (`CLAUDE.md` → Грабли,
  «Модели и лимиты»); Codex жжёт время в `sleep` и ретраит на исчерпанной квоте, что лечится
  явными правилами, а не доверием к самокоррекции.
- **Практический вывод:** если резать, то в `pipelines/default/prompts/roles/*.md` (эти файлы
  собираются на роль и в `AGENTS.md` **не** зеркалятся), а не в проектном `CLAUDE.md`. Обе строки
  `Adversarial self-review` лежат именно в `roles/` — то есть самое дорогое по гайду удаление
  делается там, где оно не задевает чужие рантаймы. Это удача, а не общее правило.

---

## 7. Есть ли у нас следы овер-верификации и разбухания (отрицательные результаты)

**Сразу об ограничении, которое обесценивает половину напрашивающихся сравнений:** контрольной
группы «до Opus 5» у нас **нет**. Распределение моделей по 314 сессиям холодного архива (ноутбук,
снимок 03.08.2026): `claude-opus-4*` — **0 сессий**. Живая БД: 53 сессии, из них 1 на
`claude-opus-4-8[1m]` и 1 на `claude-haiku-4-5`. Весь наш корпус — уже Opus 5. Поэтому «стало ли
хуже после Opus 5» на нашем материале **не измеримо в принципе**; ниже только абсолютные замеры.

**Замер 1 — повторные вызовы одного и того же инструмента внутри хода** (живая БД, все сессии
`claude-opus-5%`, ход = отрезок между `user_message`):

```
turns=1053  tool_calls=10950  mean=10.4/ход  median=5
turns_with_dup=193 (18.3%)  dup_calls=955 (8.7% всех вызовов)
дубли по инструментам: Edit 804, Bash 155, Read 128, Write 5
```

Разбор дублей по существу: **84 % — это `Edit` одного и того же файла** (итеративная правка, а не
проверка). При более строгом ключе (первые 200 символов команды вместо 120) дублей `Bash` — 53, из
них **верификационных по форме** (`git status|git log|git diff|pytest|grep|wc|ls|cat|head|tail|sqlite3`)
— **22, то есть 0.2 % от 10 950 вызовов.**

**Вывод: следов овер-верификации в виде повторного прогона одного и того же в логах нет.** 0.2 % —
это шум, и самый частый случай (3 повтора) — повторный `pytest` после правки, то есть законный
повторный прогон, а не перечитывание.

**Замер 2 — разбухание письменных артефактов.** 259 файлов `research.md`/`report.md` в main,
медиана 10 252 B, среднее по дате первого коммита: до 03.08 — 15 176 B (145 файлов), после — 13 143 B
(114 файлов). Разница **в сторону уменьшения**, но интерпретировать её как эффект чего-либо нельзя:
обе группы написаны Opus 5 (см. выше), состав задач разный, а 03.08 — дата переноса контура, а не
смены модели. **Честный вывод: разбухание артефактов у нас есть в абсолютных числах (пять файлов
> 52 КБ, максимум 61.8 КБ), но приписать его модели нечем.**

**Замер 3 — субагенты-верификаторы:** ноль (§5.2).

Итог раздела: **из трёх проверенных следов подтверждён один (абсолютный размер артефактов), два
отрицательных.** Овер-верификация как повторный прогон в наших логах не обнаружена.

---

## 8. Counter-evidence — что аргументирует против моих же выводов

1. **Мой замер повторов не ловит главный механизм из гайда.** Гайд говорит о лишних *шагах*
   верификации (лишний проход, лишний ход), а я мерил *дословные повторы одного вызова внутри
   хода*. Ход, целиком потраченный на «ещё раз проверю», в моей метрике невидим. Значит «следов
   нет» = «следов ЭТОГО вида нет», а не «овер-верификации нет». Понижаю уверенность до LIKELY.
2. **Наши замеры получены под нашим текущим сводом, а не в сравнении с его отсутствием.** Правило
   «мутация спасала 5/20 → 15/20» доказывает, что формулировка правила лучше другой формулировки,
   но **не** доказывает, что без правила Opus 5 справился бы хуже. Ни один наш замер не является
   A/B «правило есть / правила нет» на Opus 5. Это ослабляет аргумент «у нас есть замеры, они
   старше пересказа» — они старше, но отвечают на другой вопрос.
3. **Гайд может быть прав шире, чем я признаю.** Формулировка *"legacy harness scaffolding that
   adds separate verification steps"* достаточно широка, чтобы накрыть и наш Codex-гейт, и
   пофазовые гейты `full-cycle`. Я толкую её узко (Codex — другая модель, значит настоящее второе
   мнение, а не самопроверка), и это толкование не подтверждено источником.
4. **Anthropic — заинтересованная сторона.** Рекомендация «удалите ваши проверки, модель проверяет
   сама» исходит от продавца модели и не сопровождается ни числами, ни методикой. Тир источника —
   первичный (тир 2 по нашей шкале), но не измерение. Наши правила про артефакты опираются на тир 1
   (собственные прогоны). При конфликте тир 1 бьёт тир 2 — и именно поэтому §5.1 рекомендует резать
   2 строки, а не 30.
5. **Против пункта «краткость»:** гайд сам предупреждает, что позитивные примеры работают лучше
   запретов, а у нас в PROCESS RULES краткость оформлена набором запретов («НЕ пересказывай», «НЕ
   дублируй», «НЕ объясняй»). То есть в категории, где мы «уже совпадаем с гайдом», форма как раз
   не оптимальна.

---

## 9. Итоговая таблица: правило → категория → решение → основание

| # | Правило (файл) | Категория | Решение | На чём основано |
|---|---|---|---|---|
| 1 | `Adversarial self-review. Before committing, find 2-3 potential bugs…` — `roles/worker.md:34` | самопроверка | **РЕЗАТЬ** | Дословный класс из §Self-correction: объект — свой вывод, нового наблюдения нет, триггер безусловный. В `roles/`, зеркала `AGENTS.md` не касается |
| 2 | то же, дубль — `roles/full-cycle.md:143` | самопроверка | **РЕЗАТЬ** | То же + наше правило «одна мысль = один owner» |
| 3 | `After each ticket: check it against its AC (self-verify)` — `roles/full-cycle.md:83` | самопроверка | **ПЕРЕФОРМУЛИРОВАТЬ** | AC-проверка порождает артефакт (прогон), но слово self-verify приглашает перечитывание. Заменить на «AC подтверждается прогоном/выводом команды» |
| 4 | 14 правил «Проверка и доказательства» (`CLAUDE.md`, 3 328 симв.) | самопроверка (по грепу) / фактически артефакт | **ОСТАВИТЬ** | По критерию §3 порождают наблюдение; гайд их не называет. Тир 1 замеры в самих правилах. Зеркалятся в `AGENTS.md` для Sol/Spark/Grok, где рекомендация Anthropic не проверена |
| 5 | 10 правил «ПРОВЕРЬ ПЕРЕД РАБОТОЙ» (`CLAUDE.md`, 3 876 симв.) | скоуп/предпосылка, не самопроверка | **ОСТАВИТЬ** | Проверяют предпосылку ДО работы, а не ответ ПОСЛЕ. Замер: #114 закрыт без правок. Совпадает с духом §Task scope |
| 6 | `research-method` Steps 3–5 (тиры источников, контр-поиск, эксперимент) | самопроверка (по грепу) / метод | **ОСТАВИТЬ** | Про добычу и ранжирование внешних данных; в гайде нет ни слова против |
| 7 | `Step 0.5: Delegate or DIY? … hesitation means the gate failed` — `modules/orchestration.md:12` | делегирование | **ПЕРЕФОРМУЛИРОВАТЬ** | Прямо противоположно §Controlling subagent spawning. Добавить обратную сторону: не делегировать то, что закрывается несколькими вызовами инструментов. Замер: 31 сессия ≤3 ходов, $133, нижняя планка ≈$4.3/сессия |
| 8 | `Все воркеры заняты — спавнить нового, а НЕ ставить в очередь` — `CLAUDE.md` PROCESS RULES | делегирование | **ПЕРЕФОРМУЛИРОВАТЬ** | То же + гайд советует детерминированный потолок. Файл зеркалится → правку формулировать нейтрально к рантайму |
| 9 | `<parallelism>` 2-3 воркера на research — `roles/full-cycle.md` | делегирование | **ОСТАВИТЬ** | Совпадает с гайдом дословно: широкое многофайловое исследование + потолок уже стоит |
| 10 | Запрет встроенного `Agent`/`SendMessage` — `base.md` | делегирование/инструменты | **ОСТАВИТЬ** | Строже гайда и в ту же сторону (*"do not use subagents to verify"*). Замер: 1 287 записей `subagents`, все `local_bash` |
| 11 | Отсутствует: калибровка длины письменных артефактов | многословность | **ДОБАВИТЬ** | §Written deliverable length + замер: медиана 10.3 КБ, максимум 61.8 КБ, 5 файлов > 52 КБ, правила нет ни одного |
| 12 | `КРАТКОСТЬ — не лей воду` (PROCESS RULES) + `<communication-style>` (`base.md`) | многословность | **ОСТАВИТЬ, форму переформулировать** | Гайд: позитивные примеры эффективнее запретов; у нас пять «НЕ» подряд |
| 13 | `Surgical changes` / «Хирургические правки» | скоуп | **ОСТАВИТЬ + дополнить** | Совпадает; не хватает второй половины гайда — «не сужай молча, доводи задачу до конца» |
| 14 | Калибровочный блок ревью с `"nit" = skip` — `modules/orchestration.md:40-55` | инструменты/ревью | **ПРОВЕРИТЬ ОТДЕЛЬНО** | §Code review: инструкция «be conservative» исполняется буквально и снижает находимость. Наш блок близок по форме; нужен замер, а не правка вслепую |
| 15 | 77 строк про инструменты (маршрутизация, запреты) | инструменты | **ОСТАВИТЬ** | Пункт пересказа отсутствует в обоих источниках; гайд про инструменты высказывается положительно |
| 16 | `effort: xhigh` у `full-cycle`, `medium` у оркестратора (`pipeline.yaml`) | эффорт | **ПРОВЕРИТЬ ОТДЕЛЬНО** | Гайд требует свежий sweep, а не унаследованные значения; `low`/`medium` — основной рычаг цены. Это отдельная задача с замером, не правка промпта |

**Предварительный размер того, что реально стоит резать:** 2 строки (~330 байт) на удаление,
5 позиций на переформулировку, 1 на добавление. Это **менее 0.5 %** от 132 753 символов свода.
Пересказ обещал ревизию, источник даёт точечную правку.

---

## 10. Состязательная самопроверка (вместо Codex — квота выбрана до 08.08)

Проверял свои же выводы на четыре типовые ошибки из нашего свода.

1. **«Числа из выполненной команды, а не из впечатления».** Перепроверил три числа таблиц: размер
   `CLAUDE.md` — 51 526 байт / 32 815 символов (различие байт/символ из-за кириллицы, в §4.1 стоят
   символы, в §4.2 и §6 — байты; помечено явно). 78 «verify»-строк — это греп-совпадения, а не
   правила про самопроверку; в §4.1 добавлена оговорка, потому что без неё число читалось бы как
   «78 правил под нож». Дубли `Bash`: при ключе 120 символов — 155, при 200 — 53; в тексте оставлен
   строгий вариант с явным указанием причины расхождения.
2. **«Проверка, дающая одинаковый вывод при успехе и провале, — не проверка».** Греп по
   анти-паттернам мог дать ноль просто потому, что у нас всё написано по-русски. Прогнал вторым
   заходом русские формы («перепровер», «ещё раз провер», «самопровер») — результат тот же: 1 ложное
   совпадение + 3 по `self-review`. Проверка различающая.
3. **«Далёкая область против выборочного эффекта».** Классификация «артефакт против перечитывания»
   выведена на разделе про проверку; прогнал её на чужом материале — на секции «Чужая машина»
   (6 правил про память ноутбука). Все шесть — про добычу наблюдения (`MemAvailable` из
   `/proc/meminfo` вместо `free`, `findmnt /tmp`, `pgrep -af`). Критерий не разваливается на далёкой
   области, но и не различает там ничего интересного — он полезен только внутри верификационного
   класса.
4. **Самое слабое место работы, названное прямо.** Ключевой вывод («резать 2 строки, а не секцию»)
   опирается на **толкование** различия между самопроверкой и предъявлением артефакта. Толкование
   выведено из текста гайда (§3), но **гайд этого различия не проводит явно** — он перечисляет
   примеры, а обобщение сделал я. Если Anthropic имели в виду шире (все навязанные шаги проверки,
   включая прогоны), правильный ответ ближе к пересказу, чем к моему. Проверяется это только
   замером: A/B `full-cycle` с секцией «Проверка и доказательства» и без неё на одинаковом наборе
   заданий. Такого замера нет ни у нас, ни у Anthropic — и до него любая массовая резка будет
   решением на веру.

---

## 11. Confidence по выводам

| Вывод | Уверенность | Причина, привязанная к тиру |
|---|---|---|
| Пункт (б) пересказа (инструменты) отсутствует в источнике | **CONFIRMED** | Тир 2 (первоисточник) + исчерпывающий греп по обеим страницам |
| Пункты (а), (в), (г), (д) подтверждены дословно | **CONFIRMED** | Тир 2, цитаты приведены целиком |
| «Главная работа — удалять» — искажение акцента | **CONFIRMED** | Тир 2: счёт 4 удаления против 7 блоков на добавление + рамочная фраза про out of the box |
| Гайд бьёт по самопроверке текста, а не по предъявлению артефакта | **LIKELY** | Тир 2, но обобщение моё: гайд даёт примеры, а не определение (см. §10.4) |
| Овер-верификации как повторных прогонов в наших логах нет | **LIKELY** | Тир 1 (собственный замер 10 950 вызовов), но метрика не ловит лишние *ходы* (§8.1) |
| Делегирование у нас поощряется сильнее, чем рекомендует гайд | **CONFIRMED** | Тир 2 (цитата) + тир 1 (текст трёх наших правил + $133 на 31 короткой сессии) |
| Калибровки длины письменных артефактов у нас нет | **CONFIRMED** | Тир 1: греп по всем файлам + распределение 259 документов |
| Резать правила про артефакты опасно для не-Anthropic рантаймов | **LIKELY** | Тир 1 (механика зеркала в коде, 35 % не-Anthropic сессий) + отсутствие какого-либо замера для Sol/Spark/Grok |
| Контрольной группы «до Opus 5» у нас не существует | **CONFIRMED** | Тир 1: 0 сессий `claude-opus-4*` в архиве из 314 |

---

## 12. Затронутые файлы, риски, edge cases (для возможной Phase 2)

**Файлы под правку (если она будет одобрена):**
- `pipelines/default/prompts/roles/worker.md` — 1 строка на удаление
- `pipelines/default/prompts/roles/full-cycle.md` — 1 строка на удаление, 1 на переформулировку,
  1 добавление (длина артефактов)
- `pipelines/default/prompts/modules/orchestration.md` — Step 0.5, обратная сторона гейта
- `CLAUDE.md` — PROCESS RULES (потолок параллельности); **правка зеркалится в `AGENTS.md`**

**Риски:**
1. Любая правка `CLAUDE.md` мгновенно доезжает до Codex-воркеров при реконнекте (байтовая копия) —
   формулировки должны быть нейтральны к рантайму.
2. `pipelines/*/prompts/` и `CLAUDE.md` расходятся при односторонней правке — известные грабли
   («Правило в `CLAUDE.md` и промпт роли в `pipelines/` расходятся → воркер слушается ПРОМПТА»).
   Правки про делегирование затрагивают оба слоя, синхронизировать обязательно.
3. Удаление `Adversarial self-review` снимает единственную явную инструкцию искать баги в своём коде
   перед коммитом. Гайд утверждает, что модель делает это сама. У нас этого замера нет — если
   резать, стоит зафиксировать дату и следить за долей возвратов на доработку.
4. Запас до `project_doc_max_bytes` — 14 010 байт (21 %). Любое добавление в `CLAUDE.md` его ест.

**Что НЕ трогать:** глобальный `~/.claude/CLAUDE.md` (решение юзера), секцию «Грабли» целиком,
`research-method`, правила предъявления артефакта.

---

## Sources

Все три URL открыты лично в этой сессии 2026-08-06 через `curl` (`.md`-версии, HTTP 200), сырой
markdown сохранён локально.

1. **Prompting Claude Opus 5** — <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5>
   (11 225 B). *Тир 2 — первичная документация вендора.*
2. **Migration guide** — <https://platform.claude.com/docs/en/about-claude/models/migration-guide>
   (148 590 B, 2 772 строки; релевантна секция «Migrating to Claude Opus 5 from Claude Opus 4.8»,
   строки 706–793). *Тир 2.*
3. **Effort** — <https://platform.claude.com/docs/en/build-with-claude/effort> (21 987 B).
   *Тир 2.* Не был в пересказе, привлечён из-за ссылок гайда.

**Измерения (тир 1, все проведены в этой сессии):** `/home/kesha/orchestra/data/orchestra.db`
(копия `/tmp/o127.db`, read-only) — `turn_usage`, `logs`, `sessions`, `subagents`;
`/home/kesha/orchestra-archive/` — 314 JSON-сессий; `git ls-files` + `git log` по
`docs/tasks/*/{research,report}.md` в `main`; `~/.codex/config.toml`; `app/workspace.py`,
`app/session.py`.
