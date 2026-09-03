# #261 — X-поиск через Grok как фоновый тул

Дата: 2026-08-13. Фаза 1: research + experiment; реализации ещё нет.

## Вопрос

- **Контекст:** Orchestra уже умеет запускать фоновые `codex_review` jobs с артефактом и
  пробуждением вызывающего; Grok 4.5 по подписке доказал native X retrieval в #251.
- **Изменение:** добавить один доступный всем pipeline-ролям MCP-тул для точечного вопроса к X
  через Grok 4.5, а не обязательную фазу full-cycle и не общий Grok-worker route.
- **Baseline:** ручной spawn Grok-worker либо отсутствие первичного X-доступа.
- **Решающий исход:** один неблокирующий вызов создаёт проверяемый артефакт с реальными X URL,
  громко отказывает до работы без auth/при исчерпанной квоте и имеет явный верхний бюджет.

## Гипотезы и фальсификаторы

1. **H1: `codex_review` можно безопасно повторить как узкий `grok_x_search`.** Неверно, если
   существующий bg-job жёстко связан с Codex resume/review semantics либо не сохраняет полный
   stdout отдельно от обрезанного notification.
2. **H2: структурной проверки URL + X snowflake + фактического native tool trace достаточно,
   чтобы запретить сочинённую ссылку.** Неверно, если headless trace не раскрывает нужный
   `post_id`/timestamp или реальный, но нерелевантный пост проходит ту же проверку.
3. **H3: auth и quota можно проверить до model call без API-ключа.** Неверно, если подписочный
   CLI не даёт локального/дешёвого readiness сигнала или quota доступна только после расхода.
4. **H4: расход можно ограничить одним turn/таймаутом/числом X calls.** Неверно, если CLI не
   принуждает хотя бы один из лимитов либо server-side X loop не виден до завершения.

## Предрегистрация эксперимента E1 — независимая проверка X-ссылки

Пилот до фиксации критерия: публичный `cdn.syndication.twimg.com/tweet-result` вернул одинаковый
`HTTP 200 {}` для заведомо существующего post id и `id=1`, поэтому он непригоден: проверка даёт
один ответ при успехе и провале. `publish.twitter.com/oembed` на тех же двух объектах дал
соответственно HTTP 200 с автором/HTML поста и HTTP 404. Полный прогон делается на уже замороженных
18 trace из #251; новых Grok-ходов нет.

Для каждого X URL, который модель заявила в `post_url`, считаем отдельные признаки:

1. URL имеет каноническую форму `https://x.com/<handle>/status/<decimal id>`;
2. тот же id присутствует во входе фактически завершённого native `x_thread_fetch` в JSONL;
3. заявленный timestamp отличается от времени X snowflake не больше чем на 1 секунду;
4. независимый oEmbed отвечает HTTP 200, его canonical URL содержит тот же id, автор совпадает;
5. нормализованный `verbatim_text` модели совпадает с нормализованным телом oEmbed полностью.

Строгий PASS ссылки = все пять признаков. Отдельно считаются случаи, где oEmbed подтверждает URL,
но точный текст не совпал. Смысл свободного summary этим экспериментом **не** считается проверенным:
структурная проверка не умеет доказать релевантность или отсутствие искажения в пересказе.

## Предрегистрация эксперимента E2 — исполнительные ограничения headless X-хода

Один адресный положительный контроль на известном post id из #251 запускается на `grok-4.5` с
`--max-turns 1`, `--no-memory`, `--no-plan`, `--no-subagents`, внешним
`timeout --kill-after=5s 120`, JSON schema и deny всех общих built-in code/web tools. Нативные X
tools не перечисляются в allowlist: сначала проверяется, переживают ли они deny ненужных built-ins.

PASS: rc=0; ровно один terminal `end`; `end.num_turns <= 1`; хотя бы один completed native
`x_thread_fetch` с замороженным id; ответ содержит канонический URL/точный timestamp; ни одного
completed не-X tool; wall <120 s. Провал любого пункта опровергает пригодность этого набора флагов.

