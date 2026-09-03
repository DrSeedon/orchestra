# #208 — Fast mode: живой normal ↔ Fast замер

**Fast реально ускорил доставленный ответ, но не дал 1.5× во всех наших ячейках; улучшение
успешной пропускной способности на этом малом корпусе не установлено.** На `gpt-5.6-sol`, effort `medium`,
Fast дал медианный парный speedup `1.23×` cold и `1.43×` warm по wall time; exact quality —
`4/12` против `5/12` у Standard, различие при N=12 не установлено. Локальная
API-equivalent цена почти одинакова (`$2.47` против `$2.56`), потому что Orchestra считает
токены по Standard price table и **не знает 2.5× Fast credit multiplier**. Included primary
пул вырос 58→60 %, но за окно прошли ещё 19 Codex-ходов на `$18.76` против `$5.90` стенда:
quota multiplier живым счётчиком **UNIDENTIFIED**. Поэтому Fast — не режим для throughput;
его следует запрещать контроллером по умолчанию и разрешать только на явно user-blocking
критическом пути, где несколько секунд ожидания дороже дополнительного quota burn.

Дата замера: 17.08.2026. Предрегистрация и harness до первого model call: коммиты
`7ae174df`, `03caa07f`, `3d7c9df6`. Raw machine-readable artifact:
`fast-mode-results.json`, SHA-256
`2eda03c9f2e5e98ad57624b3c2fa6523c94d656111b4a741f42e44be4ed105a1` [2].

## Вопрос и конкурирующие гипотезы

- **Контекст:** Codex CLI 0.146.0, ChatGPT auth, `gpt-5.6-sol`, effort `medium`.
- **Изменение:** тот же запрос через Fast service tier; response wire value — `priority`.
- **Baseline:** Standard; response wire value — `default`.
- **Исход:** первый доставленный answer delta, `turn/completed`, exact grader, ошибки,
  токены/cache/output, локальные `$` и provider primary %.

H1: Fast уменьшает end-to-end latency примерно в заявленные 1.5 раза без потери качества.
Фальсификатор: парный CI ниже/пересекает 1, либо только один tier устойчиво проходит exact
grader. H2: prefill/очередь/локальный overhead съедают выигрыш. Фальсификатор: CI целиком выше
1 и близок к 1.5. H3: provider quota multiplier нельзя атрибутировать при фоне. Фальсификатор:
нет чужих Codex turns, reset стабилен, после шага счётчика есть чистый отрезок.

## Что именно было запущено

| Параметр | Значение |
|---|---:|
| Model / effort | `gpt-5.6-sol` / `medium` |
| Confirmatory sample | 6 пар на tier × cold/warm = 24 turns |
| Excluded pilot | 1 normal + 1 Fast thread = 4 turns; все exact PASS |
| Fixture | 1 800 records, 24 двухшаговых lookup-вопроса на turn |
| Cold | новый ephemeral thread + nonce/cache-buster |
| Warm | второй набор вопросов по тем же records в том же thread |
| Order | предзаданный AB/BA, 6 реплик |
| Tools | запрещены инструкцией; фактически 0 calls |
| Global config | не менялся; tier передан только isolated app-server |

Первый preflight не дошёл до `turn/start`: harness ожидал буквальные `fast`/`standard`, а CLI
возвращает канонические `priority`/`default`. Primary остался 57→57, direct `$0`; ошибка и
исправление заморожены до model calls в `fast-mode-preflight-20260817.json`.

## Результат A — latency

`TTFT` здесь — время до первого **доставленного** `item/agentMessage/delta`. Во всех 24
confirmatory turns этот timestamp совпал с первым model delta: отдельные reasoning/text delta
не пришли. Поэтому это не время до скрытого внутреннего reasoning token, которого app-server
не показывает в этом schema-constrained прогоне.

| Cell | Standard median | Fast median | Парный speedup N/F | Paired bootstrap 95 % CI |
|---|---:|---:|---:|---:|
| Cold TTFT | 17.38 s | 15.33 s | **1.131×** | 1.087–1.310 |
| Cold wall | 24.16 s | 19.37 s | **1.229×** | 1.054–1.349 |
| Warm TTFT | 11.42 s | 8.44 s | **1.298×** | 1.196–1.589 |
| Warm wall | 18.14 s | 12.95 s | **1.428×** | 1.149–1.609 |

