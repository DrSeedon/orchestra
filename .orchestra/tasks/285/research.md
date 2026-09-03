# #285 — подписочные лимиты Claude, Codex/ChatGPT и Grok

## Вопрос

- **Контекст:** локальный ноутбучный контур Orchestra и доступные ему подписочные CLI Claude, Codex/ChatGPT и Grok; VPS используется только как read-only источник доказательств о сбоях, без изменений prod/config.
- **Изменение под проверкой:** заменить статический порог остановки адаптивным контроллером, который стремится закончить каждое независимое окно около 99% непосредственно перед reset, сохраняя около 1% safety margin и отдельный резерв под критичную работу.
- **Baseline:** ручная маршрутизация и статические пороги (в частности stop-at-95%), не учитывающие оставшееся время, текущий темп, неопределённость, drift плана и независимость пулов.
- **Измеримый исход:** по WAL-safe истории и живым read-only endpoint'ам восстановить окна, reset transitions, интервалы ≥80/90/95/100%, непрерывные блокировки, turns/tokens/cache/API-equivalent cost и наблюдаемую ёмкость; затем проверить на историческом replay, уменьшает ли прогноз раннее исчерпание и недожог при safety margin 1%.

## Гипотезы и фальсификаторы

1. **H1:** подписочные окна расходуются как несколько независимых bucket'ов (Claude 5h/7d/scoped, Codex primary/Spark, Grok), поэтому единый процент или единый stop-threshold неверен.
   - Фальсификатор: синхронные reset/utilization transitions и официальная документация, прямо подтверждающая общий пул для соответствующих bucket'ов.
2. **H2:** наблюдаемая ёмкость и reset-поведение непостоянны (план/offer drift, неполный retention, дискретные snapshots), поэтому оценка runway требует rolling rate, интервал неопределённости и детектор смены режима.
   - Фальсификатор: несколько полных окон с устойчивой ёмкостью/темпом, точными reset timestamps и без смены схемы/плана.
3. **H3:** Grok «почти выжжен» локально, а сбой VPS quota-fetch отражает login/token fault; inference reachability и datacenter-IP остаются отдельными вопросами.
   - Фальсификатор: локальные свежие quota snapshots показывают большой остаток либо VPS ошибки содержат однозначный quota-exhausted сигнал при валидном login.
4. **H4:** адаптивный контроллер с целевой траекторией к 99% и fail-safe при низкой уверенности лучше статического stop-at-95% использует подписку без раннего hard-block.
   - Фальсификатор: historical replay на полных окнах показывает больше/дольше ранних блокировок либо не меньший недожог при сопоставимом резерве.

## Метод и границы данных

Каждый вывод ниже привязан к первичному источнику или воспроизводимому измерению; отсутствие telemetry не трактуется как нулевое использование.

### Контуры и время

| контур | что реально найдено | timezone | статус |
|---|---|---|---|
| `vmi3407579` | `/home/kesha/orchestra/data/orchestra.db`, live `GET http://127.0.0.1:8888/api/usage` | БД хранит UTC; ОС `Europe/Berlin` (CEST, UTC+02 на дату съёма) | WAL-safe backup `sqlite3.Connection.backup`, `quick_check=ok` |
| ноутбук `maxim-911aird` | заданного пути `/home/kesha/orchestra/data/orchestra.db` нет; фактический checkout — `/mnt/data/Projects/Python/orchestra`, БД — `data/orchestra.db` | ОС `Asia/Krasnoyarsk` (UTC+07) | remote backup `Connection.backup`, SHA-256 `91427d…7fc`, `quick_check=ok`; DB-only evidence доставлен и JSON-validated, без чтения `.env`/live auth |

Основной полный ряд и журнал ошибок ниже относятся к **локальному VPS checkout**; ноутбучные факты помечены отдельно и не складываются с VPS. Это не косметическая оговорка: retention и Grok отличаются по контурам. Источник `M1` содержит VPS-пары строк, `M6` — ноутбучный DB-only slice; секреты и платёжные реквизиты в них не попали.

### Retention, cadence и качество

- `usage_snapshots`: 10 219 строк, `2026-07-05T05:19:58.635440Z` — `2026-08-16T08:45:35.224799Z`. `turn_usage`: 3 451 строк, `2026-08-03T06:33:39.118015Z` — `2026-08-16T08:45:22.873498Z`. `provider_usage` появился только в части retention: Anthropic — 3 747 строк, Codex — 3 740, Spark — 3 721, Grok — 853. [M1]
- Ноутбук содержит 10 818 `usage_snapshots` (`2026-05-30`—`2026-08-16T08:57:55Z`) и 3 605 `turn_usage` (`2026-07-26`—`2026-08-16T08:54:24Z`); median cadence 302.029 с, p95 311.620 с, 129 gaps >900 с. Его 16 test rows исключены тем же production predicate. [M6]
- Median cadence — 300.674 с, p95 — 302.847 с, максимум — 33 052.357 с; 54 разрыва больше 900 с. Поэтому начало/конец threshold и reset приводятся как **интервал между соседними samples**, а длительности — по left-endpoint step-function `[ts_i, ts_(i+1))`, без переноса через gap >900 с и без экстраполяции за последний sample. Это наблюдаемое время, не точное время события. [M1]
- После исправления collector 07.08 недоступный Anthropic источник хранится как `status=unavailable`; 535 таких строк не превращаются в ноль. В старой части retention остаются 106 строк `provider_usage='{}'` с `5h=0, 7d=0`, где настоящий reset неотличим от старого collector failure; они исключены из выводов как unknown. [M1][M2]
- Все 26 885 нормализованных quota observations и 9 684 legacy percentages — целочисленные. Реальная доля внутри одного процентного пункта непублична; из `99`/`100` нельзя восстановить десятые доли. Live endpoint не отдаёт `observed_at`, а локальный cache TTL равен 300 с; median age quota sample у завершённого Claude turn — 150.19 с, p95 — 282.07 с. [M1]

