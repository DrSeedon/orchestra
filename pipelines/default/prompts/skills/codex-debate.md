---
name: codex-debate
description: "Optional risk-based review routing: deterministic skip, Luna first pass, Sol technical escalation, and evidence-backed debate. Luna and Sol run through codex_review; no Codex means no review. Triggers: 'review', 'кодекс ревью', 'второе мнение', 'cross-review', 'adversarial review', '/codex', '/codex-debate'."
---

# Review Routing and Codex Debate

## Typed knowledge contract

- Use the single `knowledge` tool for canonical knowledge and evidence operations.
- Request progressive detail as `summary` < `record` < `evidence`.
- Use typed `orch://` identifiers for task, fact, evidence, session, resource, and skill references.
- Markdown files, SQLite, FTS, and vector hits are never independent truth.
- Historical Markdown and session archives are immutable cold evidence and are never regenerated.
- Canonical task, fact, evidence-reference, and session events are structured Git JSON.

Этот файл — единственный владелец выбора reviewer, доказательств для skip и потолка раундов.
`codex_review` запускает Luna или Sol в явном reviewer model. Другого ревьюера у нас нет:
ревью существует ровно настолько, насколько доступен Codex.
Основание маршрута и его границы измерений: `docs/tasks/289/research.md`.

## Главный принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА
Reviewer — дополнительный sensor, не oracle. Он часто прав, но **не всегда**:
- **Прислушивайся** к каждому замечанию
- **Проверяй** blocking-замечания через код (`grep`/`cat`/read) **перед** тем как принять
- **Спорь** если не согласен — resume сессии с контраргументами из кода (не молча игнорь)
- **Эскалируй** если reviewer просит удалить функционал или сменить архитектуру
- **Не соглашайся слепо** — это обесценивает review

**Кому эскалировать.** Ты общаешься с тем, кто дал тебе задачу: worker/full-cycle — своему
оркестратору (или отправителю `[from:X]`) через `send_message`; оркестратор — юзеру. Воркер
не пишет юзеру напрямую и не выводит вопрос в обычный чат.

Формат: "Reviewer говорит X. Я проверил — [согласен / не согласен потому что Y]. Нужно решение."

## Review decision gate — canonical policy

Перед review/skip запиши в отчёт четыре входа: изменённые файлы и consumers; author model/runtime
из metadata сессии, не из имени агента; точный AC; named test/check command и его фактический
вывод. **The author never self-certifies risk or oracle strength**: автор может поднять риск, но
не понизить floor, заданный затронутой поверхностью. Слова `trivial`, `low-risk`, `strong oracle`
без этих проверяемых входов не открывают дешёвый маршрут.

**Strong independent deterministic oracle** — заранее существовавший или замороженный до
реализации named test/AC, чья команда даёт однозначный pass/fail и механически покрывает каждый
критичный критерий. Тест, написанный после реализации, self-review, «дифф выглядит безопасно» и
неназванный ручной просмотр не являются таким oracle. Нет exact command + observed output + AC →
oracle слабый.

**High-risk is evidence-derived, not author-declared.** Floor взводится из перечисленных changed
consumers, если затронут хотя бы один класс: shared process/session/message delivery, queue/lock/
concurrency; auth/permissions/security/secrets; persistence schema/migration или irreversible/
destructive/data-loss path; externally consumed API/schema/protocol/compatibility contract; review/
admission/authorization/lifecycle gate, чей bypass отключает контроль. Явная классификация задачи
оркестратором тоже взводит floor. Автор может добавить класс риска, но не снять сработавший; неясны
consumer или последствия → high-risk до решения независимого reviewer/оркестратора.

**Ревью доступно, но не обязательно (решение юзера 19.08.2026).** Есть Codex — ревью полезно и
маршруты ниже говорят, какое именно. **Codex недоступен → ревью НЕ делается: пиши в отчёт
`Review: none — Codex unavailable` и продолжай работу.** Замену ревьюеру не искать: не поднимать
Opus, не спавнить ревьюера-агента, не звать другую модель «вместо». Отсутствие ревью — законный
исход, а не долг; вместо него отчёт опирается на собственную самопроверку (pre-mortem, мутации
оракула) и на просмотр диффа тем, кто ставил задачу. Раньше здесь стоял обязательный floor и
маршрут «поднять Opus вместо Codex» — оба сняты: они стоили четырёх платных ревьюеров за день,
которых юзер не заказывал.