Практическая экономия медианы: `4.79 s` cold и `5.18 s` warm на turn. Суммарный wall для 12
Standard turns — `253.55 s`, Fast — `201.35 s`, то есть aggregate speedup `1.259×` [2].

Bootstrap CI выше — описательный при N=6, не самостоятельное доказательство направления.
Cold wall был быстрее на Fast в 5/6 пар (exact sign test, two-sided `p=0.219`), warm wall —
6/6 (nominal `p=0.03125`); одна cold-пара была **медленнее** (`0.897×`), одна warm почти
равна (`1.011×`). Заявленные 1.5× — про model speed, а не гарантия нашего end-to-end wall
[1]. Cold CI целиком ниже 1.5; warm CI 1.5 включает.

**Confidence: CONFIRMED для измеренных времен; LIKELY для устойчивого ускорения этой fixture.**
Warm directional evidence сильнее cold; N=6 не устанавливает общий multiplier задач.

## Результат B — exact quality и ошибки

| Cell | Standard | Fast | Wilson 95 % CI Standard | Wilson 95 % CI Fast |
|---|---:|---:|---:|---:|
| Cold exact PASS | 2/6 | 2/6 | 0.097–0.700 | 0.097–0.700 |
| Warm exact PASS | 3/6 | 2/6 | 0.188–0.812 | 0.097–0.700 |
| Всего | **5/12** | **4/12** | 0.193–0.680 | 0.138–0.609 |

Парная раскладка 12 turns: оба PASS `3`, только Standard `2`, только Fast `1`, оба FAIL `6`.
Exact McNemar по discordant-парам даёт `p=1.0`: устойчивую разницу качества этот результат
не устанавливает. Отдельные Wilson intervals в таблице описывают неопределённость каждого
arm, но не заменяют парное сравнение. Низкий общий PASS означает, что fixture действительно
не потолочная — в отличие от лёгких заданий #199.

- 24/24 confirmatory turns завершились `completed`.
- Model reroutes: `0`; thread tier mismatches: `0` (`default` у Standard, `priority` у Fast).
- Tool calls / tool errors: `0 / 0`.
- Observable errors/warnings/retry events: `0`. Внутренние provider retries, не публикуемые
  app-server, этим числом не покрываются.

**Confidence: UNCERTAIN по разнице качества.** N=12/tier и paired McNemar `p=1.0` не
отличают реальную разницу от дисперсии модели.

## Результат C — токены, cache и локальные `$`

Confirmatory sample, pilots исключены:

| | Standard | Fast | Fast / Standard |
|---|---:|---:|---:|
| Turns / exact PASS | 12 / 5 | 12 / 4 | — |
| Input tokens | 800 244 | 800 150 | 1.000 |
| Cached input | 391 680 | 409 600 | 1.046 |
| Cache write | 0 | 0 | — |
| Output tokens | 10 669 | 10 529 | 0.987 |
| Reasoning output | 6 433 | 6 293 | 0.978 |
| Local API-equivalent `$` | **2.55873** | **2.47342** | **0.967** |
| Local `$` / exact PASS | **0.51175** | **0.61836** | **1.208** |
| Wall seconds / exact PASS | 50.71 | 50.34 | 0.993 |

Fast оказался на 3.3 % дешевле в локальных `$` из-за небольших различий cache/output, не из-за
tier pricing. В cold Fast получил 17 920 cached tokens, Standard — 0; это дало Fast часть
ценового преимущества и не было целью эксперимента. Input почти побайтно равен.

Происхождение `$` проверено по коду: `turn_usage.cost_usd` и harness используют локальную
`CODEX_TOKEN_PRICES/_codex_cost` с Standard ставками Sol `$5/$0.5/$6.25/$30` за миллион
fresh/cached/write/output tokens. Codex/provider долларов не присылает [3]. Прямые app-server
turns не создают DB-строк `turn_usage`, поэтому harness воспроизводит ту же формулу из
`thread/tokenUsage/updated.last`; foreign turns берутся из `turn_usage`.