## Findings

### 1. Карта пулов: что связано, а что отдельно

| bucket | официальная связь | наблюдаемый контракт Orchestra | вывод для routing |
|---|---|---|---|
| Claude 5h | одно session-окно на активность Claude web/desktop/mobile/Code; reset через 5 часов | отдельный `five_hour`, reset anchor зависит от начала использования | hard gate по максимуму ограничений 5h и 7d |
| Claude weekly all | общий недельный лимит по моделям, фиксированное account reset time | `seven_day`, текущий reset `2026-08-18T06:59:59Z` | главный дефицитный Claude bucket |
| Claude Fable scoped | **не независимая добавочная ёмкость**: Fable тратит общий weekly и одновременно имеет scoped cap до 50% weekly | live `weekly_all=100`, scoped Fable `0`; scoped history не сохранялась | доступная Fable ёмкость = `min(all_remaining, fable_scoped_remaining)`; при all=100 она равна нулю |
| Codex main | общий ChatGPT agentic pool для Codex и ChatGPT Work/Excel/Workspace Agents; локальные/cloud turns делят лимит | один `codex.primary`, plan `pro`; Sol/Terra/Luna — разные модели внутри него | Luna растягивает тот же pool; Sol — quality/workhorse, не отдельный кошелёк |
| Codex Fast | service tier для поддерживаемой модели, не модель и не bucket: GPT-5.6/5.5 заявлены 1.5× быстрее за 2.5× ChatGPT credits, GPT-5.4 — за 2× | отдельного utilization counter нет | только latency-critical: при тех же tokens burn-rate pool примерно ×2.5; не включать автоматически |
| Codex Spark | отдельная менее способная model preview с собственным demand-adjusted usage limit | `codex_spark.primary`, максимум истории 9%; цена `None` | overflow только для полностью закрытых oracle-backed leaf tasks; не считать бесплатным |
| Grok paid weekly | один weekly allowance SuperGrok между Chat/Imagine/Voice/Build; free Chat/Voice limits отдельно после exhaustion | один нормализованный `grok.primary`, когда login работает | резервировать под X/web/opinion; продуктовые проценты — breakdown общего, не независимые wallets |

**Вердикт H1: частично REFUTED.** Независимы Claude 5h против weekly, Codex main против Spark и provider pools между собой. Но Fable — scoped sub-limit внутри Claude weekly, Fast — multiplier внутри Codex main, а продукты paid Grok делят общий weekly. [O1][O3][O5][O6][O8]

### 2. Время у порогов и непрерывные блокировки

Все числа — наблюдаемые step-duration на доступных samples, не wall-clock downtime сервиса. `100%` означает показание целочисленного счётчика; два успешных Opus turn ниже доказывают, что оно не тождественно немедленному hard denial.

| provider/window | ≥80% | ≥90% | ≥95% | =100% | longest observed 100%-block |
|---|---:|---:|---:|---:|---:|
| Claude 5h | 54.333 h / 34 blocks | 40.209 h / 30 | 34.947 h / 27 | 28.830 h / 26 | 3.004 h |
| Claude 7d | 169.447 h / 20 | 126.726 h / 13 | 117.964 h / 13 | 52.957 h / 8 | 7.972 h lower bound; несколько интервалов обрываются gap |
| Codex primary | 219.681 h / 5 | 202.575 h / 4 | 188.639 h / 3 | 118.889 h / 1 | 118.889 h |
| Spark | никогда не достигал 80%; observed max 9% | — | — | — | — |
| Grok VPS | available history не достигала 80%; observed max 79% | — | — | — | — |
| Grok laptop | 8.039 h / 5 intervals | 6.879 h / 5 | 6.456 h / 5 | 0 | 0 |

Сумма времени у threshold не равна времени полной недоступности. Для quota exhaustion нужны provider error/отказ либо отсутствие успешных turns; один percentage flag недостаточен. [M1][M6]

### 3. Reset/drop transitions и смена Codex `prolite → pro`

- Последний `prolite` sample: id 10199, `2026-08-16T07:10:39.764982Z`, Codex main `97%`, Spark `9%`. Первый `pro`: id 10200, `07:15:41.615352Z`, main `24%`, Spark `9%`, оба со старыми reset anchors. Отношение целых percentages `97/24 = 4.042`; это **наблюдаемый rescale**, не точное доказательство размера плана. [M1]
- Следующий sample id 10201, `07:20:43.838690Z`: main `0%`, Spark `0%`, anchors перескочили на `2026-08-23T07:20:43Z`; ещё через samples main начал расходоваться, а нулевой Spark продолжил сдвигать displayed reset к `now+7d`. Поэтому этот drop классифицирован как plan migration/rebase, а не естественный reset старого окна. [M1]
- До upgrade Codex main показал: `100→0` около scheduled reset 08.08; затем неожиданные `26→0` (anchor +13.916 h), `87→0` (+40.739 h), `92→0` (+51.141 h). Это несовместимо с наивной моделью одного неизменного fixed-week bucket. Публичная документация говорит лишь о shared 5h и возможных дополнительных weekly limits, но точный алгоритм внутренних rolling/refill counters непубличен. [M1][O5]
- Falsifier H2 сработал против стабильности: план сменился внутри retention, anchors дрейфуют, новый `pro` имеет меньше двух часов истории в frozen slice. Старый `prolite` нельзя масштабировать в runway нового плана без нового calibration window.

