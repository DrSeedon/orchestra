# #243 — Codex resume при смене модели внутри рантайма

## Вопрос

**Контекст:** Orchestra сейчас считает любую смену модели внутри `codex` несовместимой с
нативным resume: `resume_across_models=False` в `app/runtime_registry.py`, поэтому
`AgentSession._change_model_locked()` архивирует thread id и строит `runtime_handoff`.

**Проверяемое изменение:** возобновить один настоящий Codex thread, созданный на Sol, сначала
на Luna, затем на Spark, не импортируя и не пересобирая историю.

**Baseline:** resume того же thread на той же модели Sol.

**Решающий исход:** `thread/resume` возвращает запрошенный id, а новая модель дословно возвращает
UUID, который находился только в первом user turn. Для цены сравниваются `input_tokens`,
`cached_input_tokens` и API-equivalent `cost_usd` первого хода после resume.

## Гипотезы и фальсификаторы

1. **H1:** Codex 0.146.0 умеет native resume между моделями одного рантайма, потому что модель
   задаётся заново и в `thread/resume`, и в `turn/start`, а thread остаётся тем же.
   **Фальсификатор:** protocol/model error, другой returned id или отсутствие UUID в ответе.
2. **H2 (альтернатива):** app-server принимает resume формально, но новая модель получает чистый
   контекст. **Фальсификатор:** точный UUID из первого user turn в ответе новой модели.
3. **H3:** видимая история сохраняется, но prefix cache привязан к модели и первый changed-model
   ход становится почти cold. **Фальсификатор:** cache hit Luna/Spark сопоставим с Sol control.
4. **H4:** Spark отказывает не из-за смены модели, а только когда сохранённый контекст больше
   его собственного окна. **Фальсификатор:** отказ ниже окна либо успешный ход выше окна без
   compaction.

## Стенд

- Бинарник: дословный вывод `codex --version` — `codex-cli 0.146.0`.
- Отдельный `CODEX_HOME` под `/home/kesha/.cache/orchestra-probes/r243-*`; из рабочего home
  копировался только `auth.json`. Живые worker/thread не использовались.
- Из одного замороженного Sol seed сделаны три независимые ветки:
  `Sol→Sol control`, `Sol→Luna` и `Sol→Spark`.
- Один thread id на всём пути:
  `019ff9b0-8c7e-7d72-b1b0-80c7c72494bd`.
- Маркер `R243-6eac83ef-0ef0-41a4-b7e0-50c941eb6202` присутствовал **только в первом user
  message**. Текущий prompt и `developerInstructions` при resume маркер не содержали.
- Первый пробный стенд исключён из semantic evidence: он ошибочно повторял маркер в новых
  `developerInstructions`. Его cache-цифры согласовывались с финальным прогоном, но вывод о
  recall на нём не строится.

Команда и полный воспроизводимый код — `probe_cross_model_resume.py`; literal результаты —
`probe-results.json` и `probe-spark-overflow.json`.

## Findings

### F1. Sol→Luna и Sol→Spark продолжают тот же native thread — CONFIRMED

| Ход | requested id = returned id | Ответ содержит UUID | Статус |
|---|---:|---:|---|
| Sol→Sol control | да | да | `ok=true`, `end_turn` |
| Sol→Luna | да | да | `ok=true`, `end_turn` |
| Sol→Spark | да | да | `ok=true`, `end_turn` |

Во всех трёх случаях returned/session id дословно равен seed id. Luna и Spark вернули
`R243-6eac83ef-0ef0-41a4-b7e0-50c941eb6202`, которого не было в текущем запросе. Значит
`resume_across_models=False` — консервативное допущение, а не ограничение Codex CLI. [M1]

**Confidence: CONFIRMED** — прямой изолированный прогон, semantic oracle и проверка identity.

### F2. Первый changed-model ход сохраняет историю, но теряет большую часть prefix cache — CONFIRMED для этого прогона

| Первый ход после resume | input | cache read | fresh input | cache hit | API-equivalent cost |
|---|---:|---:|---:|---:|---:|
| Sol→Sol control | 33 651 | 31 488 | 2 163 | 93.57% | $0.027489 |
| Sol→Luna | 38 310 | 5 888 | 32 422 | 15.37% | $0.00669456 |
| Sol→Spark | 35 761 | 5 504 | 30 257 | 15.39% | неизвестна |

