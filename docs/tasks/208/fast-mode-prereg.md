# #208 — предрегистрация bounded normal ↔ Fast

Записано 16.08.2026 **до первого вызова модели**. Этот файл и `fast_bench.py` коммитятся
отдельно до пилота. После появления результата критерии, порядок, fixtures и формулы не
меняются; исправление стенда аннулирует пилот и требует нового коммита/явной пометки.

Первичная заморозка harness — коммит `7ae174df`, SHA-256
`d4934783d9e11d7b924d5c50fb75c08d3c7ed98e3b69af13ca89f6f22041a1f3`.
17.08.2026 **до первого model call** пользователь изменил правило атрибуции: primary burn metric —
per-turn API-equivalent `$`, целочисленный provider % может остаться confounded. Поправка только
переключает стоппер на прямой virtual cost: 2 п.п. × измеренные в #219 `$5.39/п.п.` = `$10.78`;
перед каждым следующим turn резервируется `$1.00`, превышение резерва одним ходом останавливает
прогон. Provider cap применяется как stopper только в объявленном тихом окне; в текущем запуске
без него остаётся слоем B. Новый SHA записывается отдельным pre-call коммитом ниже.
Исправленный harness SHA-256:
`c5060884b30c6c29d8fbcdae30accc31d4c011831444645b96e8b4025042fe3b`.

Первый runtime preflight остановился **до `turn/start` и до model call**: CLI 0.146.0
канонизирует requested normal `null` в response `serviceTier="default"`, а requested Fast —
в `serviceTier="priority"`; harness ошибочно ожидал `null/standard` и `fast`. Снимки primary
57→57, direct `$0`. Проба обоих `thread/start` без turn подтвердила mapping. Оба допустимых
response-значения исправлены до первой измеряемой ячейки; excluded raw summary —
`fast-mode-preflight-20260817.json`. Повторно замороженный harness SHA-256:
`4fd2e878e3f50081cd5f731ee75fdac01500204ef71dea2421585d0e8c396ed4`.

До обоих коммитов выполнен только `--self-test` без model calls: `PASS`, cold 127190 chars,
warm 1202, answers SHA-256
`28b8b79c901d505352e64e36a3cc2e6b3e2b14caa5fa23ddff85668732e0d6b6`.

## Вопрос

- **Контекст:** Codex CLI 0.146.0, ChatGPT-auth, included weekly primary pool.
- **Изменение:** Fast service tier (`serviceTier="fast"`) на той же модели.
- **Baseline:** Standard (`serviceTier=null`) при том же model/effort/fixture.
- **Исход:** latency до первого answer delta и до `turn/completed`, точность, ошибки,
  токены/API-equivalent cost и движение included primary pool.

Fast — service tier, не Spark: Spark ни разу не выбирается.

## Гипотезы и falsifier

**H1 (дока воспроизводится):** Fast ускоряет медианную latency примерно в 1.5 раза и списывает
included credits примерно в 2.5 раза быстрее, не меняя точность. H1 опровергается по latency,
если парный 95% bootstrap CI speedup целиком ниже 1.0; по качеству — если только один tier
проходит exact grader хотя бы в двух парных репликах; по quota — если чистый пост-переходный
отрезок целочисленного счётчика несовместим с ×2.5 при обоих способах округления.

**H2 (энд-ту-энд ускорения нет):** prefill/очередь/локальный overhead доминируют, поэтому Fast
не уменьшает user-visible latency, хотя tier реально применён. H2 опровергается, если 95% CI
парного speedup целиком выше 1.0 и нет reroute/ошибок/разницы точности.

**H3 (quota неидентифицируема):** общий целочисленный счётчик и параллельные Codex-агенты не
позволят измерить именно этот эксперимент. H3 опровергается только если за интервал нет ни
одного чужого Codex `turn_usage`, `resets_at` неизменен, а последовательность снимков содержит
достаточный пост-переходный отрезок. Пустая/одинаковая дельта не считается доказательством.

## Зафиксированный протокол

- Model `gpt-5.6-sol`, effort `medium`, app-server один на весь прогон.
- Глобальный config не меняется: отдельный временный `CODEX_HOME`, только symlink на auth;
  `features.fast_mode=true`; tier передаётся явно в `thread/start` и `turn/start`.
- Новый ephemeral thread = **cold**; второй turn в том же thread = **warm**. Локальный процесс
  app-server в обоих плечах один, поэтому его startup не попадает в сравнение.
- 6 парных реплик на cell (`normal/fast × cold/warm`), fixed order AB/BA:
  `N0,F0,F1,N1,N2,F2,F3,N3,N4,F4,F5,N5`.
- До подтверждающей выборки — один normal и один fast pilot с seed 999. Они навсегда excluded.
- Каждая реплика: 1 800 детерминированных records, 24 объективных вопроса в cold и другие 24
  в warm. Record set и вопросы побайтно одинаковы внутри пары; в cold добавлен независимый
  CACHE-BUSTER, который не участвует в ответе и ломает межтредовый prompt-cache.
- Модель не знает tier и получает запрет инструментов. Любой tool call записывается, не
  вычищается. Exact JSON grader сравнивает все 24 `{q, final, sum}`.
