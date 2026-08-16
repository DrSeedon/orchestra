# #289 — ROI `codex_review`: задержка, same-model и Luna default

**Phase 1 research only.** Исторический cutoff: `2026-08-16T10:07:30.748436+00:00`.
Эксперимент Luna/Sol проведён отдельно после заморозки корпуса и предрегистрации.

## Короткий ответ

1. **Review добавляет заметную, но не доминирующую задержку.** На 182 точно
   спаренных успешных вызовах медиана review wall — **79.0 с**, p90 —
   **180.1 с**. В 37 завершённых matched tasks объединённое review wall занимает
   медианно **4.80%** полного цикла задачи, p90 **12.93%**. Это верхняя граница
   task-path overhead, а не автоматически задержка пользователя: tool запускает
   background job; в **120/190 (63.2%)** интервалах параллельно шли чужие turns.
   При этом вызывающий агент не делал других tool calls в **123/190 (64.7%)**
   интервалах — локально он обычно ждал результат. [M1][M2]

2. **Свежий Sol-thread полезен, но не независим.** История содержит реальную
   пользу — например, review #230 нашёл 11 lifecycle blockers за три раунда, а
   review исследовательской прозы #194 дало 7 принятых содержательных поправок
   из 8. Но новая слепая пара Luna/Sol одинаково пропустила оба заранее скрытых
   механизма блокеров K2 и Q4. Свежий контекст снимает зависимость от текущего
   transcript, но одинаковые пропуски совместимы с общими parametric blind spots.
   Это наблюдение, не causal estimate эффекта свежего thread. [M5][M7][M10]

3. **Luna можно сделать default только для низкого/среднего риска с сильным
   oracle; нельзя — для shared-runtime/security как единственного reviewer.** В
   минимальном предзарегистрированном N=4 Luna и Sol дали одинаковый вектор
   `PASS/PASS/BLOCK/PASS`, одинаковый primary recall **0/2** и FP **0/2**.
   Каждая нашла другой настоящий blocker в Q4 — потерю important-сообщения после
   трёх неудач, — но обе пропустили предзарегистрированное starvation из-за lock
   через sleep/retry. Luna стоила **$0.00650 API-equivalent** против Sol
   **$0.18384** (в **28.3×** меньше), но один прогон не доказывает ни качество,
   ни latency superiority. [M4][M5][M6]

4. **Рекомендуемый режим — гибрид B+C:** Luna first/default review для обычной
   работы с сильным oracle, Sol escalation по реальному blocker/неясности;
   cross-family Opus — только для high-risk shared runtime/security, особенно
   когда автор Sol. Убирать review целиком нельзя: нынешние escape-примеры
   показывают и слепые зоны reviewer, и ещё более опасный класс — критические
   изменения вообще без review. [M3][M8][M9]

## 1. Вопрос и конкурирующие гипотезы

### Контекст, изменение, baseline, outcome

- **Контекст:** Orchestra — личная/малокомандная система с большим числом
  параллельных agent turns; главный ущерб — crash/corruption/security и отказ
  shared runtime, а также quota/wall latency.
- **Изменение:** заменить Sol default review на Luna там, где это безопасно, и
  определить место cross-family review.
- **Baseline:** нынешний Sol reviewer; альтернативы — no review, Luna default +
  Sol escalation и cross-family only high-risk.
- **Измеримые outcomes:** review wall, доля task cycle, API-equivalent cost и
  quota proxy, принятые/исправленные findings, blinded blocker recall и
  blocking false positives.

### Гипотезы и falsifiers

