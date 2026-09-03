# #314 Фаза 2 — план: дефицит деградирует, процент отказывает

Рамка подтверждена оркестратором 19.08: **дефицит рабочих часов → `reserve_only` + увод новых
воркеров на Luna; отказ остаётся за процентом.** Обоснование — цена ложного срабатывания
становится «работали на Luna» вместо «работать нечем», и недоказанность порога (§5 research)
перестаёт блокировать выкат.

Основание: `docs/tasks/314/research.md`. Числа 34 / 34 и «9 окон» держатся до вердикта
`rev314-opus` как предложение — **см. §4, тикеты от них не зависят структурно.**

---

## 1. Главное решение: НЕ писать второй раз то, что уже написано

Инвентарь того, что существует и отревьюено (проверено чтением кода, не по памяти):

| кусок | где | состояние |
|---|---|---|
| расчёт `deficit / pace / runway_hours` | `app/quota_runway.py` | готов, покрыт тестами |
| переякоривание базы окна | `app/db.py:3387` | готово |
| вердикт полосы Claude по дефициту + латч | `app/runtime_router.py:878-896` | **готов, в допуск не сшит** |
| храповик `reserve_only` по `window_id` | таблица `runtime_routing_latches` (`app/db.py:1236`), неизменяемая, с триггерами | готова |
| журнал решений | таблица `runtime_routing_decisions` (`app/db.py:1217`) | готова |
| прецедент деградации «Sol → Luna по прижатому runway» | `app/quota_controller.py:182` `route_codex_model_for_runway`, вызывается `app/manager.py:726` | работает, ровно нужная форма |
| единственный производитель `QuotaDecision` | `app/quota_gate.py:395` `get_worker_admission` | все четыре точки допуска идут через него |

**Отсюда архитектурное решение: `get_worker_admission` ПОТРЕБЛЯЕТ вердикт `runtime_router`, а не
считает дефицит заново.** Вторая реализация того же правила — прямое нарушение «одна мысль =
один owner» из `CLAUDE.md`, и расходиться копии начнут на первом же изменении порога.

Симметрично — про точки допуска: их четыре (`manager.py:762`, `session.py:1288,2319,2526`), и
перечислять их в правке нельзя (`CLAUDE.md`: список приезжает неполным). Врезка — в
**`get_worker_admission`**, через который проходят все четыре.

### Что НЕ делаем

- **Не трогаем `state` у `QuotaDecision`.** `allowed` = `state in {available, not_applicable}`
  (`app/quota_gate.py:59`), поэтому новое значение `state` немедленно стало бы ОТКАЗОМ в
  `require_worker_admission` — ровно то, что рамка запрещает. Деградация едет ортогональным
  полем; старый потребитель, который его не читает, ведёт себя ровно как сегодня.
- **Не переключаем модель у ИДУЩИХ сессий.** Деградация применяется только при спавне нового
  воркера. Смена бэкенда на живой сессии рвёт нативный тред (`CLAUDE.md`, политика пулов).
- **Не трогаем числа процента** (`claude 90`) и оркестраторов (они гейт не проходят вовсе).

---

## 2. Тикеты

### T1 — `QuotaDecision` несёт причину и runway, ничего не решая
- **Files:** `app/quota_gate.py` (dataclass + `worker_readiness_envelope`)
- **Что:** добавить в `QuotaDecision` поля `binding_constraint: str = "none"`
  (`none | static_pct | runway_deficit | blind_no_pace | runway_unavailable`) и
  `runway: dict | None = None` (`deficit, pace, runway_hours, work_hours_left, work_used,
  window_id, blind_until`). `evaluate_worker_admission` при отказе по проценту проставляет
  `static_pct`. Значения `runway` пока всегда `None` — источник появится в T3.
- **Test:** `docs/tasks/314/oracles/test_t1_binding_constraint.py::test_static_denial_names_percent`
  + `::test_envelope_carries_binding_constraint` — committed RED
- **AC:** команда зелёная; `worker_readiness_envelope` отдаёт `binding_constraint`;
  существующие поля envelope не переименованы (`wire_version` не меняется — новые поля
  аддитивны).
- **blocked-by:** none

### T2 — пороги дефицита живут в горячей политике, а не в константах
- **Files:** `app/db.py` (схема `quota_controller_policy` + сид + миграция), `app/quota_gate.py`
- **Что:** две nullable-колонки на существующую таблицу: `deficit_hours REAL`,
  `min_work_hours REAL`. Существующий `CHECK (threshold >= 0 AND threshold <= 100)` не трогаем —
  он про процент и остаётся инвариантом. Сид для полосы `claude`. Чтение — на каждое решение,
  без кеша в памяти (иначе п.«обратимость без рестарта» не выполняется).
