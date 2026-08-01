# #115 — как Orchestra реально мержит worker-ветки

Дата снимка: 2026-08-01. Прод-код, live SQLite, journal и Git читались
read-only. Все Git-эксперименты выполнены в одноразовых репозиториях `/tmp`.

## Вопрос и критерий ответа

**Контекст.** В live DB есть 16 project scopes с оркестраторами; worker worktree
ведут как минимум к 19 доступным Git roots, потому что один scope может запускать
работу в другом репозитории (`COG-second-brain` → `inscryption-ai`, `seedon` →
`seedon/site`). Поэтому считать только каталог Orchestra или только `scope`
нельзя. [D1]

**Изменение под проверкой.** Сделать `merge_worker` единственным штатным
commit-point для worker-работы и оставить человеку только контролируемое
разрешение конфликтов/восстановление.

**Baseline.** Нынешний гибрид: `merge_worker`, а после timeout/conflict — raw
`git merge --squash`, `cherry-pick`, выборочный checkout или копирование файлов из
worktree.

**Измеримый outcome.** Работа worker не теряется; каждый вызов даёт однозначный и
непустой результат; target и worker остаются в известном состоянии; Git commit,
task links, RAG и lifecycle либо завершены, либо их можно идемпотентно
доделать; повтор вызова не запускает скрытую вторую мутацию.

## Гипотезы и фальсификаторы

1. **H1: ручной merge — редкое личное предпочтение, а не системный путь.**
   Фальсификатор: повторяемые bypass-операции в нескольких проектах и/или
   официальный prompt, который предписывает raw Git. **REFUTED.** В live логах
   bypass есть в Orchestra, Seedon, Kesha, Polus и COG/Inscryption; текущий
   orchestration prompt прямо велит при конфликте делать fresh branch +
   cherry-pick. [D2][C6]
2. **H2: основная причина отказов — настоящие Git-конфликты.** Фальсификатор:
   lifecycle/precondition failures встречаются чаще. **REFUTED.** Из 64 hard
   failures только 8 — content conflicts; 34 — явно busy/waiting, ещё 6 пустых
   30-секундных ошибок согласуются с timeout во время ожидания, 14 — dirty
   worktrees. [D3]
3. **H3: raw Git merge эквивалентен `merge_worker`, кроме красивого сообщения.**
   Фальсификатор: после одного и того же Git commit расходятся task links, RAG,
   worker ref и persisted lifecycle. **REFUTED.** Все эти side effects находятся
   после Git merge в route и raw Git их не вызывает; live DB и vec index уже
   содержат такие расхождения. [C2][D6][D7]
4. **H4: конфликт всегда откатывается в чистое состояние.** Фальсификатор:
   target после `ok=false` содержит staged/unmerged paths. **PARTIALLY REFUTED.**
   Related-history path безопасен в 6/6 прогонах, unrelated-history fallback
   оставил target dirty/conflicted в 3/3. [E1][E2]
5. **H5: двойной `#N: #N:` создаёт сам squash message builder.**
   Фальсификатор: builder удаляет task prefix из summary или двойные префиксы
   предшествуют этому коду. **CONFIRMED.** Builder собирает `#N` из исходных
   messages, затем без очистки дописывает тот же исходный summary; код существует
   с `f368e5b` от 2026-05-31. [C3][G2]

## 1. Что реально происходит

### 1.1 Точное окно live-логов

Снимок `data/orchestra.db` содержит **205 настоящих вызовов** `merge_worker` за
2026-07-24 17:39:52Z — 2026-08-01 07:36:26Z. Критерий вызова:
`logs.type='tool' AND content LIKE 'mcp__orchestra__merge_worker:%'`. Поиск
`LIKE '%merge_worker%'` даёт сотни ложных совпадений из кода, исследований и
tool output. Parallel Codex calls требуют связывать вызов с последующим
merge-специфичным `tool_result`, а не просто с ближайшим результатом. [D3]