| Гипотеза | Что опровергает | Итог |
|---|---|---|
| H1: review существенно тормозит полный цикл | median task-cycle share мала, а wall перекрывается чужой работой | **REFUTED в сильной форме:** median 4.80%, p90 12.93%; overhead реален, но не доминирует |
| H2: свежий Sol reviewer достаточно независим от Sol-author | заранее скрытый blocker, одинаково пропущенный fresh same-family reviewers | **REFUTED как гарантия независимости:** K2 и Q4 пропущены обоими; полезность review не refuted |
| H3: Luna явно хуже Sol как default reviewer | Sol-only required hit или Luna-only blocking FP | **НЕ НАБЛЮДАЛОСЬ:** одинаковые 0/2 hits и 0/2 FP, но N=4 не доказывает equivalence |
| H4: review не окупается и его можно убрать | проверенный новый blocker или принятый actionable finding | **REFUTED для нетривиальной/high-risk работы:** исторические review дали исправленные blockers и содержательные правки |
| H5: качество определяется только выбором модели | unreviewed incidents, слабый oracle или проигнорированный finding вызывают escape | **SUPPORTED как конкурирующее объяснение:** coverage/follow-through остаются load-bearing |

## 2. Что было известно до обновления

Сначала воспроизведены несущие числа предыдущего отчёта, без нового
переопределения его выборки. Скрипт перечитал оба TSV и получил: [M1][M2][M3]

- **98** исторических `codex_review` calls: 75 Sol backend / 23 Claude;
  `exec=45`, `resume=40`, `review=13`.
- **45** blind-graded review artifacts; **5** Sol-arm файлов были reader tests,
  а не adversarial reviews.
- После очистки: Sol `n=26`, zero-substantive `3/26`, blocking `10/26`, median
  substantive `4.0`, mean `4.31`; Claude `n=14`, `0/14`, `9/14`, median `4.5`,
  mean `5.86`.
- Fisher exact для zero-substantive: **p=0.53947**, то есть прежнее **p≈0.54**.
  Различие не обнаружено, но arms полностью confounded типом задачи и эпохой;
  результат не является non-inferiority proof.
- Review шёл тем же checkpoint Sol; свежий процесс менял контекст, но не веса.
- Найдены **n=2 Sol→Sol escapes**; оба направленно тревожны, но n=2 и
  Sol-доминированный search space не позволяют причинного вывода.
- Прежние **~7.5% Codex pool** были extrapolation из 98 call counts и медиан
  `n=11` измеренных jobs, а не прямой quota attribution.

Что изменилось к новому cutoff: появились per-review `turn_usage`, измерение wall
и task-cycle share, 235 удержанных calls, а также предзарегистрированная Luna/Sol
пара. Старый вывод «нет обнаружимого Sol-vs-Claude gap» сохраняется; новая пара
не показывает Luna хуже, но впервые даёт прямой common-miss counterexample.

## 3. Метод и границы cohort

### Исторический cohort

С live SQLite снята WAL-safe копия через `sqlite3.Connection.backup()`;
`PRAGMA integrity_check = ok`. Ни process argv/cmdline/environ, ни `.env`, ни raw
tool logs не читались и не сохранялись. После построения агрегатов backup удалён.
[M1][M2]

До cutoff найдено **235 invocations**, **101 unique artifact paths**, из них
**96** доступны (**95.0%**). По фазам: impl 95, research 83, plan 41, other 16;
по mode: resume 115, exec 98, review 22. Scope: Orchestra 210, Seedon 18,
Kesha-TG-Bot 4, DnD 3. [M1]

Reviewer model во всех 235 calls — Sol. Ближайший author model: Sol 136, Opus
86, Luna 13; это attribution, не рандомизация. Среди доступных 96 artifacts
round distribution 1/2/3/4/5/7 = 17/39/25/10/4/1. Поэтому 115 resume calls —
не редкий edge case, а существенная часть текущего процесса. [M1]

Атрибуция сделана так:

- start — timestamp tool invocation; end/status — **точно совпавшее** уведомление
  фонового job, без хронологического fallback;
- author runtime/model — ближайший caller `turn_usage`, а не текущее поле
  `sessions.model`, которое переписывается при model switch;
- reviewer — `gpt-5.6-sol`, зафиксированный `codex_review` runtime;
- phase — имя artifact/target; rounds — mode и разбиение сохранённого artifact;
- tokens/cache/output/cost — `turn_usage` с `event_id=codex-review:*`, доступный
  для 125 новых review turns.