- **⚠ Ловушка миграции, найдена чтением кода.** Дрейф-проверка `app/db.py:428-457` при
  несовпадении схемы чинит таблицу через `DROP TABLE` → `CREATE` → `INSERT`, причём и SELECT, и
  INSERT перечисляют **шесть колонок дословно** (`lane, threshold, revision, source, reason,
  updated_at`). Обновить `_QUOTA_POLICY_TABLE_SQL` и забыть эти два списка → операторские
  значения `deficit_hours` / `min_work_hours` молча обнулятся при следующем же дрейфе, а
  деградация тихо выключится. Отказ бесшумный, поэтому выносится в AC отдельной строкой.
- **Test:** `docs/tasks/314/oracles/test_t2_policy_hot.py::test_deficit_policy_read_is_not_cached`
  — меняет строку политики между двумя вызовами в одном процессе и требует разного результата;
  `::test_drift_repair_preserves_deficit_columns` — записать значения, искусственно вызвать
  дрейф, проверить что значения на месте; `::test_percent_check_constraint_survives_migration`
  — committed RED
- **AC:** команды зелёные; `sqlite3 .schema quota_controller_policy` содержит обе колонки и
  прежний CHECK дословно; **мутация «убрать `deficit_hours` из INSERT-списка дрейф-починки»
  краснит `test_drift_repair_preserves_deficit_columns`** (иначе тест не про эту ловушку).
- **blocked-by:** none

### T3 — `get_worker_admission` потребляет вердикт router'а (единственная врезка)
- **Files:** `app/quota_gate.py:395`, `app/runtime_router.py` (экспорт вердикта для полосы Claude)
- **Что:** `get_worker_admission` спрашивает у router'а candidate для полосы Claude и переносит
  в `QuotaDecision`: `reserve_only` → `binding_constraint="runway_deficit"` + `runway={...}`;
  `claude_weekly_runway_no_data` → `blind_no_pace` с `blind_until`. **`state` при этом не
  меняется никогда.** Отказ router'а/телеметрии → `runway_unavailable`, поведение = сегодняшнее
  (fail-open в сторону текущей статики, как `manager.py:748-757` уже делает).
- **Test:** `docs/tasks/314/oracles/test_t3_no_refusal.py::test_deficit_over_threshold_never_refuses`
  — дефицит выше порога при проценте ниже предела → `decision.allowed is True` и
  `require_worker_admission` НЕ поднимает; `::test_percent_still_refuses_under_deficit` — committed RED
- **AC:** обе команды зелёные; **`grep -c "require_worker_admission" app/quota_gate.py` не
  изменился** (врезка не добавила новых точек отказа); мутация «вернуть `state="blocked"` на
  `reserve_only`» краснит `test_deficit_over_threshold_never_refuses`.
- **blocked-by:** T1, T2

### T4 — деградация: новый воркер на Claude уходит на Luna
- **Files:** `app/manager.py` (рядом с существующим `route_codex_model_for_runway`, :724-726)
- **Что:** по тому же образцу — `route_claude_model_for_runway(model, decision)`: при
  `binding_constraint == "runway_deficit"` новый воркер, запрошенный на Claude-модель, получает
  Luna. Оркестраторы (`is_orch`) исключены. Идущие сессии не трогаются.
- **Test:** `docs/tasks/314/oracles/test_t4_degrade_routing.py::test_worker_spawn_degrades_to_luna`
  + `::test_orchestrator_spawn_keeps_claude` — committed RED
- **AC:** команды зелёные; мутация «снять проверку `is_orch`» краснит второй тест.
- **blocked-by:** T3

### T5 — храповик: не мигать вокруг порога
- **Files:** `app/quota_gate.py` или `app/runtime_router.py` (переиспользовать
  `runtime_routing_latches`, provider=`anthropic`)
- **Что:** сработало в окне `window_id` → держим деградацию до смены `window_id`. Таблица
  неизменяемая (триггеры уже есть), снятие храповика — только сменой окна.
- **Обоснование числами:** в ленте 12.07 (research §4) дефицит колеблется 13.8…15.6 вокруг
  порога с шагом 5 минут; без храповика воркеры мигали бы Claude/Luna каждые пять минут.
- **Test:** `docs/tasks/314/oracles/test_t5_latch.py::test_latch_holds_after_deficit_falls`
  + `::test_new_window_clears_latch` — committed RED