### 4. Fable при `All models=100%, Fable=0%`: что реально выполнялось

- Live endpoint подтвердил `weekly_all=100` active/critical и `weekly_scoped Fable=0` inactive; current session 0. Исторический collector **не сохранял** scoped Fable, поэтому временного ряда Fable нет и его отсутствие не выдается за нулевое потребление. [M1]
- За `2026-08-15 UTC` в `turn_usage` завершены 4 Claude turns, все `claude-opus-5[1m]`, Fable — 0. После первого наблюдаемого перехода weekly `99→100` между `09:56:49.600877Z` и `10:01:51.939888Z` были ещё 2 успешных Opus turns: `11:03:06Z` и `11:12:13Z`, суммарно input 147, output 9 498, cache-read 3 074 752, cache-create 389 090, виртуальный API-эквивалент `$5.666461`. Их user starts были больше чем через час после first-100, поэтому версия «старый in-flight turn закончил работу» опровергнута. [M1]
- Автоматического Fable fallback нет: фактическая модель в `turn_usage.model`, а не текущее `sessions.model`, осталась Opus. Версия «списались usage credits» также опровергнута: live `extra_usage.is_enabled=false`, `used_credits=0`, spend disabled; dashboard пользователя показал `$0 spent`, balance `$1.87`, auto-reload off. Баланс при выключенных credits инертен. [M1][O2]
- Совместимые объяснения — integer rounding, delayed/admission-time accounting или иной непубличный allowance: `100` могло означать верхний округлённый band при остатке либо enforcement мог опираться на другое состояние. Staleness до 300 с существует, но не объясняет час полностью; exact enforcement/rounding Anthropic не публикует. Поэтому причина **UNCERTAIN**, anomaly сохранена, а не «объяснена» догадкой.
- Fable в контроллере — не overflow после all=100. Каждый Fable turn уменьшает общий weekly headroom и scoped Fable headroom; использовать его можно только пока оба положительны и качество задачи подходит. [O1]

### 5. Turns, tokens, cache и деньги

Frozen production predicate: `NOT (scope='/test' OR session_id LIKE 'test-%')`; в этом slice он исключил 0 строк, duplicate `event_id` — 0. [M1]

| runtime/model | turns (ok) | input | output | cache read | cache create | `$ turn` API-equivalent |
|---|---:|---:|---:|---:|---:|---:|
| Claude Opus 5 `[1m]` | 2 576 (2 503) | 4 271 951 | 21 772 302 | 7 226 900 634 | 151 459 356 | $4 863.481233 |
| Claude Haiku 4.5 | 2 (2) | 27 | 658 | 82 572 | 72 572 | $0.157423 |
| Codex Sol | 807 (797) | 2 195 596 686 | 7 695 554 | 2 128 180 736 | 0 | $1 632.036738 |
| Codex Luna | 61 (58) | 117 346 305 | 569 451 | 110 132 736 | 0 | $4.527579 |
| Codex Terra | 1 (1) | 1 012 208 | 5 311 | 951 552 | 0 | $0.375354 |
| Spark | 4 (4) | 22 448 134 | 174 876 | 21 747 712 | 0 | **unknown**: 4 unaccounted rows, local `None` |

`$ turn` — только виртуальный API-эквивалент локального rate card, не списание с карты и не subscription invoice. Для Codex официальный ChatGPT rate card выражен в credits; локальная долларовая шкала — аналитическая нормализация. Spark price в research preview официально non-final, поэтому `$0` в сырой SQL-сумме означает `unaccounted`, а не бесплатный turn. Реальные известные recurring цены плана приводятся отдельно из official pricing, но не выводятся из tokens. [M1][O3][O6]

### Что здесь означает «наблюдаемая ёмкость Orchestra»

- Абсолютный размер current Claude/Codex/Grok subscription buckets в tokens или turns провайдеры не публикуют, а percentage counters целочисленные. Поэтому честная ёмкость — **фактически завершённая работа плюс траектория provider counter**, не пересчёт процентов в выдуманные tokens. [M1][O12]
- За retention `turn_usage` Orchestra реально завершила 2 505 из 2 578 Claude turns и 856 из 869 Codex-family turns с известным token breakdown; таблица выше даёт их tokens/cache/API-equivalent. Это throughput нескольких окон и смены плана, не capacity одного окна. Spark имеет 4 успешных turns, но числовой allowance и цена остаются unknown. [M1]
- Grok доказал минимум 36 завершённых real turns в журнале; последние 20 дали `$98.86` виртуального API-эквивалента. Их token breakdown отсутствует из-за instrumentation gap. Laptop provider counter дошёл до 98%, что является лучшим прямым измерением текущего исчерпания, но не раскрывает абсолютный weekly allowance. [M5][M6]
- Реальный платёж владельца по token rows не вычисляется. В измеренном live state Claude usage credits выключены и `$0 spent`; published plan prices — offer, а не доказательство конкретного invoice. Поэтому artifact не публикует balance или платёжные реквизиты. [M1][O2][O3]

## Контроллер «99% к сбросу»

Это **предлагаемая policy**, а не измеренный факт. Она заменяет статичный stop-at-95 динамической задачей слежения. Единица управления — `(provider, bucket, plan/regime)`, а не provider целиком.

### Входы и вычисления

Для bucket `b` на каждом свежем sample:

1. `u_b` — reported utilization; `T_b` — reset time; `h_b` — часы до reset. Нулевой/отсутствующий anchor (Claude 5h до активности, Spark при 0%) не выдумывается.
2. `g_b = max(0.5 pp, q95_pp(one eligible turn), drift_guard)` — measurement guard. `0.5` следует только из целочисленного отображения; если single-turn q95 больше, обещать final 1% невозможно и нужен Luna/smaller turn.
3. `R_b(t)` — ещё не выпущенный reserve под критичные turns: q95 суммы заявленных critical jobs до reset. Reserve постепенно выпускается в последние `max(2h, q95 critical lead time)`; это не вечные статичные 5%.
4. `H_b = 99 - u_b - g_b - R_b(t)` — доступный non-critical headroom. `r*_b=max(0,H_b/h_b)` — допустимый средний расход до target.
5. `D_b(τ)` — moving-block bootstrap оставшегося спроса из hourly increments **того же plan/regime**, плюс очередь запланированных работ по empirical pp/turn. Block length выбирается по decay/первому устойчивому zero-crossing autocorrelation; `3h` — только начальная sensitivity-точка до такой оценки, не утверждение независимости. Отдельно считаются p50/p90/p95 и `P(hit 100 before T_b-guard_time)`.
6. Для Claude dispatch разрешён только если одновременно проходят 5h и weekly; для Fable добавляется scoped constraint. Для Fast expected pp/turn умножается на официальный credit multiplier 2.5 для GPT-5.6/5.5 (2.0 для GPT-5.4), пока paired live measurement не дал свой коэффициент. Spark и Grok не наследуют темп Codex/Claude.

### Зоны действия

| зона | measurable predicate | действие |
|---|---|---|
| **ACCELERATE** | p90 projected end `<97%` и telemetry fresh | добавить eligible non-critical, Sol как workhorse на сложном, Luna максимально на closed/high-volume; Spark — только closed+oracle; Fast запрещён без latency deadline |
| **TRACK** | p50 end `97–99%`, p90 `≤99.5%`, early-exhaust risk `<10%` | обычный Luna-first routing, Sol по сложности; каждые 5 минут переоценка |
| **THROTTLE** | p50 end `>99%` или early-exhaust risk `≥10%` | убрать opportunistic work, Luna для малых закрытых turns, spillover на другие provider buckets, Fast off |
| **RESERVE** | p90 пересекает 100 до critical horizon, `H_b≤0`, либо bucket reported 100 | только заранее отмеченные critical jobs, если `u+q95_turn+g≤99-R(t)`; остальное перелить/поставить в очередь до reset |
| **FAIL-SAFE** | sample age `>10 min`, reset/plan changed, anchor прыгает, counter падает вне scheduled reset, либо меньше calibration history | не пытаться «дожечь до 99» вслепую; Luna-only для обязательного, Fast off, сохранить reserve, требовать 3 стабильных samples перед rebaseline |

Hard-stop применяется не на `95`, а перед конкретным dispatch: `u_b + q95_pp(turn_class, model, mode) + g_b > 99 - R_b(t)`. Эквивалентно, turn проходит только когда `q95_pp≤H_b`; сам target `99` и есть номинальный 1 pp safety margin, а `g_b` защищает от rounding/drift внутри него. При отсутствии pp/turn оценки task не идёт в дефицитный bucket. In-flight не прерывается: остановка следующего dispatch безопаснее и соответствует официальному исключению Codex, что активный turn может завершиться после достижения limit. [O5]

### Replay на живой истории

Текущий Claude weekly reset начался `2026-08-11T07:00Z`. Первое наблюдаемое `95%` — `2026-08-14T11:01:39Z`, то есть за **91.972 h** до reset; первое `100%` — `2026-08-15T10:01:51Z`, за **68.969 h**. Для явно заданного baseline `0%` в начале 168-hour окна elapsed=`168−68.969=99.031 h`, поэтому линейная target-trajectory равна `99×99.031/168=58.36%`. Observed mean burn был `1.010 pp/h`. Это не тонкая настройка около края, а явный early-exhaust regime. [M1]

Контроллер на 95 не остановил бы всё статически: он вошёл бы в THROTTLE/RESERVE, перевёл non-critical на Codex/Spark/Grok, оставил Claude только для q95 critical reserve и выпустил бы остаток ближе к Tue reset. На first-100 `H≤0`, поэтому два поздних Opus turns были бы допущены только как critical и только если q95-fit доказан; Fable `0%` не помог бы, потому что `weekly_all=100%`.

Codex даёт второй fail-safe пример. На `prolite=97%` оставалось **92.771 h** до displayed reset; через 5 минут план стал `pro` и percentage пересчитался в 24, затем в 0 с новым anchor. Любой runway, рассчитанный до transition, должен быть аннулирован. После transition frozen history нового режима слишком коротка для CI.

### Доверие, чувствительность и сколько истории нужно

- **Cold start:** до 1 полного окна — только point forecast и q95 token/credit proxy; статус LOW, без auto-acceleration к 99.
- **Pilot:** 1–2 полных окна одного plan/regime — block-bootstrap показывается, но dispatch использует верхнюю границу; MEDIUM только если coverage ≥80% и нет unexplained drops.
- **Operational:** минимум 3 полных окна, ≥20 non-overlapping blocks после thinning не короче оценённой correlation length и effective sample size ≥20; показывать p50/p90/p95, empirical coverage, выбранный block length и sensitivity при `g±0.5 pp`, demand `±25%`, single-turn q95 `±1 bin`. До оценки autocorrelation `3h` остаётся лишь sensitivity-сценарием.
- **Drift:** любое изменение `plan_type`, window duration, reset anchor >1 cadence вне scheduled reset, либо два подряд forecast residual вне 80% interval → новый regime; абсолютные pp/window старой истории запрещены. Task-class token distributions можно переносить, если model/rate card не менялись.
- **Целые проценты:** 1% safety — цель, не гарантия. Если `q95 turn + 0.5pp > 1pp`, финальный target автоматически понижается до `100-(q95+0.5)` или выбирается Luna/короткий turn.

