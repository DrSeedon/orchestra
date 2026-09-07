# #432 — отделить разведку от длинного диалога: постановка причинного замера

Дата фиксации: 2026-09-01. Фаза 1: только исследование и протокол; реализации нового harness нет.

## Question

- **Context:** Orchestra-агент решает реальную задачу в уже длинной сессии. Каждый следующий
  модельный вызов после `rg`/`Read` снова несёт историю и результаты предыдущих инструментов.
- **Change under test:** весь пакет `fresh scout + узкие read-only tools + JSON handoff`: Luna-
  разведчик получает задачу и read-only снимок репозитория, ищет тем же `rg`, возвращает один
  отобранный context bundle; основная Luna получает bundle одним сообщением и продолжает задачу
  в прежней длинной сессии. Замер не пытается отдельно приписать эффект одному только placement.
- **Baseline:** та же основная Luna, тот же исторический снимок, тот же исходный диалог и те же
  read-only инструменты, но разведку она выполняет inline.
- **Outcome:** проходит ли лечение тот же замороженный поведенческий oracle и насколько меняются
  (а) общая цена всех модельных вызовов, (б) общий `cache_read`, (в) `cache_read` основной модели.
  Вывод об экономии разрешён только после quality gate; «main стал дешевле, scout не посчитан»
  экономией не является.

## Hypotheses considered

### H1 — разведчик даёт чистую экономию

Разведчик снижает общую цену, потому что несколько поисковых вызовов перечитывают короткий свежий
контекст разведчика, а длинную историю основная модель перечитывает один раз с готовым bundle.

**Фальсификатор:** сумма `cost_usd` или `cache_read_tokens` разведчика и основной модели не ниже
baseline за пределами собственного A/A-шума либо treatment ухудшает замороженную приёмку.

### H2 — handoff только добавляет второй агентный цикл

Разведчик повышает цену, потому что выполняет почти тот же поиск, после чего основная модель всё
равно делает минимум один дорогой вызов и может перечитать недостающее.

**Фальсификатор:** treatment сохраняет качество, а нижняя граница 90% clustered-bootstrap CI
парной экономии выше нуля и медианная экономия больше p90 A/A-шума.

### H3 — эффект условный, а не общий

Лечение помогает только при сочетании длинного parent-контекста и нескольких repository-read
вызовов; на холодном ходе, закрытом тикете и данных вне репозитория не помогает.

**Фальсификатор:** cold negative control показывает ту же экономию, что warm treatment, либо
экономия не связана ни с baseline `cache_read`, ни с числом repository-read вызовов.

## Findings

### F1 — причина измерять деньги, а не только число вызовов, подтверждена

В #345 предельная цена одного tool-вызова измерена как $0.135 для Claude и $0.106 для Codex;
69%/72% предельной цены объясняются `cache_read`, а перемешивание числа вызовов внутри сессии
обрушает связь [1]. Это tier 1 (живая `turn_usage` + отрицательные контроли), но это наблюдательная
связь: она не доказывает, что перенос поиска в другой агент даст ту же дельту.

**CONFIRMED** — прямая measurement evidence для цены вызова; причинный эффект нового seam остаётся
неизмеренным.

У входной формулировки #432 есть числовая неоднозначность, которую нельзя переносить в новый
знаменатель. Артефакт #345 различает: доля разведочных **вызовов** у Claude 26.8%, денежная доля
Claude 19.4%, денежная доля Codex 35.1%, общая денежная доля 26.8% [1]. В постановке #432
«26.8% денег у Claude» смешивает две строки. Новый A/B поэтому не использует ни одну из этих долей
как outcome: он суммирует фактические строки `turn_usage` каждого experimental slot.

### F2 — подходящий реальный corpus есть, но это узкий класс

Read-only probe по абсолютному окну `2026-08-25T00:00:00Z .. 2026-09-01T00:00:00Z` распаковывает
`bash -lc`/`timeout`/`env`, относит к repository-read прямые `Read/Grep/Glob/LS` и Bash-сегменты
`rg/grep/find/sed/cat/head/tail/ls/tree/wc/stat/file/awk/nl` либо read-only `git
show/log/diff/status/rev-parse/ls-files/grep`. Он нашёл:

- 105 worker-turns с настоящим несистемным `user_message` и ≥4 repository-read вызовами;
- 80 turns с ≥6 и 57 turns с ≥8;
- выбранные 12 задач дают 14 таких turns, 154 repository-read из 515 agent tool calls;
- у выбранных эпизодов максимум repository-read за один turn — от 5 до 31.

Команда: `python3 scripts/recon429/corpus_probe_432.py --min-repo 4 --group-tasks` [2].
Счётчик боевой `sessions` внутри probe: `467 → 467`; соединение открыто URI `mode=ro`.

**CONFIRMED** — tier 1, прямой read-only подсчёт строк `logs`/`turn_usage`.

### F3 — frozen corpus состоит из 12 repository-local завершённых задач

Правило отбора, замороженное до treatment:

1. scope ровно `/home/kesha/orchestra`, worker (`sessions.is_orchestrator=0`), task id непуст;
2. terminal turn попадает в абсолютное окно F2 и содержит несистемный `user_message`;
3. хотя бы один turn задачи имеет ≥5 repository-read вызовов по классификатору F2;
4. `tm_tasks.status='done'`, а `git_commits` непуст и каждый commit доступен;
5. в отобранных turns нет `WebSearch`, `WebFetch`, `curl` или `ssh`;
6. исключён bulk-repair живой production state (#422): это другой причинный класс;
7. из candidate table вручную заморожены 12 задач; это purposive corpus высоко-разведочных
   repository-local эпизодов, а не случайная выборка и не доказательство полноты всего парка.

Для каждой строки [corpus.tsv](corpus.tsv) заморожены task id, episode timestamp, session,
исторические `repo_calls`/`total_tools`, цена и `cache_read`, SHA trigger prompt, Git snapshot строго
до `tm_tasks.created_at`, result commit(s) и SHA-256 description [3]. Повторная команда
`python3 scripts/recon429/freeze_corpus_432.py` побайтно воспроизводит manifest и проверяет, что
result commits существуют. Внутри freeze `sessions: 467 → 467`.

**CONFIRMED** — tier 1 для происхождения corpus и tier 2 (Git/SQLite primary state) для снимков.

### F4 — payload cap получен только из pre-treatment source context

Для каждого frozen episode source-producing repo-tool (`Read/Grep`, shell `rg/grep/sed/cat/...`,
`git show/diff/grep`) спарен с ровно одним `tool_result` по non-null `tool_use_id`; metadata-only
`ls/find/git status/log/ls-files` не считаются. Два вызова без результата (#401, #415) явно
отмечены `unpaired=1` и в bytes не входят; duplicate result был бы hard failure. Считаются UTF-8
bytes фактически возвращённого source context, без result diff, oracle и treatment output.
Получилось 34,760..402,670 bytes на episode, nearest-rank p75 = 151,661 bytes;
следующий power of two = **262,144 bytes** [4]. P75, а не P95, выбран до treatment как явный
компромисс: bundle должен принуждать `filter_chunks/prune_context` и оставлять окно warm main под
задачу/implementation; достаточность не предполагается, а проверяется quality gate.

Treatment bundle ограничивается 262,144 UTF-8 bytes целиком в сериализованном JSON, включая path,
line range и framing. Это source-calibrated capacity heuristic, не заявка об оптимуме.

**CONFIRMED** для арифметики cap; **UNCERTAIN** для достаточности bundle — это проверит quality gate.

### F5 — ожидаемый main-only выигрыш правдоподобен, чистый выигрыш неизвестен

В baseline длинный parent prefix входит в каждый поисковый модельный вызов. В treatment он не
входит в scout loop, но остаётся в основном финальном/implementation loop. Поэтому main-only
`cache_read` должен снижаться, если bundle снимает хотя бы один main read; общая цена одновременно
получает новый scout loop и handoff. Без интервенции знак суммы не следует из #345.

**LIKELY** для снижения main-only `cache_read` — механизм следует из архитектуры вызовов и #345;
**UNCERTAIN** для общей цены — отсутствует A/B.

Причинный estimand — эффект **всего пакета** scout+ограниченные permissions+JSON handoff против
inline baseline. Разделить вклад role prompt, framing и удаления parent history этот двухплечевой
замер не может; cold control проверяет зависимость эффекта от history, но не превращает package
estimate в «чистую цену placement».

### F6 — класс, где схема заведомо не работает

`rg`-разведчик не может заменить решающее наблюдение, которого нет в frozen repository snapshot:
живое состояние SQLite/очереди/процесса, свежую веб-страницу/API, визуальную оценку изображения,
взаимодействие с пользователем или side effect. На таком задании он либо возвращает неполный
контекст, либо основная модель всё равно делает исходную внешнюю разведку; добавленный scout loop
не устраняет ни одного обязательного внешнего вызова.

Отдельный строгий нулевой случай — CLOSED ticket, где prompt уже содержит точный file+symbol,
AC и named test, а baseline делает 0 repository-read. У treatment число устранённых main calls
равно нулю, но scout/handoff не бесплатны; net savings невозможна по построению.

**CONFIRMED** как граница применимости интерфейса: локальный `rg` не производит внешний факт.

### F7 — vector/RAG не является альтернативным arm

#419 дал 0 unique wins vector против 6 у ordinary `rg`; `RAG_ENABLED=false`. Новый замер сравнивает
inline lexical retrieval с пакетом fresh-scout+handoff, а не vector/lexical quality [5].

**REFUTED** — возвращать vector arm противоречит frozen #419 и прямому запрету постановки.

## Exact measurement contract

Ниже правило подсчёта, которое должно войти в Phase 2 без переформулировки.

> **Experimental slot.** Slot = `(episode_id, repetition, arm)`, где 12 `episode_id` взяты
> побайтно из `docs/tasks/432/corpus.tsv`, `repetition ∈ {1,2}`, `arm ∈ {A,B}`. Один slot получает
> новый isolated checkout и новые session ids. A содержит только main session. B содержит scout
> session и main session. Все session ids и UTC `started_at`/`finished_at` записываются в frozen
> run manifest до чтения outcome.
>
> **Priced rows.** Для slot считаются ВСЕ строки copied run DB `turn_usage`, у которых
> `session_id` входит в manifest этого slot и `started_at <= ts <= finished_at`. Фильтра по `ok`
> или `stop_reason` НЕТ. `cost_A = SUM(cost_usd)` main session; `cost_B = SUM(cost_usd)` scout+main
> sessions. `cache_main_A = SUM(cache_read_tokens)` main; `cache_main_B` — main; `cache_net_B` —
> scout+main. Строка с `cost_unaccounted=1` или `cost_usd IS NULL` не превращается в ноль: slot =
> `MEASUREMENT_INVALID`, причина и уже наблюдавшаяся usage остаются в raw table. После начавшегося
> provider request retry запрещён; любой такой slot делает денежный verdict `INCOMPLETE`.
>
> **Tool rows.** Для diagnostics считаются ВСЕ строки copied run DB `logs`, у которых
> `type='tool'`, `session_id` входит в manifest и timestamp в том же slot interval. `FileChange`
> исключается как системная запись. `repo_call` классифицируется ровно функцией `classify()` из
> `scripts/recon429/corpus_probe_432.py`, включая распаковку Bash wrapper; знаменатель
> `tool_calls` — все agent tool rows после исключения `FileChange`, а не только named tools.
>
> **Denominator.** Основной A/B знаменатель = 24 парных наблюдения: 12 episodes × 2 repetitions.
> Quality failure НЕ исключает пару и её цену. Доказанный pre-provider failure (`provider_started=0`
> И ноль `turn_usage` rows) получает максимум один immediate retry с тем же frozen slot; оба
> availability attempts остаются в отдельном denominator по arm/role. Второй pre-provider failure
> или любой отказ после provider start делает slot/pair `INCOMPLETE`; замены другим episode нет.
>
> **Primary effect.** Для каждой пары `saving_i = 1 - cost_B_i / cost_A_i`. Primary estimate =
> median 24 `saving_i` с 90% bootstrap CI, где resampling cluster = episode (обе repetitions идут
> вместе). Secondary money-weighted estimate = `1 - SUM(cost_B)/SUM(cost_A)`. Аналогично считаются
> main-only и net `cache_read`. Для cost и main-cache публикуются разные A/A noise median/p90 и
> разные CI/threshold decisions; cost noise не является порогом cache. Net cache scout+main не
> имеет симметричного A/A control и остаётся descriptive. Нельзя делить Claude-
> счётчик на Codex-счётчик; experiment держит одну Luna model/runtime/effort во всех model roles.
>
> **Quality gate.** После завершения model process privileged controller копирует его result tree
> в отдельный judge checkout, затем накладывает oracle bundle из controller-only path и выполняет
> task-specific named command. Oracle path/commit не монтируется в model sandbox. Pass — exit 0 и
> frozen assertions; fail/timeout — fail. Adoption запрещён, если `B_passes < A_passes` по 24 slots
> или один episode имеет две B-only ошибки при хотя бы одном A pass. Цена всё равно считается по
> всем slots. Дополнительно печатается `SUM(cost)/passes`, но это secondary ratio.

## Experimental protocol

### 1. Изоляция и отсутствие утечки ответа

1. До первого импорта `app.*` сделать `sqlite3.Connection.backup` боевой БД в каталог на реальном
   диске под `scripts/recon429/run-<uuid>/`; задать абсолютный `ORCHESTRA_DB_PATH` копии.
2. Боевой `sessions` считать read-only непосредственно перед backup и после всего прогона; обе
   цифры обязаны совпасть. Phase 1 probes уже дали `467 → 467`, но Phase 2/3 печатает свои числа.
3. Каждый checkout строить не worktree и не local clone с общим object store: пустой repo +
   `git fetch --depth=1 file:///home/kesha/orchestra <snapshot>` + detached checkout. До запуска
   `git cat-file -e <result_commit>^{commit}` внутри checkout обязан вернуть non-zero.
4. Модель не получает Bash или произвольное чтение host FS. Оба arms используют одинаковые
   rooted read/search tools поверх `rg`; root = isolated checkout. Semantic/vector path отсутствует.
5. Oracle bundle создаётся Phase 2 controller-ом в отдельном path, checksum замораживается до
   model runs. До запуска canary требует: relative traversal и absolute oracle path → DENY;
   `result_commit` и oracle filenames отсутствуют в model checkout/tool transcript. Только после
   остановки model tools controller создаёт judge checkout и копирует oracle туда.
6. Raw parent transcript и customer data не коммитить. Run manifest содержит hashes и byte/token
   counts; private payload живёт только в run directory и проходит secret-form scan перед любым
   возможным сохранением.

### 2. Arms

- **A / inline:** warm main получает один и тот же frozen parent transcript prefix и trigger
  prompt; search/read/edit/test tools доступны в isolated checkout; выполняет исходную задачу.
- **B / scout:** fresh scout получает trigger prompt, task brief и только read/search tools;
  возвращает JSON bundle ≤262,144 UTF-8 bytes. Warm main получает тот же prefix+prompt и bundle;
  edit/test и fallback search доступны. Любой fallback считается, запрета «не искать» нет.
- Main/scout — один Luna alias и effort; read/search implementation одинакова. Scout имеет узкий
  role prompt, не получает parent transcript и не имеет write tools. Поэтому сравнивается весь
  production package, а не изолированный байт parent history; модель/retriever при этом не меняются.
- Warm prefix сериализуется из реальных `logs` до trigger row; берутся последние целые сообщения,
  помещающиеся в 120,000 токенов точного tokenizer текущего Luna backend. Tokenizer id/version и
  фактический размер печатаются. 120k оставляет больше половины эффективного 258k окна под task,
  search results и implementation; это production-shaped, но не точное восстановление нативного
  provider thread.

### 3. До-прогон, шум и порядок

1. **До любого B** взять 6 из 12 episodes по минимальным шести значениям
   `sha256("432:" + task_id)` и выполнить A0/A0 на неизменном code/model/prompt. Это обязательный
   «до против до».
2. Для каждого outcome `x ∈ {cost_usd, main_cache_read_tokens}` и episode: если
   `x_A01=x_A02=0`, то `noise_x_i=0`; иначе
   `noise_x_i = 2*abs(x_A01-x_A02)/(x_A01+x_A02)` (при одном нуле формула определена и даёт 2).
   Отдельно печатаются median/p90 cost-noise и main-cache-noise. Split-half: hash-odd и hash-even
   по три episodes; обе половины печатаются, только baseline A0/A0 входит в шум.
3. Основной порядок counterbalanced до run: чётный low bit `sha256("432-order:"+task_id)` →
   **A1/B1/A2/B2**, нечётный → **B1/A1/B2/A2**. Внутри каждого episode arms чередуются, а по
   corpus половина начинает A, половина B; episodes идут hash-order. Каждый slot — fresh
   checkout/session. Рядом печатаются `loadavg`, wall time, model, prompt revision, bundle bytes
   и provider availability.
4. Успех по цене объявляется только если quality gate зелёный, нижняя граница 90% clustered CI
   primary saving > 0, а median saving > p90 cost A/A noise. Main-cache получает отдельный вывод
   только при CI > 0 и median > p90 main-cache A/A noise. Net cache scout+main всегда descriptive,
   потому что baseline A/A не калибрует дополнительный scout distribution.
   Любой иной исход — «эффект не отделён от шума» либо «дешевле ценой качества», не «слабая
   экономия».

### 4. Negative controls

- **Cold-history control:** на трёх calibration episodes прогнать A/B с пустым parent prefix.
  Чистая экономия B не ожидается: если она появляется на уровне warm arm, измеряется различие
  инструкций/инструментов, а не снятие перечитывания диалога.
- **Zero-retrieval control:** CLOSED #409 (prompt уже содержит exact files, immutable test и AC)
  запустить с main-search disabled в обоих arms. A делает 0 repo calls; B обязан быть не дешевле.
  Если метрика объявляет обратное, классификация расходов или manifest неверны.
- **Permutation control:** после фиксации raw table перемешать B labels между episodes, сохранив
  распределение cost. Связь с pair обязана схлопнуться; это analysis-only, не новый model run.

## Counter-evidence and limitations

- Toast-публикация не даёт воспроизводимого corpus и половину заявленной токен-экономии связывает
  с собственным search backend; переносится только форма agent loop, не их число [5].
- В выбранных исторических turns есть implementation/test/coordination вызовы помимо 154 repo
  reads. Это намеренно end-to-end corpus, но лечение отвечает только за поисковую часть.
- Замороженные result commits — один известный правильный путь, не полный набор допустимых
  реализаций. Hidden behavioral tests уменьшают, но не устраняют риск отвергнуть валидную
  альтернативу; Phase 2 должен для каждого oracle прогнать исходный result commit (green) и
  baseline snapshot (red по missing behavior, не collection error).
- `logs` — канонический журнал Orchestra, но не побайтный provider thread. Warm replay
  production-shaped, а не exact; cold control и одинаковый prefix в паре ограничивают, но не
  устраняют эту угрозу.
- Все выбранные historical episodes — Codex workers в одном репозитории. Вывод переносится на
  Luna в этом harness; Claude/Opus transfer требует отдельного эксперимента и отдельного
  разрешения, потому что семантика/цена cache отличается.
- Задачи с внешним/live/visual evidence исключены; общую долю разведки из #345 нельзя умножить на
  найденный процент и объявить экономией всего парка.

## Affected files, risks, edge cases for later phases

- Разрешённая будущая поверхность: `scripts/recon429/` и `docs/tasks/432/`; `app/harness/` не
  трогать — им владеет #433.
- Phase 2 начинается с frozen oracle manifest: exact copied files, SHA-256, named command,
  expected failing assertion на baseline snapshot и green output на result commit по каждой
  задаче. До готовности manifest, red/green evidence и sandbox canary любой model run запрещён.
- Главный риск данных — случайно импортировать `app.db` до `ORCHESTRA_DB_PATH`; защита — отдельный
  process, env set первой строкой, live `sessions` before/after и read-only live connection.
- `cost_unaccounted`, provider failure, prompt overflow, missing result commit и доступ result SHA
  из checkout — fail loud, не ноль и не автоматический retry после раскрытия соседнего arm.
- #415 меняет только тест: oracle должен разрешать исправление тестового contract, а не требовать
  production diff. #416 не добавил тест в result commit: его named failing tests берутся дословно
  из frozen task description и проверяются отдельно.

## Review outcome

- Changed artifacts/consumers: `research.md`, `corpus.tsv`, три read-only probe scripts и append в
  `docs/kb/token-efficiency.md`; consumer — только будущая Phase 2 постановка, production runtime
  не изменён. Author metadata: `gpt-5.6-sol`, runtime `codex`.
- Exact AC: четыре пункта постановки #432 плюс отсутствие записи в production DB. Named checks:
  `freeze_corpus_432.py` побайтно равен `corpus.tsv`; `cap_probe_432.py` → p75 `151661`, cap
  `262144`, sessions `467→467`; `check_kb_contract.py` → `KB contract OK`; `py_compile` → RC 0.
- Route: two Luna prose rounds, предел исчерпан. Round 1 нашёл oracle-access blocker; Round 2
  подтвердил его `FIXED` и процитировал текущий artifact, но дал verdict `Needs work` из-за
  неопределённого `0/0` cache-noise.
- После round ceiling формула получила явное `0/0→0`, net-cache стал descriptive, а cap probe —
  non-null one-to-one source-only pairing с отчётом unpaired calls. Третий round не запускался;
  reviewer `APPROVED` не заявляется. Полный журнал и механическая post-review resolution —
  `docs/tasks/432/review-research-luna.md`.

## Sources

1. `docs/tasks/345/call-to-dollar.md`, `docs/tasks/345/tool-call-mix.md` — tier 1: цена вызова,
   cache-read decomposition, runtime split и отрицательные контроли.
2. `scripts/recon429/corpus_probe_432.py` — tier 1: read-only классификация реальных turns;
   команды и counts приведены выше.
3. `docs/tasks/432/corpus.tsv`, `scripts/recon429/freeze_corpus_432.py` — tier 1/2: frozen corpus,
   DB hashes и Git snapshots/result commits.
4. `scripts/recon429/cap_probe_432.py` — tier 1 read-only one-to-one pairing реальных source-
   producing repo-tool/result; bytes 34,760..402,670, p75=151,661, cap=262,144,
   два unpaired calls явно исключены, `sessions 467→467`.
5. `docs/kb/agent-memory-architecture.md` — primary-source synthesis Toast harness и frozen #419
   verdict 0 vector wins против 6 `rg`; исходные URL уже проверены владельцем раздела, в #432
   внешние источники заново не измерялись по прямому условию задачи.
6. `app/db.py:15-38,116-127,707-730` — primary code: `ORCHESTRA_DB_PATH`, `logs`, `turn_usage`.
7. `docs/kb/evidence-methods.md:19-21,88-94` — measured rules для A/B interleave, baseline noise,
   negative control и Bash wrapper classification.

## Phase 1 conclusion

Схема **правдоподобно** снимает main-only reread, но её net-экономия не доказана: свежий scout сам
создаёт агентный loop. Проверяемая единица — не «число поисков», а полная стоимость scout+main при
том же hidden behavioral oracle. Corpus, cap, знаменатель, A/A noise, A/B/A/B и controls теперь
заморожены; численного ответа «на сколько» до интервенционного прогона нет.