Следствие: `2.47342` — **не subscription burn Fast**. Официальный Manual отдельно заявляет
2.5× Standard credits для GPT-5.6 Fast при ChatGPT auth; при API key действует другой API
Priority billing [1]. Если только для иллюстрации умножить Fast local `$` на документированные
2.5 как credit-weighted proxy, получаем `$6.18355`, или `$1.54589/PASS` — в `3.02×` хуже
Standard на этой выборке. Это proxy, не измеренный доллар и не результат provider quota arm.

**Confidence: CONFIRMED для токенов и локальной формулы; UNIDENTIFIED для subscription
credits.**

## Результат D — included primary pool и фон

| | Полный прогон | Confirmatory only |
|---|---:|---:|
| Provider primary | 58→60 % | 58→60 % |
| Direct harness local `$` | 5.89930 | 5.03215 |
| Foreign Codex local `$` | 18.76351 | 15.46206 |
| Cumulative local `$` | 24.66281 | 20.49421 |
| Foreign turns | 19 | 16 |
| Quantization bound истинной Δ | 1–3 п.п. | 1–3 п.п. |
| `Δpp / cumulative-$` bound | 0.0405–0.1216 | 0.0488–0.1464 |
| Обратный `$ / pp` bound | 8.22–24.66 | 6.83–20.49 |

Фон по DB snapshot (`Connection.backup`), полный интервал:

| Session | Model | Turns | Local `$` |
|---|---|---:|---:|
| `fix-tspu-ingress` | Sol | 3 | 5.93503 |
| `feat-review-council` | Sol | 1 | 3.20841 |
| `bench-effort` parent turn | Sol | 1 | 3.04280 |
| `back` | Sol | 3 | 2.04598 |
| `fix-task-tool-labels` | Sol | 1 | 1.98189 |
| `i0-red-oracle` | Luna/Sol across rows | 7 | 1.85385 |
| `ai-table-lead` | Sol | 1 | 0.40408 |
| `Claude-Code-Game-Master-orchestrator` | Sol | 2 | 0.29148 |

Два видимых шага счётчика пришлись на Standard turns без foreign completion внутри именно
этих коротких интервалов. Это **не** доказывает, что Standard списался, а Fast нет: до шагов
накопились чужие и Fast расходы, counter целочисленный, а provider update может запаздывать.
Фальсификатор H3 не выполнен: foreign turns есть, тихое окно не объявлялось.

**Verdict quota: UNIDENTIFIED.** Можно оценить только общий mapping cumulative local `$` к
округлённой Δ всего контура; разложить 2 п.п. на Standard/Fast или подтвердить 2.5× нельзя.

## Когда Fast окупается

При одинаковом качестве, Standard cost `C`, normal time `T` и speedup `s` Fast экономит
`T × (1−1/s)` времени и, по Manual для GPT-5.6, добавляет `1.5C` credit-equivalent burn.
Break-even:

`value(time) × T × (1−1/s) > value(quota) × 1.5C`.

Для throughput без срочности Fast проигрывает по построению: даже при vendor `s=1.5` получаем
лишь `1.5 / 2.5 = 0.60` Standard throughput на credit. На нашем aggregate `s=1.259` —
`1.259 / 2.5 = 0.504`, примерно половина Standard throughput на документированный credit.
Это ещё без учёта неустановленной разницы качества.

### Контроллерный verdict

**Данные поддерживают `default off pending workload-specific measurement`.** Число «99 %»
этот опыт не измерял: у нас нет production-распределения latency-critical ходов. Если владелец
задаёт 99%-off как консервативный rollout budget, это provisional policy prior, а не эмпирический
результат #208. Предварительный whitelist может оставлять только ход, где одновременно выполнены
все условия:

1. человек или критический fan-in прямо сейчас ждёт результат;
2. несколько секунд действительно меняют исход/SLO, а не просто выглядят приятнее;
3. задача короткая и bounded, без ожидаемой цепочки retries;
4. quota runway допускает 2.5× credit rate;
5. controller пишет tier и причину, чтобы whitelist можно было пересчитать.