| Caller scope | clean Git success | success + link warning | hard failure | всего |
|---|---:|---:|---:|---:|
| Orchestra | 58 | 9 | 27 | 94 |
| Seedon | 29 | 18 | 17 | 64 |
| Polus | 4 | 7 | 8 | 19 |
| Kesha | 8 | 2 | 6 | 16 |
| COG | 2 | 4 | 6 | 12 |
| **Всего** | **101** | **40** | **64** | **205** |

Итого Git успешно завершился в **141/205 (68.8%)** вызовах. В 40 случаях Git
успешен, а предупреждение относится только к task metadata; считать их failed
merges неправильно. [D3]

### 1.2 Ручные обходы

Для сопоставления зафиксирован закрытый срез непосредственно перед стартом этого
research worker: `logs.id <= 371999`, 2026-07-24 17:22:57Z —
2026-08-01 07:33:07Z. В нём 203 tool calls дали 139 content-producing success,
один no-op и 63 hard failures. Считать нужно сами merge-specific `tool_result`,
а не только `LEAD()` сразу после call: восемь успешных результатов отделены от
вызова параллельными tool events. Для manual засчитывался только target commit,
для которого в orchestrator log есть явная операция с named worker
branch/worktree и SHA подтверждён в target history. [D9]

| Project/scope | tool-created target commits | manual target commits | manual share среди strict-confirmed commits |
|---|---:|---:|---:|
| Orchestra | 67 | 8 | 10.7% |
| Seedon (root + site) | 46 | 6 | 11.5% |
| Polus | 11 | 2 | 15.4% |
| Kesha | 10 | 5 | 33.3% |
| COG scope | 6 | 11 | 64.7% |
| **Всего** | **140** | **32** | **18.6% из 172 confirmed** |

Итого в одном и том же retained window подтверждены **139 успешных штатных
content-producing merges**, ещё один failed tool call (`stash restore`) уже успел
создать target commit, и **32 ручных target commits**. При единой физической
единице strict-confirmed set содержит 140 tool-created и 32 manual commits:
**18.6% ручных среди этих 172 доказанных commits**. Это не upper bound для всей
retained population: opaque manual integrations могли не попасть в strict
classifier, поэтому истинная доля неизвестна. Один успешный `Merged 0 commits` не
является integration commit и из таблицы исключён. Logical integration intents
посчитать столь же точно нельзя: post-failure manual cleanup может относиться к
тому же намерению, а DTO не возвращает `target_after` для надёжной дедупликации.
[D3][D9]