Этот пилот **не** доказывает потолок числа native X calls: даже при PASS один agent turn может
содержать произвольное их число. Доказательством такого потолка был бы отдельный принуждаемый CLI
лимит или остановка до `(N+1)`-го X-вызова; ни один пока не найден.

## Findings

### F1. Форма `codex_review` переносима, но её восстановление полного текста устроено иначе

Текущий путь — `mcp_stdio.codex_review()` → `POST /api/bg/jobs` типа `run` →
`BgJobManager._run_exec()` → `codex_review_artifact.py` → пробуждение вызывающего. Job сохраняет
команду и immutable session id в SQLite, переживает hibernate/restart, ограничен 600 секундами,
проверяет непустой `success_file`; уведомление и `bg_jobs.last_output` сохраняют только последние
3000 символов [1][2][3]. Описание и ответ тула оба содержат `END YOUR TURN NOW`, поэтому
вызывающий не блокирует текущий ход ожиданием [1].

Полный текст `codex_review` в нормальном пути берётся из `codex -o <output>.round`, а JSONL нужен
для UUID, usage и execution guard. Автоматического «восстановить review из JSONL после nonzero rc»
в коде **нет**: это ручная аварийная процедура из проектного правила. Для Grok отдельный `-o`
не нужен и недоступен: его полный ответ воспроизводимо собирается как ordered concatenation всех
`type=text.data` в raw streaming JSONL; #251 уже сделал это 18/18 [4]. Поэтому требование
«восстановить полный текст, если notification обрезан» выполняется не чтением notification, а
обязательным finalizer, который всегда парсит весь JSONL и атомарно пишет Markdown-артефакт.

**CONFIRMED — tier 1/2:** прямой code trace и существующие тесты; формулировка «копировать
целиком» означает сохранить bg/artifact/wakeup/failure contract, но не Codex-specific CLI grammar.

### F2. Grok 4.5 подходит как runtime узкого X-тула

#251 дал Grok 4.5 native X success **9/9** (в паре обе модели 18/18), exact permalink на
однозначных A+B **4/6**, медиану **34.616 с**, 47 completed X calls и 0 stderr/nonzero exits [4].
Grok 4.6 на тех же заданиях был хуже по exact links (2/6) и медленнее (44.977 с), поэтому
`grok-4.5` должен быть жёстко пинован и сверяться с живым `grok models`, а не браться из default
(сейчас default — 4.6) [4][5].

E2 проверил именно будущую узкую форму: `grok-4.5`, `--max-turns 1`, JSON schema, без memory,
plan, subagents, общего web/code/filesystem/MCP. Результат: rc=0, 9.639 с, один `end`,
`num_turns=1`, ровно один completed `x_thread_fetch(2087564648325530099)`, ноль не-X tools,
канонический URL и timestamp с расхождением 0.893 с от snowflake [7]. Это доказывает, что
ненужные capabilities можно удалить, не убив native X tools.

**CONFIRMED — tier 1:** одинаковая версия/runtime и адресный положительный контроль.

### F3. Приёмка может отсеять сочинённую ссылку и проверить часть цитаты, но не весь смысл

Минимальный fail-closed validator должен принять артефакт только если:

1. есть ровно один terminal `end` с `stopReason=end_turn`, `num_turns<=1` и terminal model key
   `grok-4.5-build`;
2. есть хотя бы один completed native `x_*`, ни одного completed не-X tool;
3. каждый опубликованный URL каноничен, его decimal id соответствует фактически completed
   `x_thread_fetch(post_id)`, timestamp соответствует X snowflake в пределах 1 секунды;
4. независимый `publish.twitter.com/oembed` возвращает HTTP 200 и canonical id/author этого
   поста. Публикуемый fragment берётся из самого oEmbed body, а не из текста модели.