С текущим retention уверенность: Claude weekly — MEDIUM для обнаружения gross overburn, но LOW для точного 99 из-за gaps/целых процентов/аномальных drops; Claude 5h — MEDIUM; Codex `prolite` — MEDIUM исторически, текущий `pro` — LOW после structural break; Spark — LOW (max 9%, reset при нуле плавает); Grok VPS — LOW после обрыва login telemetry.

## Routing и reserve policy для непрерывной Orchestra

1. **Luna first, Sol workhorse по сложности.** Закрытая задача с названными файлами, AC и механическим oracle → Luna. Исследование, архитектура, спорное решение, exact multi-tool protocol, где Luna ожидаемо не справится → Sol. Экономия Luna превращается в параллельность и runway того же Codex main pool.
2. **Fast — режим дедлайна, не default.** Включать только если latency SLA ценнее 2.5× burn и forecast остаётся TRACK после multiplier; выключать в THROTTLE/RESERVE/FAIL-SAFE. Fast GPT-5.6/5.5 официально обещает 1.5× speed, поэтому при одинаковой работе efficiency в credits per wall-time хуже примерно `2.5/1.5=1.67×`; это аналитическое следствие official multipliers, не paired live result. [O7]
3. **Spark — отдельный overflow, но с узкой дверью.** Text-only, полностью заданные решения/значения, ≤100K initial context, существующий immutable oracle. После одного incomplete/fail — Luna/Sol, без Spark retry. Numeric price/reset public unknown → не оптимизировать по `$0` и не форсировать burn к 99 при плавающем anchor.
4. **Claude:** Opus только special complex; Fable лишь когда качество оправдывает и оба weekly constraints имеют headroom. При Claude weekly THROTTLE non-critical уходит в Codex main/Spark/Grok; credits выключены, значит paid overflow отсутствует.
5. **Grok:** первичная ниша — X/Twitter search, current web search и opinion-diversity; не общий coding overflow. Локальный quota state, OAuth health и VPS reachability — три разные gates. `token_expired`/datacenter-IP denial никогда не уменьшает quota forecast; quota exhaustion требует собственного provider signal.
6. **Critical reserve:** task до spawn помечается critical/non-critical. Reserve — q95 remaining critical demand по bucket, не фиксированные 5%. В последние guard-hours невостребованный reserve выпускается малыми Luna turns, чтобы приблизиться к 99; final 1% остаётся measurement/surprise margin.
7. **Spill order при binding main Codex:** Luna для обязательных закрытых → Spark для допустимых closed+oracle → Grok только по его нише → Opus для special complex при Claude headroom. Sol opportunistic выключается раньше Luna; идущий turn не переключается на лету.

## Spark ↔ Luna: эмпирическая граница

Предыдущий #222 установил safety boundary: на missing-data tasks Spark выдумал недостающие значения 2/2, Luna остановилась и спросила 2/2; при ~164K initial context Spark loud-failed 2/2. Spark дал отдельный quota counter, но официальная цена preview не опубликована. [M3]

Preregistered #286 (`89d00a00`) на двух fresh one-file fully closed frozen-oracle tasks дал 2/2 PASS обеим моделям, byte-identical production diffs и 0 tool failures. Spark: 80.304 s против Luna 112.138 s (−28.4% wall), input 268 254 против 331 349 (−19%), output 5 137 против 3 422 (+50.1%); cold start у Spark в среднем хуже на 17.6%. Luna API-equivalent `$0.017845`; Spark actual price unknown, а «Luna-priced sensitivity» не является ценой Spark. Финальные artifacts `docs/tasks/286/{research.md,data.json,report.md}` — commit `43a138a8`, Codex approved без blockers. Вывод не расширяет routing за closed+oracle boundary; isolation parent-root была configured, но не independently probed inside process. [M4]

## Grok: quota, login и фактическая работа

### Что измерено

- Старый ноутбучный retention 27–28.07 показывает weekly 2→12%, затем 10%, и отдельный старый monthly counter `474/20000 modelCalls`. Это исторические provider signals, не текущая ёмкость и не основание объединять monthly/weekly units. [M5]
- VPS normalized telemetry работала 13–14.08: 215 available samples, все `window_minutes=10080`, reset `2026-08-16T19:51:48.358179Z`. Utilization выросла 8→14%, после login recovery — 14→79% между `09:25` и `11:21 UTC` 14.08; последняя доступная серия держала 79% до `15:23:53Z`. Затем 496 consecutive snapshots до cutoff дали `PermissionError: token_expired`; вместе по retention — 640 token-expired и 29 missing-key rows. [M5]
- Ноутбучный WAL-safe slice закрывает эту дыру: последний snapshot `2026-08-16T08:57:55.844593Z` показывает Grok **98%**, reset `19:51:48.358179Z`. Наблюдаемое время laptop ≥80/90/95 — 8.039/6.879/6.456 h; 100% не наблюдался. Слова «почти выжег» **CONFIRMED** прямым provider snapshot: до target 99 оставался 1 pp, до displayed reset — 10.898 h. [M6]
- В bounded journal 13.08—cutoff: explicit Grok quota/rate-exhaustion markers — 0; raw backend terminal-error marker — 0; `token_expired` usage errors — 767; missing OAuth credentials — 191; billing 401 — 189. Три строки HTTP 429 исключены: они относились к `bench-grok` с backend Codex, а не Grok. [M5]
- В `logs` шесть Grok-backend sessions дали 36 `turn ended`; последние 20 non-probe real turns 14.08 все завершились `end_turn` на `grok-4.5`, с quota suffix 31→78%. Последний real turn: `grok-200`, user `11:12:08Z`, end `11:19:26Z`, turn API-equivalent `$3.51`, reported Grok 7d 78%. Сумма API-equivalent последних 20 turns — `$98.86`; это виртуальная API цена, не списание с подписки. [M5]
- `turn_usage` содержит **0 Grok rows**, а `sessions.total_turns` этих шести sessions также 0. Поэтому input/output/cache tokens для этих 36 реальных turns в Orchestra DB не восстановимы: журнал сохранил turn cost/context/quota, но не token breakdown. Сырые token examples из старых benchmark JSONL нельзя приписывать этим turns. Это telemetry gap, а не нулевые tokens. [M5]