Точно спарены **190/235 (80.9%)**: 182 completed, 7 failed, 1 timed out,
45 unpaired. Среди paired success **95.8%**, failure/timeout **4.2%**. Unpaired
означает retention/template gap, а не автоматически failure. Logs retention и
отсутствующие/удалённые worktrees не позволяют честно восстановить всё до
первого удержанного timestamp. [M1][M2]

### Luna/Sol A/B

До model calls commit `0138b371` заморозил preregistration, N=4 corpus и exact
prompt. Hashes корпуса и prompt, а также hidden-ground-truth commitment
механически совпали при reveal. Два defect cases и два clean controls получили
по одному fresh review от Luna и Sol; prompt, порядок, cwd, scope и `high`
effort совпадали; retry/resume не было. Outputs сначала hash-сортировались в
anonymous arms, затем оценивались против commitment и только после этого
получили model labels. [M4][M5]

N=4 — минимальный **операционный falsifier** утверждения «Luna явно не хуже», а
не статистический тест equivalence. Из-за двух foreign Sol turns между provider
snapshots точный quota расход пары неразложим; integer provider counter остался
12→12, reset не менялся, поэтому gate `≤1 pp` не нарушен, но quota cost каждого
arm остаётся unresolved. По prereg stop rule дополнительных turns не запускалось.
[M5]

## 4. Насколько review замедляет полный цикл

### Wall

| Cohort | n | median | p90 | mean | sum |
|---|---:|---:|---:|---:|---:|
| Успешные paired reviews | 182 | **79.0 с** | **180.1 с** | 117.8 с | 5.95 ч |
| Все paired, включая failure/timeout | 190 | 79.1 с | 180.2 с | 119.2 с | 6.29 ч |

По фазам для completed: impl `n=77`, median 71.8 с, p90 212.7 с; plan
`n=33`, 79.0/147.7 с; research `n=62`, 90.0/147.6 с; other `n=10`,
50.4/109.9 с. [M1]

### Доля task cycle и critical path

Для 37 задач, где tracker `created_at→completed_at` и review intervals можно
сопоставить, пересекающиеся review intervals объединены. Получено:

- median review-wall share **4.8009%**;
- p90 **12.9260%**;
- mean **5.7099%**.

Это **верхняя граница task-path share**, а не causal user wait. `codex_review`
возвращается как background job. В 67/190 paired intervals caller продолжал
tool work, в 123/190 — нет; в 120/190 шли 344 foreign turns. Следовательно:

- review обычно создаёт локальную паузу у автора;
- Orchestra часто утилизирует эту паузу параллельной работой;
- `elapsed review wall = user delay` — неверное равенство;
- для последовательной одиночной задачи разумная наблюдаемая цена ближе к
  79 с/call, а для всего портфеля — ниже из-за overlap.

**Confidence: CONFIRMED для описанного cohort** — direct timestamp measurement;
**LIKELY для будущих задач** — matched tasks всего 37, allocation review к
user-visible milestone не наблюдается. [M1][M2]

## 5. Cost, quota и yield

### Tokens и API-equivalent cost

Для 125 review turns с нативной usage telemetry: [M1]

| Метрика | median | p90 | sum |
|---|---:|---:|---:|
| input tokens | 427,958 | 874,625 | 61.31M |
| cached input | 369,664 | 777,882 | 51.82M |
| output | 2,983 | 4,903 | 386,974 |
| API-equivalent $ | **0.6386** | **1.1178** | **84.9432** |

Cache ratio — **84.53%**. В том же accounting window все Codex turns стоили
виртуальные `$969.9106`; review share — **8.76% cost** и **24.80% turns**.
Это лучше инструментировано, чем прежние ~7.5%, и находится в том же порядке,
но метрики не идентичны: старая оценка экстраполировала credits, новая делит
API-equivalent cost.

В последнем непрерывном reset segment перед cutoff Codex counter вырос 0→11 pp:
review `$9.5608` из `$144.6606`, то есть **6.61% cost proxy** и пропорционально
**0.727 pp** из 11. Counter глобальный и целочисленный; это accounting proxy,
не причинное списание review. Полный window пересёк 14 reset values, поэтому его
delta −40 pp для attribution не используется. [M1]