- TTFT = от записи `turn/start` до первого непустого `item/agentMessage/delta`; отдельно
  записывается первый reasoning/answer delta. End = приход `turn/completed`.
- Usage = последний `thread/tokenUsage/updated.last`; API-equivalent cost: свежий input $5/M,
  cached $0.5/M, cache write $6.25/M, output $30/M. Эти `$` **не приходят от Codex/provider**:
  это локальная оценка Orchestra по `CODEX_TOKEN_PRICES/_codex_cost` из
  `app/backend_codex.py` на main `d38f8785a73df506ef13fdfe8c8bf9911c050c8e`.
- Прямые app-server ходы стенда обходят Orchestra Session Manager и потому не создают строк
  `turn_usage`. Для них тот же локальный алгоритм считается из provider token telemetry;
  у каждой строки хранится формула/provenance. Строки фоновых сессий берутся из
  `turn_usage.cost_usd`; это та же локальная API-equivalent оценка, не provider dollars.
- `/api/usage` primary снимается до/после **каждого хода**: before-cold → after-cold/before-warm
  → after-warm. У каждого direct turn свои два снимка, UTC-границы, токены и `$`.
- Все Orchestra Codex `turn_usage` между baseline/final собираются только из SQLite-снимка,
  снятого через `Connection.backup`. Последовательные provider-снимки разбивают весь прогон,
  включая промежутки без direct turn: для каждого интервала отдельно хранятся direct mode,
  чужие session/model/turns, их токены/$ и cumulative virtual `$`.
- Анализ latency: парные ratios `normal/fast`, медиана, 20 000 bootstrap resamples, percentile
  95% CI отдельно cold/warm и TTFT/end. При `n=6` CI называется широким, точность не симулируется.
- Качество: exact pass rate + Wilson 95% CI; retries/tool errors/reroutes — сырые counts.

## Два слоя расхода

**A — наблюдаемые токены и локальная API-equivalent оценка.** По каждому direct turn:
`input/cached/cache-write/output/reasoning`, локальные `$`, exact pass, wall; сравнения
`$/exact-pass` и `wall-seconds/exact-pass`. По фону — те же поля из `turn_usage`, но mode=`unknown`:
service tier чужого хода из этой таблицы восстановить нельзя.

**B — included primary pool.** У каждого интервала есть целочисленные primary % before/after.
Если наблюдаемая дельта равна `d`, консервативный интервал истинной монотонной дельты при floor
или nearest-integer равен `[max(0,d−1), d+1]` п.п. Для ненулевого cumulative `$` хранится
`[lower/$, upper/$]`; это эмпирическая калибровка `Δprimary_pct / cumulative-virtual-$`, а не
тождество API price и подписочного лимита. `quota-%/quality` считается только при отсутствии
фоновых `turn_usage`, стабильном `resets_at` и явно объявленном тихом окне. Иначе verdict слоя B
навсегда `UNIDENTIFIED`, даже когда слой A полный.

Тихое окно — контрольная валидация, а не допущение стенда: запуск получает `--quiet-window`
только после отдельного сигнала оператора. При фоне raw latency/quality остаются валидны, но
multiplier included pool не атрибутируется arm'у.

## Стоп

- Primary hard cap текущего, фонового запуска: прямой API-equivalent расход стенда `$10.78`;
  при остатке меньше `$1.00` новый turn не начинается. В тихом окне дополнительно действует
  provider utilization +2 п.п.; без тихого окна он не стоппер, потому что включает чужой расход.
- Стоп немедленно после batch при смене `resets_at`, tier mismatch, model reroute, отсутствии
  token/TTFT telemetry или failed pilot.
- В объявленном тихом окне любое движение primary между предыдущим after и следующим before —
  неожиданный drift: model call не начинается.
- Шаг счётчика, совпавший с чужим Codex-ходом, не атрибутируется Fast/normal.
- Если чистого пост-переходного отрезка нет, verdict quota = **UNIDENTIFIED**, а не ×2.5 и не ×1.

## Decision rule для контроллера

Fast окупается в quota-нейтральной метрике только когда стоимость минуты ожидания выше цены
дополнительных 1.5 standard-credit units. Для одинакового объёма:

`Fast` сокращает время на `1 - 1/s`, где `s` — измеренный speedup, и добавляет `1.5 × C`
included credits к standard cost `C`. Порог:

`value_of_time × T × (1 - 1/s) > value_of_quota × 1.5 × C`.

До результата это только формула, не рекомендация. Контроллерный verdict после замера обязан
разделить interactive/blocking и unattended/batch; «99% запретить» принимается только если
измеренная выгода мала/CI пересекает 1 или quota multiplier живым замером не опровергнут.

## Источник

Свежий Codex Manual, раздел `Speed` (получен helper'ом 16.08.2026): Fast поддерживает GPT-5.6,
GPT-5.5, GPT-5.4; заявлено 1.5× speed; GPT-5.6/5.5 — 2.5× Standard credits; GPT-5.4 — 2×.
`/fast` и `service_tier="fast"` — один tier; API Priority — отдельный биллинг; Spark — отдельная
модель с отдельным лимитом.