### Login/quota/datacenter-IP — разные диагнозы

| сигнал | что доказано | чего он не доказывает |
|---|---|---|
| `token_expired`, billing 401 | credential/refresh path не дал read-only usage; quota state стал unobserved | quota exhaustion, provider capacity=0 |
| `credentials_missing` | конкретный CLI home не был авторизован | состояние другого local/VPS home |
| `auth.refresh.success` ×7 | managed OAuth с refresh field реально обновлялся 14–16.08 | текущую quota после последнего success |
| успешный `grok models` 13–14.08 | VPS homes могли быть login-valid и исполняли 36 turns | что они работают сейчас или с любого datacenter IP |
| datacenter/country/region/IP markers = 0 | в retained VPS journal нет такого доказательства | что IP-block отсутствует вообще |
| laptop provider snapshot 98% в 08:57Z | read-only quota fetch на ноутбучном контуре был login-valid незадолго до backup | успешный inference turn после snapshot; login probe намеренно не запускался |

Следовательно, текущий VPS **quota-fetch failure** классифицируется как **login/token fault, CONFIRMED**. Quota exhaustion **не наблюдалась до последнего валидного 78–79% состояния**, а после обрыва telemetry остаётся **UNKNOWN**: ноль explicit markers не опровергает событие в ненаблюдаемом интервале. Laptop near-exhaustion — **CONFIRMED at 98%**; datacenter-IP blocking и текущая VPS inference reachability — **UNCERTAIN/user-reported**, потому что current inference probe намеренно не запускался. Нельзя чинить это копированием auth file: официальный OAuth lifecycle и прежний local measurement показывают необходимость refresh-capable `--oauth`; mutating login/model probe в prod не запускался. [M5][M6][O9]

### Runway Grok

VPS burst 14→79 потребил 65 pp примерно за 1.93 h; наивный runway от 79 был 0.59 h, но затем VPS auth telemetry исчезла. Ноутбук позднее показал 98%, то есть burst действительно продолжился, однако между контурами нельзя интерполировать скорость. На laptop осталось 1 pp до target 99 за 10.898 h → требуемый темп всего `0.092 pp/h`; любой обычный крупный Grok turn рискует пересечь 99. Контроллер должен войти в RESERVE: только критичный X/web запрос, если q95-fit известен; иначе дождаться reset. Operational CI всё ещё LOW: один текущий Grok cycle и integer percentages недостаточны.

## Стоимость самого research fan

Fresh WAL-safe snapshot после завершения детей (`quick_check=ok`) дал:

| agent | finalized turns | input | output | cache read | API-equivalent |
|---|---:|---:|---:|---:|---:|
| `limit285-telemetry` (Sol) | 1 | 4 836 532 | 38 243 | 4 636 928 | $4.463774 |
| `limit285-official` (Sol) | 1 | 8 182 150 | 47 979 | 7 800 064 | $7.249832 |
| `limit285-grok` (Sol) | 1 | 10 861 442 | 47 979 | 10 515 456 | $8.427028 |
| **children total** | **3** | **23 880 124** | **134 201** | **22 952 448** | **$20.140634** |
| `research-limit-truth` parent | 0 finalized at capture; current turn in-flight | unavailable until turn-end | unavailable | unavailable | unavailable until turn-end |

Официальный и Grok slices завершились одним уже идущим Sol turn, поэтому безопасного checkpoint для Luna switch не было; им не выдавался второй Sol turn. Это объясняет цену, но не делает fan дешёвым: bounded textual extraction оказался дороже telemetry measurement. Parent exact usage причинно невозможно записать до его terminal event; ноль в таблице — **0 finalized**, не нулевое потребление.

## Fast mode: published claim отдельно от живого замера

Официальный Codex Manual описывает Fast как service tier: для GPT-5.6/5.5 — `1.5×` speed при `2.5×` ChatGPT-credit consumption, для GPT-5.4 — `2×` credits. Та же страница отделяет Fast от Spark как отдельной менее способной модели со своим limit. [O7]

Bounded paired normal↔Fast measurement #208 был запрошен с бюджетом ≤2 percentage points, но его final data не поступили до cutoff #285. Поэтому в этом исследовании нет observed speed/burn multiplier Fast: `1.5×/2.5×` помечено **official claim**, а не measured Orchestra result. Исследование не блокируется на этом пробеле; контроллер применяет официальный credit multiplier консервативно и выключает Fast при THROTTLE/RESERVE/FAIL-SAFE.

## Security note: только классы, без значений

### Что затронуто