### Actionable yield

В 96 доступных artifacts сохранённого live-call cohort parser нашёл 131
строго-якорных `fixed/resolved/accepted/ack` markers. Получается proxy: [M1][M2]

- **0.720** accepted/fixed marker на completed review turn;
- **0.367** на минуту completed review wall;
- **1.542** на API-equivalent dollar.

Это follow-through, не ground truth качества. Marker может относиться к одной
части multi-round finding или быть авторским self-report. По той же синтаксической
шкале **44/96 (45.8%)** artifacts не имеют initial blocking/suggestion marker.
Это **не zero-value rate**: clean approval, question-only review и parser miss
попадают в тот же бакет. Ретроспектива не даёт честный false-positive rate:
`rejected/not-a-problem=0` в текущем срезе означает отсутствие явного маркера,
а не отсутствие ложных тревог.

Единственный корпус с заранее скрытым ground truth — A/B: required-blocker
recall Luna **0/2**, Sol **0/2**; blocking FP на clean controls Luna **0/2**, Sol
**0/2**. Обе нашли один и тот же дополнительный валидный Q4 blocker. Описательная
скорость этого secondary value: Luna **0.650 blocker/min** и **153.9/$**, Sol
**0.834 blocker/min** и **5.44/$**; это по одному наблюдению и не переносится на
population. Primary precommitted yield у обеих — ноль. [M5][M6]

**Confidence:** cost/wall **CONFIRMED**; marker yield **LIKELY как процессный
proxy**; population zero-value и false-positive rates **UNCERTAIN/не
идентифицируются**.

## 6. Fresh Sol-thread: что он даёт и чего не даёт

Fresh thread действительно разрывает transcript-level dependence: reviewer не
видит рассуждение автора и получает artifact как внешний вход. Это полезнее,
чем попросить автора проверить собственный текущий ответ. Но reviewer Sol и
Sol-author сохраняют checkpoint/training distribution, поэтому общие
parametric blind spots остаются возможными. Старый отчёт формулировал это как
«убирает contextual half, не parametric half»; новая пара даёт локальный
counterexample, но не измеряет доли этих двух механизмов. [M3][M5]

Сопоставление с **Opus-authored** аудитом [M3] важно: тот независимый автор
нашёл равенство по видимому review signal (`p=0.54`), но сам предупредил, что
finding count не видит пропуски. Нынешний frozen-ground-truth A/B не
противоречит его числам — Luna и Sol снова дали одинаковый видимый output — и
одновременно заполняет именно эту дыру: одинаковый output скрыл два общих
required misses. Новый результат не отменяет Opus-аудит, а сужает его
интерпретацию: отсутствие разницы в количестве замечаний нельзя превращать в
доказательство safety same-model review.

Наблюдаемые стороны:

- **Польза есть.** В #194 review research prose привело к 7 принятым
  содержательным изменениям из 8; в #230 Sol review поймало 11 lifecycle
  blockers за три раунда. [M7][M10]
- **Независимости нет.** В K2 обе модели увидели опасный порядок и предложили
  admission до `create_session`, но классифицировали это suggestion/PASS; hidden
  blocker был именно частичный success: session создан, initial task отвергнут.
  Этот механизм соответствует реальному #227 post-review escape после трёх Sol
  rounds. [M5][M6][M8]
- **В Q4 обе нашли настоящую потерю сообщения после трёх failures, но обе не
  назвали lock starvation.** Исторический Sol review ранее задал этот вопрос и
  затем одобрил решение держать per-chat lock через retry/backoff; это один из
  прежних n=2 Sol→Sol escapes. [M3][M5][M9]
- **Correlation ≠ causation.** Одинаковый miss двух same-family checkpoints на
  двух отобранных исторических механизмах поддерживает риск common blind spot,
  но не доказывает, что причиной был author model или что Opus обязательно
  поймал бы оба.

Вердикт: свежий Sol-thread остаётся полезным second opinion для обычной работы,
но не должен быть единственным независимым барьером на Sol-authored
shared-runtime/security.