E1 на замороженных 18 trace: модель заявила URL в 10 ходах (4 уникальных post id); canonical,
snowflake и независимый oEmbed identity прошли **10/10**, соответствующий `x_thread_fetch` —
**9/10**. Последний случай показывает необходимый trade-off:
пост может быть найден прямым search без отдельного fetch, но строгий production contract должен
его отвергнуть, иначе provenance результата скрыт. Полное совпадение fragment прошло только 4/10:
oEmbed обрезает длинные/long-form посты с `…`; это не доказательство ошибки Grok [6].

После предзарегистрированного exact-match прогона exploratory-проверка увидела совпадение первых
200 нормализованных символов в 10/10 случаев. Это только диагностическое наблюдение на четырёх
уникальных постах: не было prospective mutated-prefix контроля, а критерий выбран после раскрытия
результата. Поэтому production не доверяет даже этому префиксу модели: finalizer публикует только
текст, независимо возвращённый oEmbed, и никогда не публикует неподтверждённый suffix [6].

Positive/negative control отделяет проверку от пустого ответа: старый syndication endpoint дал
одинаковый `HTTP 200 {}` существующему id и `id=1` и потому отвергнут; oEmbed дал соответственно
HTTP 200 и HTTP 404. Подмена handle при том же id тоже нормализуется oEmbed к настоящему автору,
поэтому валидатор обязан сравнить returned canonical identity, а не status code [6].

Что **не** доказуемо этим каналом: полный long-form body, репрезентативность выборки, релевантность
поста вопросу, корректность свободного summary, вывод «так думает X». Следовательно, безопасный
артефакт — **retriever report**: проверенные URL + snowflake timestamp + oEmbed fragment.
Неподтверждённый suffix и свободный синтез модели в пользовательский артефакт не попадают;
полный raw answer остаётся только временным diagnostic до финализации.

**CONFIRMED для identity provenance, LIKELY только для наблюдённого model-prefix, UNCERTAIN для
смысла:** E1 tier 1 измерил identity; prefix был post-hoc и не является production oracle.

### F4. До inference нужны три независимых preflight; quota unknown тоже должен блокировать

`ensure_grok_home()` уже отказывает до spawn, если `~/.grok/auth.json` отсутствует. Наличие файла
не доказывает валидность. Поэтому три состояния нельзя склеивать в одно «auth OK»:

1. credential file существует и managed `GROK_HOME` собран;
2. proxy-free `grok models` завершился rc=0, напечатал `You are logged in with grok.com` и содержит
   `grok-4.5` — это проверяет catalog auth и live model availability без model call;
3. свежий billing preflight вернул классифицированное `AVAILABLE`, `EXHAUSTED` или `UNKNOWN`.

Живой catalog preflight 13.08.2026 прошёл для 4.5/4.6 [5][8]. Отсутствие бинарника, credential,
auth banner, 4.5 в catalog либо классифицированного billing результата — громкий отказ до создания
bg job. Процесс должен использовать `ensure_grok_home()`/`_build_env()` либо единый owner
telemetry hard-off; пользовательский `GROK_HOME` нельзя наследовать.

Subscription quota видна через `GET /api/usage`: живой ответ 13.08.2026 10:44 CEST —
`utilization=13`, окно 10080 минут, reset 2026-08-16T19:51:48Z. Источник округлён и не содержит
числителя. Однако normal route кеширует до 300 секунд; missing auth, 401, network/schema error
дают `grok=null`. Более того, `_fetch_grok_usage()` сейчас не классифицирует billing HTTP 429:
`raise_for_status()` уходит в общий exception и наружу тоже становится `null`. Общий
`current_quota_observation()` пока не поддерживает Grok: в `_quota_refresh_locks` нет `grok`, а в
`observed_at_by_provider` нет его timestamp [8][9]. Поэтому текущий `GET /api/usage` не является
достаточным admission oracle для нового тула.

Будущий preflight обязан сохранить provenance свежего billing ответа:

- валидный weekly shape и `utilization <100` → `AVAILABLE`, запуск разрешён;
- валидный `utilization >=100` **или billing HTTP 429** → `EXHAUSTED`, fail closed с reset, если он
  известен;
- no credential, 401, network/timeout, schema mismatch, stale/no observation → `UNKNOWN`, fail
  closed до model work с точной категорией. `UNKNOWN` нельзя читать ни как 0%, ни как доказанное
  исчерпание.

Runtime 429 после успешного preflight всё равно завершает job как `rate_limit`; незнакомая ошибка
остаётся verbatim generic error. Между preflight и inference остаётся неизбежная race, поэтому
terminal классификация нужна даже при свежем `AVAILABLE`. Последний terminal payload реального
исчерпания подписки никогда не наблюдался; текстовый pattern по аналогии с Codex выдумывать нельзя
[8].

**CONFIRMED для трёх preflight и текущей потери provenance; UNCERTAIN для terminal hard-stop
shape:** code trace + live catalog/usage, реальное исчерпание ещё не наблюдалось.

### F5. Честного точного потолка subscription spend пока нет

CLI даёт два принуждаемых предохранителя: headless `--max-turns 1` и внешний
`timeout --kill-after=5s 120`. Vendor doc уточняет: `num_turns` считает main-agent model rounds;
`modelUsage.*.modelCalls` — родственная, но не гарантированно равная величина [5]. #251 уже показал
главное: один turn содержал до **21** completed X calls, а девять 4.5 ходов стоили по runtime
ticks от $0.0545 до $0.5900 (median $0.3966), хотя `modelCalls=1` в каждом [4].

Следовательно:

- `max_turns=1` ограничивает model loop, но **не** число X calls;
- wall timeout ограничивает время процесса, но не отменяет уже сделанные provider calls;
- JSON schema/фраза «не больше N» ограничением расхода не являются;
- post-hoc `x_calls <= N` полезен как integrity gate, но отклоняет уже оплаченный результат;
- `costUsdTicks`/`total_cost_usd` — runtime-reported estimate, не provider billing truth текущей
  подписки; точная остаточная ёмкость неизвестна.