- **AC:** команды зелёные; попытка UPDATE/DELETE строки латча поднимает
  `runtime routing latch is immutable`.
- **blocked-by:** T3

### T6 — журнал срабатываний, чтобы через 9 окон было что посчитать
- **Files:** `app/db.py` (переиспользовать `runtime_routing_decisions`), `app/quota_gate.py`
- **Что:** каждое решение с `binding_constraint != "none"` пишет строку: `window_id`, дефицит,
  темп, `work_used`, порог и его `revision`, исход. Без этого §5.3 research (посчитать долю
  ложных за 9 окон) невыполним в принципе.
- **Test:** `docs/tasks/314/oracles/test_t6_decision_log.py::test_degrade_writes_decision_row`
  + `::test_row_records_threshold_revision` — committed RED
- **AC:** команды зелёные; в строке присутствует `revision` политики (иначе задним числом не
  понять, каким порогом решали).
- **blocked-by:** T3

### T7 — панель различает, что решило
- **Files:** `app/routes/system.py:1293,1318`, `app/static/js/analytics.js`
- **Что:** показывать ОБЕ величины всегда, подсвечивая связывающую: «Claude 78 % (предел 90) ·
  дефицит +41 ч (порог 34) → **закрыл дефицит**». Отдельная строка для `blind_no_pace` с
  `blind_until` — иначе тишина гейта читается оператором как «всё хорошо», а это ровно тот
  класс проверки, что даёт одинаковый вывод при успехе и при провале (`CLAUDE.md`).