Все **32/32** manual SHA отсутствуют в `tm_tasks.git_commits`; это не выборка, а
полный strict manifest найденных manual integrations в срезе. Из них **24/32**
имеют numeric `#N`, распознаваемый `_TASK_REF_RE`; каждый task был создан **до**
соответствующего commit timestamp и однозначно разрешается в caller project.
Именно эти 24 — доказанный missed-link ущерб raw пути. Остальные восемь (пять
subjects без ref и три `#prompt*`) штатный parser тоже не связал бы. Контрольные
tool commits (`a4d6a85` #93, `d96ae34` #110,
`d91c6d6` Seedon #180) присутствуют в соответствующих tasks. Open-set ограничение
остаётся: opaque direct commit без ссылки на worker branch/worktree нельзя честно
отличить от обычной разработки, поэтому 32 — строгая нижняя граница, а не
доказательство отсутствия скрытых ручных merges. [D6][D9][D10]

Систематический bypass подтверждён не во всех scopes, а в нескольких конкретных
workflow:

- **COG/Inscryption** — единственный manual-majority workflow: 11 manual против
  5 tool commits именно в `inscryption-ai` (шестой COG tool merge шёл в COG
  vault). Сначала оркестратор был вынужден писать прямо в target `main`, когда
  `spawn_worker(repo_path=...)` создавал worktree не в целевом repo; позже
  оркестратор продолжал сам делать squash/commit для задач #2, #7–#14 и явно
  формулировал правило «main трогаю я». Это смешанный, но систематически ручной
  workflow. [D2][D9][M1]
- **Kesha** — повторяемый fallback (5 manual против 10 tool): оркестратор создаёт
  `merge-*` от `main`, выборочно переносит файлы или
  cherry-pick'ит worker commits, затем fast-forward'ит `main`. Это буквально
  алгоритм, предписанный текущим prompt для conflict recovery. [D2][C6]
- **Orchestra, Seedon и Polus** не manual-majority: обходы в основном следовали
  за conflict, stale/diverged branch или пустой ошибкой. Seedon, например,
  перешёл на raw squash после двух 30-секундных пустых ошибок для
  `admin-analytics-site`; ещё один класс — ручное завершение partial merge после
  неудачного stash restore. Polus после conflict спасал worker-файлы копированием
  из worktree. В Orchestra raw Git использовался для `prompt-engineer` после
  пустых ошибок/conflict. [D2][D3][D9]

То есть это не «операторы забыли про тул». Часть обходов была рациональной
реакцией на реальные дефекты, а один обход прямо узаконен системным prompt.

### 1.3 Что можно и нельзя доказать за всю историю

Live `logs` удерживают только период с 2026-07-24, поэтому **точное историческое
отношение tool/manual до этой даты восстановить нельзя**: reflog показывает
результат Git, но не PID/HTTP route, а одиночный squash commit без task ref может
выглядеть как обычный ручной commit. Любое одно точное число «за всё время» было
бы выдумкой. [D1][G1]

Вместо этого измерен проверяемый lower bound по mainline histories 19 доступных
Git roots за период после включения squash (`2026-05-31`):

- 2,219 mainline commits всего;
- **532 commits** имеют строгую сигнатуру текущего tool builder — body
  `Squashed commits:` и/или повторённый task prefix;
- **424 commits** имеют двойной prefix, из них **65 в Orchestra**.

Это нижняя граница tool merges: одиночный worker commit без task ref сигнатуры не
оставляет. Остальные 1,687 commits нельзя честно делить на manual worker merges и
обычную прямую работу только по subject/reflog. [G2]

## 2. Почему `merge_worker` отказывает или врёт

### 2.1 Таксономия hard failures

| Класс | Частота | Доля всех calls | Смысл |
|---|---:|---:|---|
| explicit running/waiting | 34 | 16.6% | route не получил idle |
| пустая ошибка около 30s | 6 | 2.9% | вероятный client timeout; точный class не записан |
| target/worker dirty | 14 | 6.8% | 10 target, 4 worker |
| merge-tree/content conflict | 8 | 3.9% | настоящий Git conflict |
| missing target branch | 1 | 0.5% | rolling MCP↔route sentinel mismatch |
| post-merge stash restore | 1 | 0.5% | commit уже landed, cleanup failed |
| **Всего** | **64** | **31.2%** | |

Явно подтверждены **34/205 (16.6%)** busy/waiting failures; вместе с шестью
вероятными timeout во время того же idle wait lifecycle-класс достигает
**40/205 (19.5%)**, то есть в 4.25–5 раз больше Git conflicts. [D3]

Dirty failures тоже не сводятся к пользовательскому WIP:

- все 5 Orchestra target-dirty cases содержали `BUGS.md`; это известный конфликт
  с `report_bug` и задача #114;
- 3/4 worker-dirty cases вызваны machine-local/injected `.mcp.json` или
  `.serena/project.yml`; только один — реальный task document. [D3]

### 2.2 Пустая ошибка локализована, но exception class не записан

Все шесть результатов `Error executing tool merge_worker:` пришли через
**30.048–30.324 s**. `_api()` задаёт `httpx.AsyncClient(... timeout=30)` и не
ловит transport exceptions; `merge_worker()` тоже не имеет `try/except`.
Пустой `str()` совместим с `httpx.ReadTimeout`, но exception type нигде не
сохранился: точнее доказано «вероятный client-side `httpx.TimeoutException`», а
не конкретный subclass для всех шести. [C1][D3]

Server route при этом не fail-fast: `_wait_for_merge_idle()` без локального
deadline ждёт `session.wait_for_turn_completion()`. Поэтому timeout клиента не
означает отмену server operation. [C2]

Live journal доказывает продолжение server work для четырёх вызовов
`prompt-engineer`: после пустых client errors, когда worker стал idle, journal
записал **пять одинаковых merge-tree prechecks за одну секунду** — четыре старых
HTTP requests плюс актуальная пятая попытка. Для двух Seedon errors server outcome
не доказан. В этом incident conflict предотвратил mutation. Session/repo locks
сериализуют requests, а первый чистый success обычно reset'ит worker, поэтому
повторный Git content commit не доказан и обычно превратился бы в no-op; повторные
lifecycle/RAG side effects и гонка с raw recovery всё равно остаются возможны.
[C2][C3][J1]

Следовательно, пустая ошибка — не просто плохой текст. Это **неопределённый
outcome**: caller не знает, завершится ли старая операция позже, и безопасный retry
невозможен.

### 2.3 Где ещё теряется смысл ошибки

- HTTP `>=400` превращается в `{"error": r.text}`: status code и structured JSON
  теряются, а caller получает вложенную строку вроде
  `Merge failed: {"error":"..."}`. Пустой body проваливается в generic
  `unknown error`. [C1]
- Route оборачивает post-Git блок широким `except Exception` и возвращает
  `str(e)`. Исключение с пустым `str` снова даёт пустой detail; главное — commit
  может уже существовать, хотя DTO говорит `Merge failed`. [C2]
- Conflict DTO содержит только filenames. MCP выбрасывает target/base/head/state;
  path parser использует `split()[-1]`, поэтому `shared file.txt` превращается в
  `file.txt`. [C1][C3][E3]
- `merge-tree` ищет только строки, начинающиеся с английского `CONFLICT`.
  Локализованный Git пишет `КОНФЛИКТ`, и route возвращает огромный generic
  `merge precheck failed` вместо списка paths. Это видно в live COG/Seedon logs.
  [C3][D3]
- `merge-base` с любым nonzero трактуется как unrelated history; operational
  error теряется и может ошибочно запустить full-history cherry-pick. Ошибки
  `rev-list`, old-head capture, reset/abort и worker reset местами игнорируются или
  остаются только в server log. [C3]
- Restore исходного primary checkout после уже успешного commit может заменить
  success DTO на `restore_failed`; route тогда пропускает links/RAG/lifecycle,
  хотя target и worker refs уже сдвинуты. [C3][E4]

### 2.4 Реальное поведение при conflict

**Related history, обычный путь.** `merge-tree --write-tree` выполняется до
мутации target. Для add/add conflict три независимых прогона вернули
`{ok:false, conflicts:['same.txt']}`; target/worker HEAD и оба status не менялись,
`MERGE_HEAD` отсутствовал. Ещё три прогона принудительно пропустили preflight и
довели conflict до `git merge --squash`; `git reset --merge` восстановил чистое
состояние в 3/3. Итого проверенные related cases безопасны **6/6**, хотя return
value cleanup не проверяет. [E1]

**Unrelated history fallback.** Код cherry-pick'ит **всю** worker history с
`--no-commit`. Если ранний commit применился, а поздний конфликтует,
`cherry-pick --abort` не вернул исходный index/worktree. В 3/3 прогонах:

```text
result.ok = false
target HEAD unchanged
target status = "A  safe.txt\nAA shared.txt"
MERGE_HEAD/CHERRY_PICK_HEAD absent
worker clean and unchanged
```

То есть target остаётся в полумёрже и следующий merge блокируется dirty preflight.
Старый target SHA не возвращается API, восстановление требует reflog/ручного
`reset --hard`. [C3][E2]

### 2.5 Base branch, squash и task switch

- Target берётся из persisted `session.base_branch`; explicit `target` его
  переопределяет. Resolver проверяет local branch и не доверяет текущему checkout.
  Это правильная база. [C2][C3]
- Related merge: merge-base → merge-tree preflight → `rev-list target..worker` →
  `git merge --squash` → один commit. После success worker worktree hard-reset'ится
  на target SHA. Старые worker commits перестают быть ancestors и остаются как
  provenance только в reflog до GC. [C3]
- Unrelated merge: все commits branch replay'ятся, что может включить лишнюю
  историю и имеет описанный dirty-target bug. [C3]
- Mutable parent base остаётся сложным: child→parent squash/reset, затем
  parent→main squash/reset меняет parent ref на новый несвязанный hash. #93 уже
  вводит общий repo lock и quarantine/rollback вокруг switch; наше решение не
  должно создавать второй lock или второй lifecycle protocol. [C7]
- `next_task_id` сейчас валидируется **после** Git commit. Ошибка может превратить
  успешный merge в HTTP failure; switch запускается с `force=True` и имеет свои
  rollback gaps. #93 T1/T2 уже планирует prevalidation и success/partial DTO — эту
  область нельзя дублировать в #115. [C2][C7]

## 3. Что raw Git пропускает и какой ущерб уже виден

### 3.1 Полный список side effects штатного пути

`merge_worker` — это не alias для `git merge`:

1. сериализует session/lifecycle и пытается дождаться terminal idle;
2. резолвит persisted base и проверяет target/worker cleanliness;
3. берёт repo merge lock, определяет checkout owner, временно переключает primary
   checkout при необходимости и восстанавливает его;
4. делает preflight, squash/cherry-pick и commit;
5. пытается hard-reset'ить **worker branch/worktree** на новый target; reset
   failure сейчас только логируется и не меняет `ok=true`;
6. парсит созданный target commit: task refs, hash, date, files, insertions,
   deletions;
7. идемпотентно пишет commits в `tm_tasks.git_commits` и увеличивает
   `sync_revision`;
8. запускает RAG backfill всех `.md` и agent logs scope;
9. persist'ит lifecycle: `branch`, `base_branch`, `task_id=''`,
   `needs_switch=true`;
10. при `next_task_id`: создаёт/переключает fresh task branch, второй раз persist'ит
    lifecycle, снимает `needs_switch`, ставит task `in_progress` и запускает
    внешний sync.

Эти шаги не объединены одной транзакцией; failure после commit может оставить их
частично выполненными. [C2][C3][C4][C5]

### 3.2 Live damage от ручного пути

**Task provenance.** Проверен полный strict manifest из 32 manual integration
commits: 2 Polus, 11 Inscryption, 5 Kesha, 6 Seedon и 8 Orchestra. Все 32
отсутствуют в `tm_tasks.git_commits`, но доказанный causal denominator — **24**:
их numeric refs распознаются текущим regex и tasks разрешаются в project. Восемь
остальных штатный parser тоже пропустил бы. Ущерб восстанавливаем по Git history,
пока commit message однозначно содержит task ref; для adhoc/selective/conflict
merges автоматическая атрибуция уже неоднозначна. [D6][D9][D10]

**RAG freshness.** Read-only сравнение SHA-256 live files с `data/vec.db` нашло
133 stale entries из 3,264. Это число нельзя целиком приписать manual merges, но
прямая улика есть: в Orchestra единственный stale file —
`docs/workers/prompt-engineer.md`, тот самый файл, который был трижды перенесён raw
Git; indexed SHA и live SHA расходятся. Полный reindex восстанавливает данные, а
последующий tool merge того же scope может случайно исцелить их. [D7]

**Lifecycle/ref state.** Raw merge не вызывает reset worker и не выставляет
`needs_switch=true`. Live rows после bypass с этим согласуются:

- `prompt-engineer`: branch `adhoc-568267/prompt-engineer`, `needs_switch=0`;
- `admin-analytics-site`: archived на `task-181/...`, `task_id=181`,
  `needs_switch=0`;
- COG workers `impl-game-ux`/`feat-mccfr-scale` остались на старых task branches и
  task ids; их branches одновременно ahead и behind current main.

Следующее сообщение такому worker не обязано создать fresh branch: оно может
продолжить старую diverged history и породить повторный add/add — именно это
произошло с `prompt-engineer`. Но divergence не является уникальным маркером raw
bypass: штатный worker reset fail-soft и тоже может оставить старый ref при
`ok=true`. [C3][D8]

**Recoverability.** Git content обычно можно спасти из target history и reflog;
task links можно backfill'ить по однозначным numeric refs; RAG — полным reindex;
lifecycle — reset/switch + persisted reconciliation. Но raw Git не сохраняет
operation record (`worker_head`, `target_before`, `target_after`, source task,
conflict decisions). После reflog expiry или selective copy эта provenance
необратимо теряется. [C2][C3][D6]

### 3.3 Прямой вердикт

**Raw ручной merge не является допустимым штатным fallback.** Он может сохранить
Git-файлы, когда tool сломан, но одновременно портит control-plane state Orchestra:
task provenance, RAG freshness и lifecycle/ref relation расходятся. Поэтому сегодня
это аварийная операция спасения данных, после которой обязателен reconcile; без
reconcile — прямая порча состояния.

Но запрещать raw Git прямо сейчас тоже опасно. `merge_worker` имеет неопределённый
timeout outcome, unrelated fallback сам оставляет target conflicted, а post-commit
failure выдаёт success за failure. Сначала нужен покрывающий эти случаи legal
recovery path, затем prompt-ban.

## 4. Рекомендуемое направление

### Мера 1 — bounded wait плюс durable operation contract

Route должен быстро завершать busy precondition до MCP deadline. Кроме того,
caller создаёт idempotency key **до первого request**, передаёт его в исходный
`merge_worker` и повторно использует после потерянного ответа; server обязан
durably записать `PENDING` по этому key до первой Git mutation. Server-generated
ID внутри ответа недостаточен: потеря именно этого ответа снова оставит caller без
ключа. Даже чистый Git→DB→lifecycle может пережить HTTP response или client
disconnect. Результат должен разделять
`git.status`, `metadata`, `lifecycle`,
`next_task`, содержать exception class, HTTP status, retryable flag и pinned
`worker_head/target_before/target_after`. Retry одного idempotency key возвращает тот
же результат, а не запускает вторую мутацию.

- **Цена:** medium; MCP wrapper + route + tests, возможно маленькая operation
  table.
- **Риск ошибки:** rolling old-MCP/new-route contract и неверная cancellation
  семантика могут снова создать duplicate mutation. Нужны live-value validation и
  restart coordination.
- **Overlap #93:** session/lifecycle/repo locks и commit-point rollback остаются
  реализацией #93. #115 добавляет transport/idempotency boundary, не второй lock.

### Мера 2 — legal conflict workflow, в котором target пишет только tool

Для обычного conflict tool возвращает точные paths + pinned SHAs и одну командную
схему: worker подтягивает target **в свою branch**, разрешает конфликт и коммитит;
после этого оркестратор повторяет `merge_worker`. Нельзя автоматически выбирать
`ours/theirs`: это и есть место, где теряется работа. Исправление unrelated
rollback, snapshot verification и `rollback_failed` DTO — prerequisite из #93
T1/T2, а не новая реализация #115.

- **Цена:** small/medium поверх завершённых #93 T1/T2.
- **Риск ошибки:** автоматическое разрешение или неверный base может тихо удалить
  одну сторону. Поэтому fail closed и никакого содержательного auto-resolution.
- **Что меняется:** только после появления legal path заменить текущую prompt-строку
  «cherry-pick вручную» и запретить raw target mutations.

### Мера 3 — commit-aware reconcile/finalize для partial и исторических ручных merges

Нужен один официальный recovery path: по session + pinned target commit проверить,
что commit действительно содержит worker delta, затем идемпотентно выполнить
links, RAG enqueue и lifecycle persist. Worker reset разрешён только через
compare-and-swap: current branch + HEAD точно равны pinned `worker_head`, полный
worker tree представлен в target, а перед reset создан durable backup ref. При
CAS mismatch reconcile не двигает worker ref и не маскирует более новую работу.
Путь чинит случаи «commit landed, restore/persist/link failed» и позволяет
backfill уже найденных manual commits. Не принимать произвольный SHA без
ancestry/tree verification.

- **Цена:** medium/high; это граница Git↔DB↔RAG и миграционный backfill.
- **Риск ошибки:** неверно adopted commit или reset не той branch — прямой риск
  потери worker work. Нужны exact SHA, clean checks, dry-run manifest и reflog
  evidence.
- **Overlap #93:** использовать его quarantine/partial-success DTO и stable repo
  lock; не строить параллельную state machine.

### Отдельные дешёвые исправления

- `_build_squash_message` не должен повторно добавлять уже присутствующий prefix;
  regression test на `#93: research` → один `#93:`. Цена small, риск — сломать
  multi-task refs, поэтому отдельно тестировать `#1, #2` и legacy `ABC-1`.
- Structured link warnings уже лучше legacy `unknown`, но `task not found` нужно
  считать metadata warning и дать reconcile action, а не оставлять жёлтый текст без
  восстановления.
- #114 должен убрать `report_bug` из tracked target или коммитить через отдельный
  безопасный канал; #115 не дублирует этот фикс.

## Confidence и counter-evidence

| Finding | Confidence | Основание |
|---|---|---|
| 205 calls / outcome taxonomy | **CONFIRMED** | direct live SQLite + robust pairing |
| 34 explicit busy/waiting failures | **CONFIRMED** | direct caller-visible results |
| 6 empty errors are client timeouts | **LIKELY** | exact ~30s timings + code; exception class not persisted |
| 4 timed-out requests continued server-side | **CONFIRMED** | later journal prechecks; two Seedon outcomes unknown |
| related conflict leaves clean state | **LIKELY** | 6/6 temp runs; cleanup return still unchecked |
| unrelated conflict dirties target | **CONFIRMED** | 3/3 temp runs + exact status |
| raw merge skips side effects | **CONFIRMED** | direct code path + live DB/RAG/lifecycle samples |
| full-history auto/manual ratio | **UNCERTAIN** | raw logs retained only from 07-24; Git signature is lower bound |
| 424 doubled prefixes are tool builder output | **CONFIRMED** | source/blame + mainline scan |

Counter-evidence против слишком жёсткого вывода:

- raw merge иногда единственный способ **сохранить Git content** при сломанном
  tool; немедленный запрет до legal recovery повысит, а не снизит риск потери;
- 141/205 tool calls успешно завершили Git, а обычный related conflict был clean в
  экспериментах — механизм не нужно переписывать целиком;
- locks + worker reset делают duplicate content commit от stale retry менее
  вероятным; доказана неоднозначность outcome, но не повторный Git commit;
- task-link warning не означает failed merge; 40 таких calls должны оставаться
  success/partial, иначе оператор закономерно повторяет уже выполненную мутацию;
- 133 stale RAG entries имеют несколько причин, поэтому только конкретный
  `prompt-engineer.md` использован как прямая manual-merge улика.

## Риски и edge cases для будущего плана

- client disconnect/cancellation во время `asyncio.to_thread` merge;
- server restart между Git commit и lifecycle persist;
- restore primary checkout failure после commit;
- target checked out в parent worktree;
- branch/head moving между preflight и commit;
- localized Git output и paths с пробелами/newlines;
- unrelated histories, empty cherry-picks, hooks rejecting commit;
- `next_task_id` invalid/missing/duplicate across projects;
- manual/selective commit без numeric task ref;
- RAG disabled, queue delayed или backfill не завершён до следующего search;
- reflog expiry/GC до reconciliation;
- old MCP subprocess против нового in-memory route до restart.

## Evidence index

### Live measurements

- **[D1]** `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, read-only:
  378 session rows, 18 historical scopes, 16 scopes с orchestrator; logs start
  2026-07-24. Existing worktrees/scopes resolve to 19 relevant accessible Git
  roots in the history scan.
- **[D2]** `logs` tool calls and paired Bash results: raw squash, cherry-pick,
  selective checkout/copy + commit in Orchestra, Seedon, Kesha, Polus,
  COG/Inscryption.
- **[D3]** exact merge census, live DB snapshot max log id 373177
  (2026-08-01T07:40:00Z): 205 calls, project matrix and failure taxonomy above.
- **[D6]** `tm_tasks` + `json_each(git_commits)`: все 32 strict manual commit
  hashes missing; 24 numeric refs resolve in caller project; three tool-generated
  controls linked.
- **[D7]** `data/vec.db` vs SHA-256 of live files: 133/3,264 stale;
  Orchestra stale file = `docs/workers/prompt-engineer.md`.
- **[D8]** live `sessions` rows + `git rev-list/diff` for manually merged workers:
  old task ids/branches, `needs_switch=0`, branches ahead and behind main.
- **[D9]** frozen retained-log integration census (`logs.id <= 371999`): 203 tool
  calls/results, 139 content successes, one no-op, 63 failures; one failed tool
  call created a target commit; 32/32 explicit manual target SHAs verified as
  commits and ancestors of their targets. Counting tool results directly corrects
  an eight-success undercount produced by immediate-`LEAD()` pairing when parallel
  tool events intervene.
- **[D10]** `git show -s --format=%s,%cI` for all 32 manual SHAs + live
  `tm_tasks` lookup in the caller project: 24 subjects have recognized numeric
  refs; all 24 tasks resolve and have `created_at` earlier than the corresponding
  commit timestamp. Eight subjects have no recognized ref.
- **[J1]** `journalctl -u orchestra --utc` around prompt-engineer timeouts: five
  delayed identical merge-tree prechecks after four caller timeouts.
- **[G1]** Git history/reflog limitation: result has no reliable caller identity.
- **[G2]** 19 mainlines since 2026-05-31: 2,219 commits, 532 strict tool
  signatures, 424 double prefixes, 65 double prefixes in Orchestra.
- **[E1]** `/tmp` related add/add: preflight 3/3 safe; forced post-preflight merge
  conflict 3/3 safe.
- **[E2]** `/tmp` unrelated two-commit branch: 3/3 target dirty
  (`A safe.txt`, `AA shared.txt`) after `ok=false`.
- **[E3]** `/tmp` path-with-space conflict: returned basename only, not full path.
- **[E4]** `/tmp` injected restore failure: target commit and worker reset happened,
  result overwritten to `ok=false, state=restore_failed`.

### Primary code sources

- **[C1]** `app/mcp_stdio.py:76-96,492-530` — HTTP timeout/error flattening and
  merge result formatting.
- **[C2]** `app/routes/sessions.py:25-31,670-766` — idle wait, route locks,
  post-commit links/RAG/lifecycle/switch and broad exception boundary.
- **[C3]** `app/workspace.py:490-530,585-640,664-914,920-970` — message builder,
  unrelated fallback, squash, cleanup/reset, commit parsing.
- **[C4]** `app/tm.py:324-364` — idempotent task commit linking.
- **[C5]** `app/rag_service.py:87-104` — scope backfill.
- **[C6]** `pipelines/default/prompts/modules/orchestration.md:124-127` — current
  prompt explicitly directs fresh-branch cherry-pick on conflict.
- **[C7]** `docs/tasks/93/plan.md` — stable repo lock, quarantine, rollback,
  prevalidation and partial-success DTO already owned by #93.
- **[M1]** cross-project memory/log evidence for the historical COG
  `spawn_worker(repo_path)` mismatch and explicit direct-main authorization.