Luna получила примерно в 15 раз больше fresh input, чем same-model control; Spark — примерно
в 14 раз. Потеря cache не делает Luna дороже Sol в долларах: цена Luna на fresh input намного
ниже, и фактический первый Luna-ход стоил $0.00669456 против $0.027489 у тёплого Sol control.
Для Spark денежная цена не заявляется: `CODEX_TOKEN_PRICES` намеренно хранит `None`, и событие
вернуло `cost_unaccounted=true`. [M1][C1]

Это измерение первого changed-model хода, а не утверждение о вечной потере cache: прогон не
мерил второй Luna/Spark ход и не устанавливает, когда новый prefix снова прогревается.

**Confidence: CONFIRMED для трёх веток одного Sol-seed canary** — runtime token counters;
обобщение на другие длины и задержки остаётся LIKELY.

### F3. Spark принимает cross-model resume ниже окна, но первый ход громко падает выше окна — CONFIRMED

Ниже окна Spark принял тот же id при `context_tokens=35 761`, сообщил собственный effective
`max_tokens=121 600` и вспомнил UUID. [M1]

В отдельном overflow-прогоне Sol сохранил тот же thread при `context_tokens=132 343` из
`258 400`. Затем `thread/resume` на Spark тоже вернул тот же id, но первый `turn/start`
завершился:

```text
ok=false
model_error=context_window
input_tokens=0
Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying.
```

Автоматического compaction перед отказом не было. Это отказ по размеру после успешного resume,
не запрет смены модели. [M2]

**Confidence: CONFIRMED** — два разрешающих плеча ниже окна и один адресный отрицательный
прогон выше runtime-reported окна.

### F4. Что именно переносится и теряется — частично CONFIRMED

- **Переносится:** native thread id и доступный модели диалог; semantic canary доказал recall
  раннего user fact без summary/import. [M1]
- **Не переносится как тёплый cache:** в первый changed-model ход cache hit упал с 93.57% до
  15.37–15.39%. [M1]
- **Внутреннее reasoning-состояние:** UNCERTAIN. Rollout физически остаётся тем же, но внешний
  протокол не сообщает, какие provider-specific reasoning blobs новая модель использовала.
  Дословный UUID доказывает видимый контекст, а не перенос скрытого состояния.

## Изменение в коде

`app/runtime_registry.py` меняет одну capability-строку для `codex`:

```python
resume_across_models=True
```

Тогда существующая ветка `app/session.py` сама оставляет `session_id` на месте, отключает старый
backend и следующий connect делает штатный `thread/resume` уже с новой моделью. Нового пути,
конвертера или handoff-кода не появляется.

Оракул фиксирует оба уровня контракта:

- registry объявляет доказанную capability;
- `AgentSession.change_model()` внутри `codex` оставляет `session_id`, не строит handoff и
  возвращает `native_session_reset=false`.

## Counter-evidence и границы

1. **Spark overflow — реальная регрессия области применимости:** с новым флагом переключение
   большой Sol-нити на Spark сохранит thread, но следующий ход fail-loud завершится
   `context_window`; прежний reset+summary мог уместиться. Автоматический размерный fallback не
   добавлялся: задача просила исправить capability одной строкой, а не вводить новый скрытый
   lossy-путь. Оператору видна точная причина.
2. Один canary не доказывает перенос каждого provider-specific item. Он доказывает identity и
   semantic recall обычного user fact.
3. Cache measurement последовательный, а не статистическая выборка. Цифры нельзя объявлять
   постоянным тарифом для любого контекста.
4. CLI API version-sensitive; результат относится к установленному Codex 0.146.0.

## Затронутые файлы и риски

- `app/runtime_registry.py` — capability `codex.resume_across_models`.
- `app/session.py` — код не меняется, но существующий predicate выбирает другой путь.
- `tests/test_runtime_registry.py`, `tests/test_session.py` — поведенческий oracle.
- `docs/tasks/243/` — probe, raw evidence, отчёт.

Главный риск — переключение в модель с меньшим окном (Spark). Оно теперь сохраняет настоящий
thread и падает громко при переполнении вместо превентивного lossy reset.

## Источники

- **[M1], tier 1 direct measurement:** `docs/tasks/243/probe-results.json`, финальные
  независимые ветки Sol→Sol, Sol→Luna и Sol→Spark одного semantic canary.
- **[M2], tier 1 direct measurement:** `docs/tasks/243/probe-spark-overflow.json`, Spark
  overflow canary.
- **[C1], tier 2 primary source:** `app/backend_codex.py` (`thread/resume`, `turn/start`, token
  accounting, price table) и `app/session.py:2837-2867` (reset predicate).