**Authorization for auxiliary reviewers (решение юзера 23.08.2026).** Внутри уже одобренной
задачи дополнительный Luna-review разрешён автоматически. Любой Sol-review — отдельный дорогой
model run и требует явного разрешения пользователя именно на дополнительный Sol-вызов; одобрение
самой задачи, ресёрча, реализации или review вообще таким разрешением не является. Маршруты ниже,
которые рекомендуют Sol, определяют технически желательного reviewer, но не дают permission.
Нет явного Sol-апрува → используй один Luna pass, если он полезен, либо `Review: none — Sol not
authorized`; не запускай Sol и не проси его постфактум одобрить уже готовый артефакт.

Применяй сверху вниз, ЕСЛИ Codex доступен; более высокий risk floor побеждает дешёвый маршрут:

1. **NO MODEL REVIEW** — только trivial fully closed leaf: точные file/symbol и AC известны до
   работы, неизвестных решений и внешних контрактов нет, diff не затрагивает high-risk floor,
   strong independent deterministic oracle зелёный. В отчёте обязательны command, output и AC;
   без них skip запрещён.
2. **one fresh Luna review** — low/medium compact diff со strong oracle. `Compact` означает:
   поверхность ограничена названными symbols/files, все изменённые consumers перечислены, нет
   открытого state/schema/security решения. Ровно один first pass, не серия «до чистоты».
3. **one targeted Sol escalation** — Luna дала blocker, uncertainty по обязательному свойству
   или schema mismatch. Проверь finding, при принятом blocker измени artifact, затем передай Sol
   только этот seam/спор; Luna второй раз не запускай. Иди сразу в один targeted Sol technical
   pass без Luna, если strong oracle отсутствует, diff не compact или high-risk floor выше
   сработал.
4. **Sol pass on a high-risk surface** — shared runtime, auth, security, secrets, migrations.
   Малый diff и зелёный тест сами по себе не переводят такой diff на дешёвый маршрут; Luna здесь
   не gate. Это выбор МАРШРУТА при доступном Codex, а не обязанность провести ревью: Codex нет —
   см. правило выше, ревью не делается и замена не поднимается.
5. **Docs / fact extraction** — сначала mechanical completeness checks. Для короткой
   low-consequence fact extraction они могут быть финальным gate; иначе один Luna completeness
   pass. Causal/statistical спор или high-risk вывод поднимается по правилам выше.

### Как запустить выбранный маршрут

- Luna запускается напрямую через `codex_review(model="gpt5.6luna", ...)`; Sol — через
  `model="codex"`. Устаревший вызов без `model` детерминированно остаётся Sol.
- `codex_review` принимает только зарегистрированные модели Codex runtime; Spark запрещён для
  review политикой.
- Выбранный reviewer недоступен → `Review: none — Codex unavailable` в отчёте, и работа идёт
  дальше. Не поднимать ревьюера на другой модели, не спавнить агента-ревьюера, не откладывать
  задачу до появления Codex.
- Explicit user request на конкретного reviewer выполняется. Ревью сверх маршрута — тоже по
  запросу постановщика, а не по своей инициативе: лишний ревьюер стоит денег юзера.

## MCP tool: codex_review

```
codex_review(context, target, output, mode, resume, model)
```
- `target` — файл для review (для `mode="exec"`). Пусто → git diff (`mode="review"`)
- `output` — путь для результата, всегда под `docs/tasks/<id>/`
- `mode` — `"review"` (git diff) или `"exec"` (review конкретного файла)
- `context` — промпт для Codex: задача + PROJECT CONTEXT (см. ниже). ВСЕГДА передавай
- `resume` — `true` → продолжить debate в той же сессии (ключ = тот же `output`). Для follow-up раундов
- `model` — reviewer model из live registry. Luna: `gpt5.6luna`; Sol: `codex`. Параметр нужно
  повторять на resume; если опущен, backward-compatible default всегда Sol

Тул сам держит persistent-сессию по `output`-файлу, делает resume, пишет результат. Никакого ручного управления UUID/proxy/timeout.