## 7. Luna против Sol

### Результат минимального blind A/B

| Arm после unblind | Required hits | Clean blocking FP | Verdict vector | wall | API-eq $ |
|---|---:|---:|---|---:|---:|
| Luna | 0/2 | 0/2 | PASS/PASS/BLOCK/PASS | 92.27 с | 0.00650 |
| Sol | 0/2 | 0/2 | PASS/PASS/BLOCK/PASS | 71.97 с | 0.18384 |

По предзарегистрированному falsifier **Luna явно не хуже не опровергнуто**:
Sol-only hit и Luna-only FP отсутствуют. Но это не доказательство equivalence;
обе arms провалили оба primary blockers. Luna дешевле по API-equivalent в 28.3×,
но обе используют один Codex quota bucket. Нулевой integer delta 12→12 не
позволяет оценить фактический subscription quota ratio, особенно при двух
foreign Sol turns на `$8.5754` между snapshots. [M5]

**Вывод:**

- для low/medium-risk, компактного diff и сильного oracle Luna — разумный
  default first reviewer;
- при blocker, слабом oracle, большом diff или неясности — один Sol escalation;
- для shared-runtime/security Luna-only недопустима; Sol обязателен минимум, а
  для Sol-authored high-risk нужен cross-family targeted review;
- один Luna прогон оказался медленнее Sol, поэтому экономию wall не заявляем.

## 8. Decision table

`blocking` здесь только crash/corruption/security/shared-runtime availability;
suggestion должен давать реальную пользу; nit пропускается.

| Фаза / риск | Diff и oracle | Author / quota | No review | Luna | Sol | Opus cross-pool | Решение |
|---|---|---|---|---|---|---|---|
| Research prose, низкие последствия | Источники и reproduction checks сильные | Любой; Codex здоров | допустим только для короткой факт-выписки | **default completeness pass**, 1 раунд | escalation при causal/statistical споре | не нужен | Механические проверки главнее finding count |
| Research/architecture, вывод меняет shared runtime/security | Oracle слабый или открытый | Sol author | нет | недостаточно | targeted technical review | **обязательный независимый pass**, если доступен | Разорвать same-family loop на самом рискованном выводе |
| Plan, closed leaf | Красный behavioural oracle, малый scope | Любой; Codex здоров | допустим для тривиального leaf | **default** | escalation при blocker/неясности | нет | Один pass; nit не исправлять |
| Plan shared-runtime/security | Любой размер; межкомпонентные контракты | Opus author | нет | не как gate | **обязателен** | при слабом oracle/высоком ущербе | Размер diff не отменяет review |
| Plan shared-runtime/security | То же | Sol/Luna author | нет | не как gate | обязательный technical pass | **targeted cross-family gate** | Fresh Sol не считать независимым |
| Impl: trivial closed leaf | Один function, сильный existing oracle, не shared runtime | Любой | **default** | опционально | нет | нет | Review overhead не окупается; тест и diff check достаточны |
| Impl: обычный compact diff | Сильные tests/mutations, низкий/средний риск | Opus или Sol author | нет | **default** | один escalation | нет | B: Luna default + Sol escalation |
| Impl: большой diff или слабый oracle | Несколько consumers/state transitions | Opus author | нет | недостаточно | **default** | при security/irreversible data risk | Sol лучше расходовать на техническую глубину |
| Impl: shared runtime/security | Любой размер | Sol/Luna author | нет | недостаточно | **обязательный минимум** | **добавить targeted pass** на load-bearing seams | C поверх B; один reviewer не oracle |
| Codex ≥90% или telemetry stale/nondecomposable | Любой | Codex reserve защищается | trivial leaf — skip | только closed leaf с готовым red oracle | не начинать | high-risk → **Opus** | Availability важнее формального review coverage |

### Повторные раунды и stop rule

- **Один раунд по умолчанию.** Второй — только если artifact изменился после
  blocker либо есть проверяемое несогласие по blocker.
