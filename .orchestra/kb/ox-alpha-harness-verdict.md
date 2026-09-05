# Ox Alpha + свой харнес: вердикт первого рабочего дня (22.08.2026)

Один день, четыре задачи (#366–#369), пять воркеров, ноль подписочной квоты. Ниже — что
измерено по журналу, а не по впечатлению.

## Числа

| воркер | вызовов тулов | ошибок тула | ходов |
|---|---:|---:|---:|
| `ox-probe` (проба) | 10 | 0 | 1 |
| `feat-harness-bubbles` (#369) | 156 | 0 | 4 |
| `feat-model-catalog` (#366) | 219 | 0 | 14 |
| `feat-or-quota` (#368) | 235 | 0 | 15 |
| `harness-tools` (#367) | 238 | 0 | 11 |
| **итого** | **858** | **0** | **45** |

Завершения ходов: `end_turn` 38, `aborted` 4 (мои `stop_worker`), `max_turns` 3.
За день в `main` ушло 17 коммитов, 67 файлов, +6 738 / −38 строк.

Распределение вызовов: `bash` 464, `edit` 132, `write` 31, `send_message` 27, `read` 18,
`review` 7, `codex_review` 6, остальное единицами.

## Что модель делала хорошо

**Не врала о сделанном.** Ноль ошибок инструментов на 858 вызовов — это не «повезло», а
следствие того, что модель проверяла результат каждого действия. Ни одного случая
«напечатал tool call текстом вместо вызова» — классической болезни, которую мы ловим у
Opus.

**Отрицательный результат объявляла отрицательным.** `harness-tools` измерил батчинг и
написал: флаг раунды не снизил, `[2,3] → [4,3]`, причина — модель батчит нативно. Отчитаться
«внедрил оптимизацию» было проще и никто бы не проверил. Там же — честное «200 это
паритетный якорь к Claude, а не вывод из распределения, n=9 мало для хвоста».

**Проверяла ЧУЖИЕ числа, включая мои.** `feat-or-quota` перепроверил живыми запросами все
факты из моей постановки (662 за 08.08, 92 за 21.08, 7 на ox-alpha) — сошлись байт в байт.
Он же нашёл третьего мутанта, которого пережил его собственный сид, и усилил сид.

**Находила то, о чём не просили.** Неиспользуемая таблица `kv` без единого писателя;
`_clear_selectable_models()`, который стёр бы каталог при первом же обновлении; два разных
вида `429`, неразличимых в одном обработчике; синхронные тулы на event loop сервера
(2008 мс против 10 мс).

**Планы защищали себя сами.** Без внешнего ревьюера (пулы выжжены) `feat-model-catalog`
написал раздел «чем каждый тикет может тихо пройти на сломанной реализации» — по пункту на
тикет, с конкретным механизмом, а не «риски вообще».

## Где ломалась

**Молчаливое завершение хода — системно, 4 раза у одного воркера.** Ход кончается, работа
не закоммичена, `send_message` не позван. Снаружи неотличимо от потерянной работы; каждый
раз я шёл проверять руками. Правило есть в `base.md` с #257 — не исполнялось.

**Отчёт расходился с артефактом трижды за день:**
- «на скриншотах видно бабблы» — на полном снимке пустой чат (живой код чистил `#chat`
  между вызовами, снимок брал видимую область);
- «T4–T6 закрыты, мутации пойманы» — шесть файлов вместе давали `12 failed, 3 errors`;
- «зелёный прогон на сломанной реализации» — вместо ответа список красноты от `ImportError`,
  то есть подмена вопроса «сторожит ли тест» вопросом «исполняется ли тест».

Все три поймались одним и тем же: я открывал файл или запускал прогон сам.

**Изоляция тестов как слепое пятно.** Глобальные словари реестра мутировались и не
восстанавливались — тесты зеленели поодиночке и краснели вместе. Модель этого не
предвидела, хотя писала тесты именно к тому коду, который мутирует эти словари.

## Где ломался харнес (наш код, не модель)

Десять дефектов инструментов, все врали в сторону «проблемы нет»: поиск падал на `grep` без
поддержки альтернации и отвечал «нет совпадений» при четырёх; фильтр по файлу игнорировался;
stderr выбрасывался; кириллица объявлялась двоичным мусором на разрезе многобайтного
символа; нумерация строк сдвинута на единицу; чтение за EOF отвечало «пусто»; правка
сбрасывала права до `0600` всегда.

**Цена этого измерена: медиана 7 → 3 раунда на задаче (−57%).** Агент, которому инструмент
соврал, не останавливается — он перепроверяет вторым способом, потом третьим, и каждая
перепроверка стоит запроса из суточной тысячи.

Отдельно: `MAX_TOOL_ROUNDS = 50` против `max_turns=200` у Claude, обрыв без отчёта. Поднято
до 100 с предупреждением за 10 и 3 раунда до конца.

## Чего у харнеса нет по сравнению с Claude/Codex

- **Автокомпакта.** `_precompact_policy()` возвращает `None` — длинный диалог упрётся в
  контекст жёстко. При 1M это далеко, но потолка нет вовсе.
- **Тихое усечение истории.** `_fit_context` выбрасывал середину задолго до лимита без
  единого признака. Теперь событие видно (T9), но память это не возвращает.
- **Steering появился только сегодня** — до правки `send()` при активном ходе бросал
  исключение, и поправка ждала конца хода.

## Вердикт

**Рантайм рабочий, модель — сильная.** Четыре задачи за день на нулевой подписочной квоте,
858 вызовов без единой ошибки инструмента, честные отрицательные результаты, находки за
пределами постановки.

Главное ограничение не в модели, а в **дисциплине отчётности**: три расхождения отчёта с
артефактом за день. Все пойманы проверкой артефакта, ни одно — чтением отчёта. Это ровно то,
что делает внешнюю проверку обязательной, а не украшением; сегодня её заменял я вручную,
потому что оба подписочных пула стояли.

Что это меняет в практике: **Ox Alpha годится как основной исполнитель**, но приёмка по
артефакту (открыть файл, запустить прогон, посмотреть скриншот) не необязательный шаг, а
условие. Дешевле требовать доказательство сразу, чем ловить расхождение на мерже.

## Обновление 23.08.2026 — #236

- Identity по-прежнему НЕ раскрыта: OpenRouter прямо называет third-party provider anonymous, а exact Models API вернул `benchmarks=null` · https://openrouter.ai/stealth/ox-alpha + `.orchestra/tasks/236/evidence/free-model-metadata-2026-08-23.json` · #236
- В frozen no-effort матрице exact route был доступен и дал 0/6 429, но шесть из шести ответов были пустыми: 0 text, 0 tool calls, 0 usage rounds, 0/6 полезных задач, median 5.551 s · `.orchestra/tasks/236/evidence/matrix/r*-stealth__ox-alpha.json` · #236
- Вывод «основной исполнитель» ОТОЗВАН как БЕЗУСЛОВНЫЙ: вчерашние 858 tool calls остаются прямым evidence capability, но сегодняшняя endpoint drift требует daily production-shaped canary; после canary — только public/non-confidential work и acceptance по артефакту · два измерения 22.08/23.08, #236
- Даже зелёный canary НЕ допускает Ox в production free-only pool: ID без `:free`, а нулевая metadata перед POST имеет TOCTOU и не запрещает провайдеру сменить цену; нужен доказанный provider-side atomic zero-spend, которого сейчас нет · review #236 + exact id `stealth/ox-alpha` · 23.08.2026, #236

## Gaps (обновление #236)

- Frozen matrix намеренно не передавала `reasoning.effort`, тогда как production `HarnessBackend` передаёт; это может объяснять пустые Ox ответы, но добор после раскрытия результата был бы exploratory и не меняет frozen verdict · 23.08.2026, #236

## Источники (обновление #236)

- .orchestra/tasks/236/research.md — current identity/metadata, free-only guard and frozen cross-model comparison

## Обновление #283 (23.08.2026)

- #283 не сделал inference-вызов: preflight показал `MemAvailable=3,666,888 kB` при обязательном пороге 4,194,304 kB и отсутствующий OpenRouter key; guard остановился до metadata/POST, `http=0`, `usage.cost=[]` · `.orchestra/tasks/283/evidence/preflight-stop.json` · 2026-08-23, #283
- Текущий production-путь выставляет `reasoning.effort=high` для frozen `closed_edit` и `closed_trace` (ключевые слова `Fix`/`Trace`) и `medium` для `open_audit` (391 символ, без high-keyword, worker) через `HarnessBackend.events()` → `AgentLoop` → `OpenRouterClient._build_body`; это source-derived mapping, не live model evidence · `app/backend_harness.py:34-74,241-245`, `app/harness/loop.py:207-216`, `app/harness/llm.py:154-168` · 2026-08-23, #283
- #236's six Ox turns remain a no-effort experiment: all six `ok=true,end_turn`, one HTTP attempt each, zero tool calls/rounds/cost; #283 therefore cannot attribute empties to effort versus endpoint drift · `.orchestra/tasks/236/evidence/matrix/r{1,2}-*stealth__ox-alpha.json`, `.orchestra/tasks/283/research.md` · 2026-08-23, #283

## Gaps (обновление #283)

- Current production-shaped Ox response under `reasoning.effort` remains unmeasured because the mandatory memory guard fired before metadata and no key was present; rerun requires `MemAvailable≥4 GiB` and guarded credentials · 2026-08-23, #283

## Источники (обновление #283)

- .orchestra/tasks/283/research.md — frozen protocol, production-path effort mapping, hard-stop receipt, and historical reconciliation
- .orchestra/tasks/283/evidence/preflight-stop.json — sanitized pre-inference guard measurement

## Обновление #283 — Contabo continuation (23.08.2026)

- Remote production-shaped Ox run completed six serial interleaved tasks through `HarnessBackend.events()`/`AgentLoop`: 31 guarded HTTP attempts, all exact metadata rows `stealth/ox-alpha` with `prompt="0"`, `completion="0"`, 0 platform/upstream 429, 0 tool errors, 0 empty responses, and no fallback model list · `.orchestra/tasks/283/evidence/remote-57473bf0/{summary,guard}.json` · 2026-08-23, #283
- Corrected external grading (raw grader defects preserved) scored `closed_edit=1.0,1.0`, `closed_trace=1.0,1.0`, `open_audit=10,9`; valid alternate control passed; useful completion/request = `6/31=0.193548` · `.orchestra/tasks/283/evidence/remote-57473bf0/corrected-grades.json` + preserved artifacts · 2026-08-23, #283
- Post-response cost telemetry had 30 explicit `usage.cost=0.0` values and one omitted `usage.cost`; no nonzero cost was observed, so the omitted field remains missing rather than being treated as zero · `.orchestra/tasks/283/evidence/remote-57473bf0/r*.json` · 2026-08-23, #283
- The first frozen grader was invalid for two reasons: it required qualified names absent from the fixture's function path, and it crashed on evidence-bearing audit category objects; corrected grading used the fixture's exact `create→build→send→complete→post` path and extracted `category` fields without rerunning Ox · `.orchestra/tasks/283/evidence/remote-57473bf0/corrected-grades.json` · 2026-08-23, #283

## Gaps (обновление #283 Contabo)

- The runner records production classifier effort (`high/high/medium`) but does not preserve the serialized request body; direct wire-level `reasoning.effort` receipt is therefore source-proven, not independently captured in the raw JSON · runner source + production `app/harness/llm.py:154-168` · 2026-08-23, #283

## Источники (обновление #283 Contabo)

- .orchestra/tasks/283/research.md — Contabo run, corrected grading, metrics, and reconciliation
- .orchestra/tasks/283/evidence/remote-57473bf0/ — sanitized page/API guards, events, artifacts, and scores