**Review реализации (diff):**
```
codex_review(mode="review", output="docs/tasks/<id>/codex-review-impl.md",
             model="gpt5.6luna",
             context="Review the staged git diff for bugs, security, breaking changes, race conditions. <PROJECT CONTEXT>")
```

**Review плана/файла:**
```
codex_review(target="docs/tasks/<id>/plan.md", mode="exec", output="docs/tasks/<id>/codex-review-plan.md",
             context="Review this plan: scope creep, wrong file/function refs, contradictions, security. Max 10 findings. <PROJECT CONTEXT>")
```

**Debate / re-review (тот же output, resume):**
```
codex_review(output="docs/tasks/<id>/codex-review-impl.md", resume=True,
             model="<same reviewer model as the prior round>",
             context="<task + current PROJECT CONTEXT>. I fixed X and Y. Re-review: for each prior blocking → FIXED / STILL BROKEN / NEW BUG. Append ## Round N.")
```

## Правила вызова
- **`mode="review"` смотрит рабочее дерево.** Если работа уже закоммичена: `git diff <merge-base> HEAD > /tmp/<name>.diff`, затем `codex_review(mode="exec", target="/tmp/<name>.diff", ...)`; иначе получишь `no changes to review` и потеряешь раунд
- **`context` ОБЯЗАТЕЛЕН** — задача + PROJECT CONTEXT. Без него Codex мискалибрует severity
- **Ограничивай ПЕРВЫЙ вызов, не второй.** В `context` сразу: точные файлы/хунки (или несущие утверждения для ресёрча), запрет уходить в logs/BUGS.md/TODO.md/git history, потолок находок. Неограниченный вызов срывается на транспорте → его приходится перезапускать
- **Ревью плана судит ТОЛЬКО текст плана.** Явно пиши: код ещё не написан, не оценивай его по текущему рантайму
- **Не заявляй "Codex прошёл/одобрил" не прочитав `output`-файл.** Не галлюцинируй результат — не видел findings, значит review не состоялся
- **resume для follow-up, НЕ новый вызов** — новый вызов теряет контекст прошлых раундов
- Прочитал `output` → работай с findings (ниже)

## Conventional Comments
Формат замечания: `<prefix>: file:line — проблема → предложение`

| Prefix | Значение |
|---|---|
| `blocking:` | must fix, мерж невозможен. Баги, security, data loss |
| `suggestion:` | рекомендация, не блокирует |
| `question:` | нужен ответ автора |
| `thought:` | мысль вслух, без действия |
| `nit:` | мелочь, можно скипнуть |

## Session concept
- Один review-поток = один `output`-файл. Codex дописывает раунды (`## Round N`) в него, не перезаписывает
- Persistent-сессию (thread) тул хранит сам, привязывая к `output`. Продолжение = `resume=True` с тем же `output`
- Новая тема = новый `output`-файл. НЕ переиспользуй `output` от несвязанного review

## Evidence-backed follow-up
**One round by default.** После первого раунда:
1. Прочитай `output`-файл, разбери findings
2. Каждое **blocking** → проверь через код (grep/cat/read). Решение: ACK / DISAGREE / PARTIAL
3. **Эскалируй** (адресат — выше) если reviewer хочет: удалить функционал / существенно менять архитектуру рабочих компонентов / что-то с неясными последствиями
4. Почини ACK'нутые (Edit)
5. Следующий раунд законен только после изменения artifact по проверенному blocker либо для
   проверяемого спора по blocker с фактами из кода. Новая suggestion, nit, unchanged artifact и
   желание получить `APPROVED` не открывают раунд.
6. Для Luna/Sol follow-up: `codex_review(..., resume=True, model="<тот же reviewer>", context="<task + current PROJECT CONTEXT>; фиксы/контраргументы: <evidence>, re-review")`.
7. Остановись при состоявшемся verdict, эскалации наверх или потолке — что наступит раньше.

**Потолок раундов — по типу предмета. Этот файл — единственный владелец правила; в промптах ролей чисел нет.**

| Предмет, который ты ПРАВИШЬ между раундами | Потолок |
|---|---|
| Исполняемый: дифф, код, скрипт | **3 раунда** |
| Проза: `research.md`, `plan.md`, отчёт, документация | **2 раунда**, второй только если артефакт между раундами менялся |