Поэтому обещать dollar/modelCall ceiling нельзя. Исполнимый MVP ceiling следует честно назвать
**execution budget**: 1 agent turn, hard wall 120 с, один job на вызов, одна активная попытка без
авторетрая; результат с >6 completed native X calls (медиана 4 в #251) отклоняется и оставляет
usage warning. Значение 6 — не pre-spend cap, а anomaly/integrity threshold; retry после
validation failure только новым явным вызовом человека/агента.

«Одна попытка» требует отдельного crash-safe механизма, потому что текущий
`BgJobManager.restore_from_db()` повторно исполняет command каждого active `run`. Контракт marker:

1. command сначала проверяет готовый валидный artifact: он завершает success без inference;
2. иначе после всех preflight, но **до** spawn Grok shell атомарно создаёт run-specific marker
   через `O_CREAT|O_EXCL`;
3. `O_EXCL` увидел существующий marker при отсутствии artifact → command отказывает distinct
   `attempt_outcome_unknown`, не
   удаляет marker и не запускает Grok повторно;
4. только создатель marker может сделать единственный spawn; marker не удаляется после ошибки.

В Phase 2 нужны crash-boundary тесты: до marker; marker→spawn; во время Grok; JSONL→artifact;
artifact→bg terminal state; плюс две параллельные команды. Без этого «без retry» не доказано.
Если требуется настоящий dollar/X-call ceiling, scope расширяется до enforcement внутри
runtime/tool-call boundary или provider-side budget — текущий headless CLI его не предоставляет.

**REFUTED H4 в сильной форме; CONFIRMED для ограниченного execution budget.**

### F6. Usage нужно атрибутировать вызывающей сессии, но не ставить выше результата

Как `codex_review`, finalizer должен извлечь terminal usage из полного JSONL и сделать
идемпотентную запись `turn_usage` с runtime `grok`, model `grok-4.5`, caller session/scope/task.
Нельзя переиспользовать Codex token semantics/`_codex_cost`: Grok headless `end` имеет свои
`usage`, `modelUsage`, `total_cost_usd_ticks`. И нельзя снова сделать accounting failure причиной
потери оплаченного retriever report: сначала атомарно сохранить validated artifact, затем записать
usage; ошибка учёта добавляет видимый warning, как исправленный `codex_review_artifact.py` [2][8].

**CONFIRMED — code trace и урок #215/#217; точность subscription billing остаётся UNCERTAIN.**

## Рекомендуемый узкий контракт тула

Рабочее имя: `grok_x_search(question: str)`. Путь генерирует сам сервер как
`docs/tasks/<current-task-id>/grok-x-<run-id>.md`; отсутствие task id отклоняется до model work.
Так тул буквально принимает один вопрос, а arbitrary path/path traversal исчезают из API.
Пустой вопрос и параллельный run с тем же id тоже отклоняются.

Порядок одного вызова:

1. локальная валидация вопроса/task id → binary/credential/catalog preflight → свежий
   classified billing preflight; запуск разрешён только при `AVAILABLE`;
2. pin `grok-4.5`, managed telemetry-hard-off `GROK_HOME`, proxy-free env, deny code/web/MCP,
   `--no-memory --no-plan --no-subagents --max-turns 1`, JSON schema;
3. bg `run`, 120 с + TERM/KILL, unique prompt/JSONL/rc и атомарный durable attempt marker по
   протоколу F5. При восстановлении active bg job готовый artifact переиспользуется, а marker без
   artifact даёт `attempt_outcome_unknown` до inference;
4. finalizer читает **весь** JSONL, валидирует terminal/model/native trace и каждый X post через
   oEmbed+snowflake, а fragment берёт из oEmbed, не из model text; затем пишет atomic Markdown.
   Raw JSONL остаётся временным diagnostic и не коммитится;
5. usage attribution nonfatal после артефакта; `success_file` + machine-readable success marker;
6. одно пробуждение с `END YOUR TURN NOW`; notification может быть обрезан, потому полная истина —
   файл. FAILED/TIMEOUT также будят и называют exact reason.

Нужный prompt trigger (одна строка, сам prompt здесь **не меняется**):

> Нужны мнения людей, реакция на событие или свежие обсуждения в X, которых нет в обычном веб-поиске → вызови `grok_x_search` и закончи ход.

## Контрдоказательства и снятые варианты

- **«Snowflake + completed X tool достаточно». Снято.** Это доказывает arithmetic/tool target,
  но не существование/автора/текст. oEmbed добавляет независимую identity+prefix проверку.
- **«oEmbed проверяет весь verbatim». Снято после E1.** Long-form body обрезан; exact только 4/10.
- **«`--max-turns 1` — потолок X расхода». Снято.** До 21 X calls в одном turn.
- **«Тул возвращает исследовательский summary». Снято.** Без проверки полной выборки и body это
  та же фабрикация смысла, которую #232 запретил; наружу идёт retriever report.
- **«Quota unknown можно компенсировать малым execution budget». Снято после adversarial
  review.** Unknown склеивает network/schema/401 и billing 429; разрешение при unknown может
  начать работу именно на исчерпанном аккаунте. Тул fail-close блокирует unknown, пока оператор
  не повторит позже; это availability trade-off, но единственный контракт, не выдающий отсутствие
  telemetry за разрешение тратить пул.

## Затронутые файлы и риски будущей реализации

Минимально ожидаются:

- `app/mcp_stdio.py` — schema, preflight, bg command. Дословное «любой pipeline-роли» требует
  добавить тул в `REDUCER_MCP_TOOLS`: `app/manager.py:_make_mcp_config()` выставляет `reducer`
  только одноимённой роли, всем остальным ролям — `full`. `read-only` в текущем production code
  не роль, а отдельный access mode без producer mapping; quota-spending/artifact-writing тул туда
  не добавляется и read-only semantics не меняет [1][8];
- `app/routes/system.py` — сохранить Grok billing status provenance, добавить Grok в fresh quota
  observation/lock/timestamp; обычного 300-second cached `/api/usage` недостаточно;
- `app/backend_grok.py` — вынести managed proxy/telemetry/auth env в один reusable helper, чтобы
  X-тул и `GrokBackend` не держали две копии security policy;
- новый stdlib-finalizer рядом с `app/codex_review_artifact.py` — JSONL recovery, validation,
  artifact, usage;
- focused tests нового MCP tool/finalizer; общий `app/bg_jobs.py` менять не требуется по
  текущим фактам;
- `docs/tasks/261/` — research/plan/report. Pipeline prompts не трогать.

## Вывод Phase 1

**PROCEED, но только как узкий bg retriever tool на Grok 4.5.** Архитектурная форма
`codex_review` подходит; E2 доказал минимальный headless X-путь, а E1 добавил независимую
проверку post identity. Успешный artifact должен содержать 1–5 валидированных
permalink/snowflake timestamp/oEmbed snippet и не выдавать model fragment или свободный Grok
synthesis за факт.

Единственная невыполнимая дословно часть — точный provider-spend ceiling: subscription CLI не
даёт pre-call лимита native X tools и exact remaining numerator. Реальный принуждаемый потолок —
один model turn + 120 секунд + одна попытка без retry; число X calls и runtime-reported cost
обязательно показываются post-hoc. Если нужен долларовый или X-call hard cap, это другой scope и
другая граница исполнения, а не этот один MCP tool.

Риски: secrets/raw tool args в коммитном JSONL; oEmbed outage/deletion/protected accounts;
long-form truncation; dynamic catalog; quota telemetry outage; расход до post-hoc rejection;
`/tmp` collision по output slug; crash в границах marker/artifact и повторный запуск; accounting
semantics; notification delivery failure. Tests должны отдельно закрыть path traversal,
shell quoting, absent/expired auth, model 4.5 missing, quota available/100/429/null/stale,
partial/no-end JSONL, fabricated id/handle/timestamp, missing `x_thread_fetch`, oEmbed
negative/control/truncation,
too-many X calls, timeout, restart idempotency, reducer visibility, nonfatal usage failure и
artifact recovery из >3000 символов.

## Источники

1. `app/mcp_stdio.py:2006-2317`, `tests/test_mcp_codex_review.py`,
   `tests/test_mcp_quota_gate.py` — production code + focused tests, tier 1/2.
2. `app/codex_review_artifact.py`, `tests/test_codex_review_artifact.py` — atomic artifact/usage,
   tier 1/2.
3. `app/bg_jobs.py:536-611,834-955`, `app/db.py:1861-1913` — bg durability, 3000-char tail,
   timeout/wakeup, tier 1/2.
4. `docs/tasks/251/{prereg.md,research.md,score.json,raw/*.jsonl}` — 18 живых ходов, tier 1.
5. `/usr/bin/grok 1.0.3 --help`, `data/grok-home/docs/user-guide/14-headless-mode.md:31-86,140-185`,
   живой `grok models` 13.08.2026 — vendor primary + live measurement, tier 1/2.
6. `docs/tasks/261/validate_251_oembed.py`, `e1-result.json` — E1, tier 1.
7. `docs/tasks/261/prompt-e2.txt`, `e2-result.json` — E2, tier 1.
8. `app/backend_grok.py:119-142,898-960,1031-1069`, `docs/grok-field-guide.md` — auth,
   errors, usage, managed env, tier 1/2.
9. `app/routes/system.py:448-582,771-882,940-947`; живой `/api/usage` ответ 13.08.2026 —
   quota semantics, tier 1/2.