До отдельного production workload sample разумно оставлять Fast выключенным для unattended
research, batch/replay, фоновой реализации и служебных ходов без человека на критическом пути.
Условия whitelist выше — проверяемая гипотеза политики, не валидированные этим стендом правила.
На этой выборке raw wall сократился на 52.2 s, а описательный quality-normalized ratio составил
50.34 против 50.71 s/PASS. При N=12 и McNemar `p=1.0` это **не доказывает** ни равную, ни
лучшую успешную throughput Fast и не является основанием policy само по себе.

## Counter-evidence и ограничения

- Manual обещает 1.5× model speed, и warm wall CI включает 1.5; утверждение «дока неверна» из
  этого замера не следует [1].
- N=6 на latency cell и N=12/tier на quality; bootstrap/Wilson intervals широкие.
- Одна fixture и одна модель/effort. Tool-using кодовая цепочка не проверена.
- Exact grader строгий и хранит только pass/hash; post-hoc частичную точность восстановить
  нельзя, что защищает от смены метрики, но снижает диагностическую мощность.
- Schema-constrained output не дал reasoning deltas, поэтому TTFT — первый доставленный JSON
  token, не скрытый внутренний token.
- Provider quota arm потерян из-за 19 foreign turns и целочисленного counter. Локальные `$`
  нельзя называть subscription credits без тихой калибровки.
- Cache чуть различался между tiers; ценовой результат нельзя читать как tier discount.

## Сопутствующий lifecycle-аудит #201

`bench201-x` проверен против принятого `a085d858`: его единственный commit содержал более
слабую реализацию и 38 строк research, чьи три вывода уже полностью покрыты accepted report.
KILL_SAFE proof — `bench201-x-audit.md`; one-shot worker был idle/clean и архивирован без
потери уникального evidence.

## Review gate inputs

- Changed artifacts/consumers: `fast-mode.md` и сводка в `research.md` читаются пользователем
  и задачей #285; `fast-mode-results.json` — machine-readable source; production runtime не
  менялся.
- Author metadata: session `bench-effort`, Codex runtime, `gpt-5.6-sol` (не вывод из имени).
- AC: одинаковые Standard/Fast fixtures; per-turn latency/grade/tokens/local `$`; primary
  before/after; весь foreign Codex spend; bounded direct `$`; controller verdict с явной
  границей `UNIDENTIFIED`.
- Named checks: `python3 -B docs/tasks/208/fast_bench.py --self-test` → `PASS`;
  independent JSON assertions → `RESULT INTEGRITY PASS: 24 turns, tiers/default+priority,
  quality 5/12 vs 4/12, foreign 19/19 assigned once`; SHA-256 raw JSON совпал с указанным.
- Review route: frozen grader механически закрывает raw quality, но statistical/controller
  вывод не имеет strong deterministic oracle → targeted Sol research review, два раунда.
- Review outcome: в первом раунде принят один blocking и три suggestions; после правок второй
  раунд завершён вердиктом `Completed. No blocking or suggestion findings remain`. Проверяемая
  дословная цитата из изменённого файла: «Условия whitelist выше — проверяемая гипотеза
  политики, не валидированные этим стендом правила». Полный след — `review-fast-mode.md`.

## Источники и артефакты

1. **Primary source:** актуальный OpenAI Codex Manual, [Speed](https://learn.chatgpt.com/docs/agent-configuration/speed.md),
   получен official manual helper 17.08.2026. Заявляет 1.5× speed, GPT-5.6 Fast = 2.5×
   Standard credits, отделяет Fast от Spark и API-key Priority billing.
2. **Tier 1 direct measurement:** `docs/tasks/208/fast-mode-results.json`, SHA-256 выше;
   per-turn timestamps, tiers, grades, tokens, local cost, provider snapshots и foreign rows.
3. **Primary local code:** `app/backend_codex.py` на main
   `d38f8785a73df506ef13fdfe8c8bf9911c050c8e`, `CODEX_TOKEN_PRICES` + `_codex_cost`;
   принятая #201 `a085d858` сохраняет те же ставки и добавляет cache-write telemetry.
4. **Frozen method:** `docs/tasks/208/fast-mode-prereg.md` и
   `docs/tasks/208/fast_bench.py`.