- Тип определяется тем, **что именно правится между раундами**, и ничем другим. Правишь только прозу — предмет проза, сколько бы скриптов рядом ни запускалось. Признаки «приложен запускаемый файл» и «ревьюер запустил скрипт» НЕ годятся: оба под контролем того, кого ограничивают, и покупают лишний раунд тривиальным скриптом.
- **«Раунд принёс новые замечания» основанием для следующего раунда НЕ является.** На прозе ревьюер порождает замечания бесконечно, поэтому условие вида «раунды без прогресса» не наступает никогда и защитой не является.
- Потолок считает ВСЕ раунды по одному предмету, включая запущенные руками через `codex exec`/Bash в обход `codex_review`. Обход тула от потолка не освобождает.
- Достиг потолка при неразрешённых находках → СТОП. Перечисли их в отчёте и отдай оркестратору, не начинай следующий раунд.

Замер, откуда числа: раунды ≥2 окупались 7 из 13 на коде и 1 из 11 на прозе, раунды 4-5 не дали ничего. Инцидент: шесть раундов по одному документу-прозе, 38 минут одного хода, остановлено человеком вручную (#177).

**Что тратит потолок раундов — правило по умолчанию: ЛЮБОЙ непустой вывод.** Это fail-closed: сомневаешься — раунд потрачен. Ненулевой код возврата вердиктом не управляет: тул может отчитаться ошибкой и при этом вернуть настоящее ревью. «Ревью мне не понравилось» и «ревью не доказало себя» основанием не считать раунд НЕ являются.

**Единственное исключение — ревьюер не ответил вовсе (несостоявшаяся попытка).** Ровно два случая:
- вывода нет: таймаут, обрыв транспорта, "chunk exceed";
- весь вывод — сообщение об отказе ИНСТРУМЕНТА (`bwrap`, `RTM_NEWADDR`, `sandbox failed`, «Unable to perform») и ничего кроме него.

Различает не «содержательность», а **кто выдал текст: инструмент или ревьюер**. Голый `ACK`, «review completed», пустой вердикт — это ОТВЕТ ревьюера, он раунд ТРАТИТ, просто вердикта в нём нет. Ревью, обсуждающее `bwrap` внутри находки, тратит. Незнакомый текст отказа вместе с находками — тратит. Сомневаешься, чей это текст, — раунд потрачен.

**Исходы по классам вывода. Любой ответ ревьюера попадает в одну из первых четырёх строк, любой не-ответ — в одну из двух последних:**

| что вернул вызов | исход |
|---|---|
| находки есть, доказательство есть | раунд потрачен, вердикт засчитан |
| находки есть, доказательства нет | раунд потрачен, в отчёт «вердикта нет» |
| находок нет, доказательство есть — честное чистое ревью | раунд потрачен, вердикт засчитан |
| ответ есть, но находок и доказательства в нём нет — голый `ACK`, «review completed», «не могу вынести вердикт», пробелы, служебный JSON | раунд потрачен, в отчёт «вердикта нет» |
| вывода нет вообще | попытка, раунд не тратит |
| весь вывод — отказ инструмента и ничего кроме | попытка, раунд не тратит |

**У попыток свой потолок: 3 на один предмет** за всё время работы над ним, считая и запуски руками через `codex exec`. Изменение артефакта потолок попыток НЕ обнуляет. Исчерпал → СТОП: запиши «вердикта нет, N попыток» с причиной каждой, сделай adversarial self-review вместо ревью, отдай оркестратору.

**Журнал попыток — тот же `output`-файл.** Перед запуском допиши строку о попытке, после — отметь исход; файл не обнуляется никогда. Это журнал самоконтроля и аудита, **а не механизм гарантии**: ведёт его тот же агент, которого он ограничивает. Настоящая гарантия — счётчик в обёртке запуска, то есть код, и это отдельная задача (#181).

**Что считается СОСТОЯВШИМСЯ ревью.** Критерий доказывает, что ревьюер РАБОТАЛ с артефактом. От того, нашёл ли он замечания, он не зависит. Вердикт засчитывается, только если ревьюер привёл одно из двух:
- **команду прогона тестов и строку её результата** («прогнал N тестов» без команды и вывода — не доказательство, это его слова о себе; «0 тестов» — тем более), либо
- **дословную строку из ревьюируемого артефакта, которой не было в тексте твоего запроса**, — и ты нашёл её в файле.

Цитата — основной признак: её ты проверяешь сам. Число тестов проверить нельзя, поэтому оно засчитывается только вместе с командой и её выводом.

**«Замечаний нет» — законный вердикт и проходит по тому же критерию.** Чистое ревью обязано назвать, ЧТО проверено, и процитировать строку. Голый `ACK` / `no blockers` / `APPROVED` без цитаты вердиктом не является — не потому, что ревьюер ничего не нашёл, а потому, что нечем отличить прочитанный артефакт от непрочитанного. Требуй цитату в САМОМ запросе, отдельно оговаривая случай «если замечаний нет».

Голая ссылка `file:line` доказательством НЕ является: она подделывается пересказом твоего же запроса. Поэтому не цитируй ревьюеру содержимое файлов — давай пути и требуй цитату.

`grep -F` на цитате из прозы даёт ложное «не найдено», если в файле она перенесена по строкам или идёт под `> `. Прежде чем объявить цитату выдуманной, сравни нормализованно — операция ровно одна и та же для цитаты и для файла: **убрать в начале каждой строки пробелы и `> `, затем заменить любую последовательность пробельных символов одним пробелом**. Ничего другого не удалять. Одной строкой:

```python
norm = lambda s: re.sub(r"\s+", " ", re.sub(r"^[ \t]*>?[ \t]*", "", s, flags=re.M)).strip()
```

Нет ни одного из двух признаков → пиши в отчёте **«вердикта нет, ревью без доказательств»**, а не «review approved». Это законный исход, а не провал.

Размер сам по себе не выбирает маршрут: trivial skip требует всех доказательств gate, а
shared-runtime/security поверхность идёт к Sol при любом размере — когда Codex доступен.

**Спор, а не молчание.** Не согласен с blocking после проверки кода → один evidence-backed
follow-up в пределах потолка. Recorded-and-ignored blocking = провал; упереться в потолок с
открытыми находками и отдать их оркестратору — предписанный исход.

## Show Result to User
```
Review route: <none — Codex unavailable / skip / Luna / Sol>
Rounds: N
Verdict: <APPROVED / needs work / reject / вердикта нет>
Findings: blocking X (Y fixed, Z rejected + причина) · suggestion M (K accepted) · nit skipped
Evidence: <named command + output + AC; reviewer artifact path>
```

## Prompt Templates (для `context`)
**Plan/Spec review:** "Review this plan. Проверь ссылки (файлы, функции, сигнатуры) против кода, scope creep, противоречия, security/race conditions. Max 10 findings, конкретика. Format: ## Summary, ## Findings (Conventional Comments), ## Verdict."

**Code review (diff):** "Review the git diff. Найди баги, security, breaking changes, race conditions. Прочитай изменённые файлы. Не рефакторь рабочий код. Нет замечаний → 'ACK' + дословная строка из изменённого файла, которой нет в этом запросе."

**Debate (не согласен):** "Не согласен с <ID-список>. Аргументы (факты из кода): <...>. Для каждого: ACK / контраргумент с фактами / частично. Append ## Round N."

**Re-review after fix:** "Применены фиксы: <changelog>. Для каждого прошлого замечания: FIXED / STILL BROKEN / NEW BUG. Все blocking закрыты и нет новых → APPROVED + дословная строка из артефакта, по которой ты это проверил. Append ## Round N."

## PROJECT CONTEXT (вставляй в `context`)
Шаблон и правила заполнения — один источник: секция **PROJECT CONTEXT** в orchestration-модуле
(она же в задании оркестратора). Поля бери из ТЕКУЩЕГО репозитория и задачи.

⚠️ Скилл общий для всех проектов. Не подставляй сюда чужой stack/scale по памяти: «~10 users»
на highload-проекте занижает severity реальных performance/architecture находок. Не можешь
назвать поле по репозиторию — выясни до review.

## What NOT to Do
- НЕ создавай новый Sol-вызов на законный follow-up — используй `resume=True`
- НЕ соглашайся слепо с blocking — проверь через код
- НЕ игнорируй blocking молча — resolve (fix/debate) или эскалируй
- НЕ заявляй "одобрено" не прочитав output-файл
- НЕ повторяй review unchanged artifact и не покупай раунд одной новой suggestion
- НЕ переиспользуй `output` несвязанного review