- Новая suggestion сама по себе не открывает ещё раунд; повтор «до чистоты»
  превращает reviewer в генератор scope.
- Безусловный потолок: prose — 2 раунда, executable artifact — 3; последний
  unresolved blocker передаётся наверх, а не замалчивается.
- Повторный review того же unchanged diff не добавляет независимости. Для
  high-risk лучше сменить family и сузить вопрос до load-bearing seam.

## 9. Сравнение вариантов A–D

| Вариант | Качество | Wall/cost | Quota/availability | Вердикт |
|---|---|---|---|---|
| A. Оставить Sol reviewer везде | Исторически полезен; same-checkpoint blind spots остаются | median 79 с; `$0.639`/turn в текущем Sol cohort | Один Codex bucket; review ≈8.76% API-eq cost share | **Неэффективен как universal default**, оставить для сложной technical escalation |
| B. Luna default + Sol escalation | В A/B не хуже по observed score; population equivalence не доказана | В compact A/B 28.3× дешевле; wall не быстрее | Тот же bucket, но существенно меньше API-eq расход на first pass | **Да для low/medium-risk с сильным oracle** |
| C. Cross-family only high-risk | Лучше разрывает Sol-author/reviewer loop; прямого Opus arm в этом A/B нет | Дороже Claude quota; применять точечно | Не зависит от доступности Codex bucket | **Да для shared-runtime/security; часть рекомендуемого гибрида** |
| D. Убрать review | Не ловит известные blockers и causal errors | Экономит весь review wall/cost | Максимальная availability | **Только trivial closed leaf; в целом reject** |

Итоговая политика — не один вариант, а **B+C**: Luna default на проверяемой
обычной работе, Sol escalation; shared-runtime/security — Sol минимум и
cross-family для Sol-authored/weak-oracle high-risk. A остаётся fallback, а D —
узкое исключение для тривиальных leaf changes.

## 10. Counter-evidence, ограничения и риски

- A/B намеренно мал: 2 defects + 2 clean controls. Он способен быстро
  опровергнуть «Luna явно не хуже», но не подтвердить non-inferiority.
- Корпус выбран из известных post-merge mechanisms; это хороший stress test,
  но не prevalence sample обычных diffs.
- Q4 показывает, почему count findings недостаточен: обе модели нашли реальный
  blocker, но не тот causal mechanism, против которого проверялась
  независимость.
- Author-model latency таблица confounded задачами: Luna-authored reviews `n=7`
  completed и p90 416.8 с не означают, что Luna-author причинно замедляет Sol.
- 45/235 live invocations не спарены из-за retention/template gaps; filesystem
  census видит только сохранённые worktrees.
- Task cycle `created→completed` включает ожидание человека и параллельную
  работу; доля review wall — верхняя граница, не controlled intervention.
- API-equivalent `$` виртуальны для subscription; cost share — полезный единый
  счётчик, но не фактический счёт и не точная quota consumption.
- Два foreign turns делают quota attribution A/B unresolved по prereg, хотя
  observed integer delta не превысил gate.
- Opus cross-family arm в этом обновлении не запускался. Рекомендация для
  high-risk основана на разрыве известной same-family зависимости и
  асимметрии ущерба, а не на измеренном Luna/Sol/Opus tournament.
- Обычный финальный Sol `codex_review` отчёта не запускался: это конфликт
  интересов для исследования самого Sol reviewer. Дополнительный Luna review
  также не запускался после A/B: prereg запретил добивать turns при foreign/
  nondecomposable telemetry. Вместо него выполнены hash/commitment, parser,
  DB-integrity и повторные aggregate reproduction checks.

## 11. Затронутые файлы и edge cases для возможной следующей фазы

Phase 1 не меняет runtime или review routing. Если будет одобрен план, он должен
учесть владельцев правил в pipeline prompts, current Codex reserve policy,
mandatory review shared runtime и невозможность считать Luna независимым
cross-family reviewer. Нельзя автоматически эскалировать каждый Luna suggestion
в Sol: это вернёт двойной wall/cost без прироста safety. Эскалация должна
срабатывать только на blocker, слабый oracle, высокий риск или реальное
несогласие.