1. **Legacy Codex app-server MCP/service credential classes:** Orchestra bridge/session credential, YouGile account/API credentials, Google OAuth client credentials и OpenRouter API key. Конкретного владельца аккаунтов безопасная env-free process metadata не устанавливает. Bug record `20260816T090547.708704Z-1af71fae7df546a4a5b3b73e0d57b3f3.md`: “Live Codex app-server argv still exposes MCP credentials after secrets-to-file fix”. [M7]
2. **Laptop Orchestra proxy credential class:** HTTP(S) proxy URL userinfo credential. Конкретного владельца DB-only evidence не устанавливает. Safe synthetic repro подтвердил false negative masker для URL userinfo без named secret key. Bug record `20260816T092037.705786Z-9c2914c525644fba87d48c2d208ec7d4.md`: “Secret masker leaves credentials embedded in proxy URLs visible in tool stderr”. [M7]

Ни одно значение, contaminated tool-log, `args`/`cmdline`/`environ` и полный платёжный реквизит в artifact не включены.

### Жив ли legacy process

Safe metadata check `2026-08-16T09:31:32Z`: legacy process **live**, start `Sun Aug 16 11:00:47 2026` host time, `comm=codex`, executable class — vendor Codex binary. Эфемерные PID/PPID и точный executable path из durable public artifact исключены; проверка использовала только разрешённые env-free metadata и `/proc/PID/exe`, argv не перечитывался. [M7]

### Shape scan

Scanner печатает только число файлов/байтов/файлов с совпадением, никогда сами совпадения. Финальная команда:

```bash
python3 docs/tasks/285/scan_artifacts.py \
  --path docs/tasks/285 \
  --path docs/tasks/286 \
  --path docs/artifacts/model-limits-source-of-truth.html \
  --commit 536a892b --commit a77d0be3 --commit efc501e6 \
  --commit 78329fb3 --commit cf30c387 --commit 550de1d9 --commit HEAD
```

Этой командой отдельно проверены final worktree scopes `docs/tasks/285/**`, imported frozen `docs/tasks/286/**`, HTML-view и snapshots commits `536a892b`, `a77d0be3`, `efc501e6`, `78329fb3`, `cf30c387`, `550de1d9`, затем final `HEAD`: `matched_files=0` во всех scopes. Отдельный broad tracked-worktree pass ранее нашёл pre-existing candidates вне этих task scopes и намеренно не открывался/не выдавался за clean. [M7]

### Минимальный owner-run rotation/restart runbook

1. Приватно сопоставить классы с активными значениями в их owning secret stores; не копировать значения в чат/логи.
2. У каждого provider rotate/revoke перечисленные credentials и заменить значения в mode-`0600` secret/config owner'а.
3. В явно согласованное окно reconnect затронутую legacy Codex session и restart laptop Orchestra, чтобы старое process state исчезло.
4. Проверить integrations value-free health probes и safe process metadata; затем revoke любой ещё действующий predecessor.
5. Повторить shape scan по #285 artifacts/выбранным commits без печати совпадений.

В рамках #285 rotation, revoke, reconnect и restart **не выполнялись**.

## Confidence и counter-evidence

| finding | confidence | основание / что спорит против |
|---|---|---|
| Claude 5h/weekly threshold durations | **MEDIUM** | direct measurements с 5-minute cadence и gap breaks; integer display, 54 gaps и 106 ambiguous legacy rows ограничивают точность |
| Fable — scoped constraint внутри weekly all | **CONFIRMED** | official primary + live all/scoped response; против версии independent overflow прямо говорит shared consumption [O1] |
| два post-100 turns были Opus, не Fable/credits | **CONFIRMED** | completed `turn_usage.model` + disabled/zero credits; версия in-flight опровергнута starts >1h после first-100 |
| причина admission post-100 | **UNCERTAIN** | rounding, delayed/admission-time accounting и иной undocumented allowance совместимы; cache staleness ≤5m не объясняет час, exact enforcement не public |
| Codex `prolite→pro` — structural break | **CONFIRMED** | соседние source row ids 10199–10201: plan/rescale/anchor jump; точный 4.042× capacity **не доказан** из integer ratio |
| current Codex `pro` runway | **LOW** | меньше одного полного окна после transition; старую `prolite` историю переносить нельзя |
| laptop Grok почти исчерпан | **CONFIRMED** | fresh WAL-safe provider snapshot 98%; это quota signal, но не успешный inference после snapshot |
| VPS Grok quota-fetch failure = token/login | **CONFIRMED для retained window** | 767 token-expired; quota не наблюдалась до 79% и UNKNOWN после cutoff, inference reachability не проверялась |
| VPS datacenter-IP block | **UNCERTAIN** | user report; retained journal содержит 0 datacenter/IP markers, отрицательный marker count не доказывает доступность |
| Spark быстрее Luna на closed+oracle | **LIKELY в узкой границе** | prereg 2/2 tasks, −28.4% wall; малая N, cold-start хуже, isolation не independently probed |
| контроллер стабильно закончит окно у 99% | **HYPOTHESIS** | formula + один historical replay, runtime не реализован; H4 не может стать CONFIRMED до prospective full-window calibration |

### Counter-evidence, которое меняет или ограничивает вывод

- Provider counter `100%` не равен мгновенному denial: два Opus turns прошли позже. Поэтому 52.957/28.830 h — time at displayed 100, не доказанный downtime.
- Fable `0%` рядом с all `100%` выглядит как свободный pool, но official shared rule делает доступный headroom нулевым; dashboard labels без topology вводят в заблуждение.
- Codex plan upgrade резко снизил percentage и сменил anchor. Это опровергает перенос исторического pp/hour между планами и любой forecast без regime detector.
- VPS Grok history остановилась на 79% из-за login telemetry, но laptop позже показал 98%. Ни один контур в одиночку не описывает всю историю; объединять их временные ряды нельзя.
- #286 поддерживает Spark на двух closed tasks, но #222 опровергает перенос результата на missing-decision tasks. Цена Spark остаётся unknown.
- H4 пока не проверена проспективно: replay показывает явный early-exhaust, но не доказывает калибровку p90/p95 и safety margin на будущих окнах.