- **Test:** `tests/test_t314_runway_panel_browser.py::test_panel_names_binding_constraint`
  (Playwright, модульная фикстура — `CLAUDE.md`, #318) — committed RED
- **AC:** команда зелёная; в DOM присутствует узел с `binding_constraint`; ассерт на СВОЙ узел,
  не на весь контейнер (`CLAUDE.md`, #270).
- **blocked-by:** T3
- **Замечание:** правку строить в `analytics.js`, не в шаблоне — иначе её нельзя ни проверить
  подменой, ни доставить без рестарта (`CLAUDE.md`).

### T8 — обратимость без рестарта
- **Files:** `app/quota_gate.py`
- **Что:** снятие деградации = запись в политику (T2), действует со следующего решения.
  Существующий `ORCHESTRA_ADAPTIVE_ENFORCEMENT=0` остаётся аварийным рубильником, но он
  env-переменная и требует рестарта — **на него в этой рамке не опираемся.**
- **Test:** `docs/tasks/314/oracles/test_t8_reversible.py::test_disable_takes_effect_without_restart`
  — committed RED
- **AC:** команда зелёная; в одном процессе, без переимпорта модуля, после записи политики
  следующее решение возвращает `binding_constraint="none"`.
- **blocked-by:** T2, T3

---

## 3. Порядок и риски

Порядок: T1, T2 → T3 → {T4, T5, T6, T7, T8}. После T3 пять тикетов независимы по файлам и
могут идти параллельно, кроме T4/T5 — оба трогают решение о деградации, их сериализовать.

| риск | смягчение |
|---|---|
| **`get_worker_admission` становится тяжелее** (поход в router + БД на каждое решение) | замерить до/после; при регрессии — кешировать вердикт на `QUOTA_OBSERVATION_MAX_AGE=300 с`, но НЕ политику (T8) |
| **fail-open расширяется** — новый источник (router) может упасть | `runway_unavailable` = поведение ровно сегодняшнее; тест на это в T3 |
| **`runtime_router` не рассчитан на вызов из горячего пути допуска** | проверить при реализации; не подойдёт — вынести чистую функцию вердикта, но по-прежнему ОДНУ |
| миграция `quota_controller_policy` при живом сервере | схема читается через `_quota_controller_expected_sql` с дрейф-проверкой (`app/db.py:432-446`) — сверить, что аддитивные колонки её не роняют |
| Playwright-тест T7 ломает соседние async-тесты | модульные фикстуры уже в `tests/conftest.py` (#318) |

---

## 4. Почему тикеты переживут вердикт ревьюера

Оркестратор держит §3.2 (порог ≈34) и §5.3 (число 9) предложением до `rev314-opus`. Тикеты
построены так, что вердикт меняет **значения, а не структуру**:

- порог и окно созревания — строки в политике (T2), не константы в коде;
- оракулы параметризованы порогом и НЕ содержат чисел 34 / 34 / 9;
- если ревьюер снимет дефицит как решающую величину целиком — T1, T6, T7, T8 остаются в силе
  (причина отказа, журнал, панель, обратимость полезны и при чистом проценте), падают только
  T3–T5.

**Поэтому оракулы не заморожены этим коммитом.** Замораживать RED до вердикта — значит с
заметной вероятностью перезамораживать их следом, а `CLAUDE.md` требует после правки оракула
считать excluded всё, что от старого коммита реплеилось. Спецификации оракулов выше даны
дословно; первое действие после вердикта — закоммитить их красными и предъявить вывод.

Это осознанное отступление от обычного порядка гейта (план кончается красным тестом), и я его
называю, а не обхожу молча.

---

## 5. Замороженные RED-оракулы (T1, T6, T7, T8) — коммит `91e6cf47`

Заморожены по решению оркестратора 19.08: эти четыре тикета верны при любом вердикте
`rev314-opus` (причина отказа, журнал, панель и обратимость полезны и при чистом проценте).
T3–T5 ждут вердикта.

Команда и фактический вывод на момент заморозки:

```
uv run python -m pytest -q docs/tasks/314/oracles/test_t1_binding_constraint.py
  4 failed, 1 passed
  test_static_denial_names_percent
    assert getattr(decision, "binding_constraint", None) == "static_pct"
    AssertionError: assert None == 'static_pct'
  (1 passed = test_envelope_stays_backward_compatible — это ГАРД контракта,
   он обязан быть зелёным и до, и после реализации; поведением тикета не является)

uv run python -m pytest -q docs/tasks/314/oracles/test_t6_decision_log.py
  4 failed
  AssertionError: app.db.record_runway_decision не существует

uv run python -m pytest -q docs/tasks/314/oracles/test_t8_reversible.py
  3 failed
  AssertionError: app.quota_gate.current_runway_deficit не существует

uv run python -m pytest -q tests/test_t314_runway_panel_browser.py
  4 failed
  test_blindness_is_visible_not_silent
    assert blind.count() == 1, "слепота гейта не показана отдельным узлом"
    AssertionError: assert 0 == 1
```

Проверено отдельно, что браузерный файл не отравляет соседние async-тесты (#318):
`pytest -q --timeout=120 tests/test_t314_runway_panel_browser.py tests/test_quota_runway.py
tests/test_quota_runway_baseline.py` → `4 failed, 69 passed` — падают ровно свои четыре.

Красное здесь означает отсутствующее поведение, а не поломку: все файлы импортируются, падения
— на ассертах. Отсутствующие символы проверяются через `getattr(...)`, а не импортом на верхнем
уровне, — иначе это была бы ошибка сборки, которая красным не считается.

**Контракт, который заморозка фиксирует** (имена — часть оракула, менять их = перезамораживать):
`QuotaDecision.binding_constraint` ∈ `none | static_pct | runway_deficit | blind_no_pace |
runway_unavailable`; `QuotaDecision.runway`; `app.db.record_runway_decision(...)` /
`runway_decision_rows(limit)` / `set_runway_policy(...)` / `quota_policy_audit_rows(limit)`;
`app.quota_gate.current_runway_deficit(...)`; DOM-атрибуты `data-binding-constraint` и
`data-runway-blind`.

---

## 6. Обновление после вердикта `rev314-opus` (BLOCKED) — 19.08

**Рамка уточнена оркестратором: сначала shadow с журналом, порог решает потом.** Пара
(M=34, T=34) снята; числа в тикетах ниже читать как «параметр политики», а не как значения.

Статус тикетов:

| тикет | статус |
|---|---|
| T1, T6, T7, T8 | **реализованы**, `354c9a93`; оракулы зелёные, мутации краснят |
| T2 | реализован в объёме, нужном T8 (колонки политики + `set_runway_policy` + перенос при дрейфе) |
| T3, T4, T5 | **держатся**: это действующая половина, и порог для неё не определён |

Что это значит на практике: `binding_constraint` уже принимает значение `runway_deficit`, но
**никто на него не действует**. Ни отказа, ни увода на Luna — только запись в журнал и строка в
панели. Деградация к тому же выключена по умолчанию (`deficit_hours = NULL`).

Ловушка миграции из T2 подтвердилась и оказалась ШИРЕ, чем описано выше: перечень колонок
`quota_controller_policy` живёт в ТРЁХ местах — `_QUOTA_POLICY_TABLE_SQL`, список переносимых
колонок в дрейф-починке и `_QUOTA_CONTROLLER_TABLE_COLUMNS`. Третий обнаружился только прогоном
(`incompatible quota controller table`) и, в отличие от второго, падает громко.

Перезаморозки оракулов (обе про имена, не про поведение) — `docs/tasks/314/report.md` §5.