## 12. Reproduction

Исторические агрегаты воспроизводятся на свежей WAL-safe копии, с тем же cutoff:

```bash
python3 docs/tasks/289/snapshot_ab.py \
  --source /home/kesha/orchestra/data/orchestra.db \
  --backup docs/tasks/289/.repro.db \
  --summary-out docs/tasks/289/.repro-summary.json
python3 docs/tasks/289/analyze_review_roi.py \
  --db docs/tasks/289/.repro.db \
  --baseline docs/tasks/codex-review-value \
  --repo-root . \
  --out docs/tasks/289/evidence-reproduced.json \
  --cutoff 2026-08-16T10:07:30.748436+00:00
```

После проверки `.repro.db*` и summary должны быть удалены: raw DB не является
артефактом задачи. В этом research run повтор на более новом backup дал
byte-equivalent `baseline_2026_07_25`, `live_db_retained_window` и cutoff-filtered
artifact census; отдельно исправлен leakage завершённых после cutoff tasks.

Слепая оценка A/B воспроизводится без model calls:

```bash
python3 docs/tasks/289/grade_ab.py \
  --corpus docs/tasks/289/ab_workspace/frozen_corpus.md \
  --prompt docs/tasks/289/ab_workspace/review_prompt.txt \
  --ground-truth docs/tasks/289/ground-truth.json \
  --luna-review docs/tasks/289/luna-review.md \
  --sol-review docs/tasks/289/sol-review.md \
  --run-metadata docs/tasks/289/ab-run-metadata.json \
  --out docs/tasks/289/ab-grade.json
```

Raw JSONL нужен только для первичного `sanitize_ab_run.py`; после фиксации
usage/timing/hash aggregates он удалён и не коммитится. Повтор A/B запрещён
предрегистрацией, поэтому исходный usage подтверждается сохранёнными hashes и
sanitized metadata, а не регенерируется новой парой.

## Источники

- **[M1] Direct measurement, tier 1:** [`evidence.json`](evidence.json) — все
  sanitized исторические и A/B агрегаты.
- **[M2] Reproduction, tier 1:** [`analyze_review_roi.py`](analyze_review_roi.py),
  [`snapshot_ab.py`](snapshot_ab.py), [`sanitize_ab_run.py`](sanitize_ab_run.py),
  [`grade_ab.py`](grade_ab.py).
- **[M3] Prior local measurement, tier 1/retrospective:**
  [`../codex-review-value/research.md`](../codex-review-value/research.md),
  `reviews-graded.tsv`, `blind-grades-raw.tsv`, `codex-review-calls.tsv`.
- **[M4] Frozen experiment contract, tier 1:** [`prereg.md`](prereg.md),
  [`ab_workspace/frozen_corpus.md`](ab_workspace/frozen_corpus.md),
  [`ab_workspace/review_prompt.txt`](ab_workspace/review_prompt.txt), freeze
  commit `0138b371`.
- **[M5] Blind grade, tier 1:** [`ab-grade.json`](ab-grade.json),
  [`ab-run-metadata.json`](ab-run-metadata.json),
  [`ground-truth.json`](ground-truth.json).
- **[M6] Model outputs, primary artifacts:** [`luna-review.md`](luna-review.md),
  [`sol-review.md`](sol-review.md).
- **[M7] Prior local review follow-through:** [`../194/research.md`](../194/research.md),
  section «Круги ревью».
- **[M8] Historical K2 escape:** [`../227/report.md`](../227/report.md),
  lines describing the independent post-review `get_worker_admission` blocker.
- **[M9] Historical Q4 escape:**
  [`../tg-message-delivery/codex-review-plan.md`](../tg-message-delivery/codex-review-plan.md),
  [`../tg-message-delivery/codex-review-impl.md`](../tg-message-delivery/codex-review-impl.md).
- **[M10] Sol review absolute utility:** [`../230/report.md`](../230/report.md),
  [`../230/codex-review-impl.md`](../230/codex-review-impl.md).