## Affected files, risks и edge cases следующей фазы

Phase 1 не меняет runtime/config. Durable source и view:

- `docs/tasks/285/research.md` — narrative source of truth;
- `docs/tasks/285/limits-data.json` — machine source of truth;
- `docs/tasks/285/{analyze_limits.py,build_limits_data.py,build_html.py,scan_artifacts.py}` — воспроизводимое построение/проверка;
- `docs/tasks/285/parts/{telemetry,official,grok}/` — frozen sanitized evidence;
- `docs/artifacts/model-limits-source-of-truth.html` — offline view, не отдельный источник фактов.

Если контроллер когда-либо пойдёт в Phase 2/3, главные риски: целочисленное rounding больше 1% margin; one-turn q95 больше remaining headroom; anchor без reset у нулевого Spark; parallel in-flight dispatch; stale telemetry; plan migration; Fable double-constraint; Fast multiplier без observed calibration; credits/offers, которые включили вне Orchestra; смена Grok login home; retention gap ровно у reset. Fail-safe должен быть кодовым gate до spawn/dispatch, а не только рекомендацией в prompt.

## Источники

### Измерения и локальные первичные данные

- **[M1], tier 1 direct measurement:** `docs/tasks/285/parts/telemetry/evidence.json` и exact rendering `evidence.md`; VPS frozen WAL-safe backup, live sanitized `/api/usage`, captured 2026-08-16.
- **[M2], tier 1 reproducibility:** `docs/tasks/285/parts/telemetry/collect.py`; threshold step convention, 900-second gap rule, reset/drop row pairs and production filters.
- **[M3], tier 1 direct experiment:** `docs/tasks/222/` — Spark missing-data 2/2 inventions, Luna 2/2 stops, Spark ~164K loud-fail 2/2.
- **[M4], tier 1 preregistered experiment:** `docs/tasks/286/{research.md,data.json,report.md}`, prereg `89d00a00`, evidence `43a138a8`, accessed locally 2026-08-16.
- **[M5], tier 1 direct measurement:** `docs/tasks/285/parts/grok/evidence.json` и `evidence.md`; bounded VPS journal/DB slice, captured 2026-08-16.
- **[M6], tier 1 direct measurement:** laptop DB-only evidence embedded at `docs/tasks/285/limits-data.json#/laptop_evidence`; remote `Connection.backup`, SHA-256 `91427df287e96a02a097a3923e6cd39849fabe42a577c9403733a847789ca7fc`, `quick_check=ok`.
- **[M7], tier 1 direct measurement:** safe env-free process metadata at 2026-08-16T09:31:32Z; bug record identifiers above; `docs/tasks/285/scan_artifacts.py`. Contaminated logs were not opened.

### Официальные / первичные внешние источники

Все изменчивые факты ниже проверены **2026-08-16**. Полная 59-row матрица с 26 открытыми official URLs, atomic claims, короткими excerpts, 9 отдельными `not_public` rows и counter-evidence: `docs/tasks/285/parts/official/evidence.json`. Вторичные источники не использовались.

- **[O1], tier 2 primary:** [Claude Fable 5 on your plan](https://support.claude.com/en/articles/15424964-claude-fable-5-on-your-plan) — scoped/shared Fable semantics.
- **[O2], tier 2 primary:** [Manage usage credits for paid Claude plans](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans) — included limit vs optional credits.
- **[O3], tier 2 primary:** [What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan) и [Claude pricing](https://claude.com/pricing) — plan offers и five-hour session language.
- **[O4], tier 2 primary:** [Anthropic API pricing](https://platform.claude.com/docs/en/about-claude/pricing) — API list-price semantics, не subscription invoice.
- **[O5], tier 2 primary:** [Codex pricing](https://learn.chatgpt.com/docs/pricing) и [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan) — five-hour/shared turns, weekly may apply, in-flight completion.
- **[O6], tier 2 primary:** [OpenAI ChatGPT credit rate card](https://help.openai.com/en/articles/20001106) — agentic credit rates.
- **[O7], tier 2 single-primary:** [Codex Manual — Speed](https://learn.chatgpt.com/docs/agent-configuration/speed.md) — Fast speed/credit multiplier и отличие Spark. Второй независимый official source не найден; claim не повышен до measured.
- **[O8], tier 2 primary:** [Grok FAQ](https://docs.x.ai/grok/faq), [Grok overview](https://docs.x.ai/grok/overview) и [xAI pricing](https://x.ai/pricing) — paid shared weekly и plan offers.
- **[O9], tier 2 primary/source:** [xAI Grok authentication guide](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md) и [CLI reference](https://docs.x.ai/build/cli/reference) — OAuth/CLI lifecycle.
- **[O10], tier 2 primary:** [xAI X Search](https://docs.x.ai/developers/tools/x-search) и [Web Search](https://docs.x.ai/developers/tools/web-search) — Grok routing niche.
- **[O11], tier 2 primary:** [xAI API pricing](https://docs.x.ai/developers/pricing) и [rate limits](https://docs.x.ai/developers/rate-limits) — API billing/rate limits, отдельно от subscription quota.
- **[O12], tier 2 compiled primary matrix:** `docs/tasks/285/parts/official/evidence.json`; значения с отсутствующим public number записаны `not_public`, не вычислены.
