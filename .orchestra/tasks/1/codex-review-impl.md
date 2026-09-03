# #1 — Codex review: НЕ СОСТОЯЛСЯ (вердикта нет)

## Попытка 1 — 13.08.2026

Вызов: `codex_review(mode="exec", target="/tmp/task1-model-registry.diff", output="docs/tasks/1/codex-review-impl.md")`

Ответ платформы, дословно:

```
weekly_quota_blocked: New Codex worker turn blocked: Codex weekly quota is 97%
(threshold 95%). Available provider: Claude, Codex Spark. Stop/model change remain available.
```

Классификация по `skills/codex-debate.md`: **весь вывод — отказ ИНСТРУМЕНТА, ревьюер не ответил
вовсе.** Это несостоявшаяся попытка, раунд не потрачен. Вердикта нет — и «Codex approved» здесь
писать нельзя.

Постановка задачи это предусматривала дословно: «Codex был на 97% квоты: если недоступен —
напиши это прямо в отчёте, вердикт не выдумывай».

Spark формально доступен, но на него финальные ревью не роутятся: в `CLAUDE.md` зафиксирован
замер — на A/B Spark пропустил реальный double-count, который поймал Sol. Дешёвая модель на
финальном ревью общего рантайма даёт ложное «одобрено», что хуже отсутствия ревью.

**Статус: ревью не проведено, 1 несостоявшаяся попытка из 3.** Вместо него ниже — adversarial
self-review, предписанный скиллом на этот случай.

---

## Adversarial self-review (замена, не эквивалент)

Проверял ровно те пять мест, которые вынес бы на ревью. Каждое — прогоном, не чтением.

### 1. Чтение производного словаря на import-time до заполнения

Риск настоящий: `_REVIEWED_PROXY_ROUTES` (строка ~283) раньше строился comprehension'ом из
`BACKENDS`/`MODEL_PROVIDERS`, а те теперь пусты до `_seed_model_specs()` на строке ~380. Молча
получился бы dict без единой hardcoded-модели.

Поймано при написании, исправлено: источник — `SELECTABLE_MODEL_SPECS`. Контроль:

```
grep -n "MODELS\[\|CONTEXT_LIMITS\[\|BACKENDS\[\|MODEL_PROVIDERS\[\|TOKEN_PRICES\[\|for .* in MODELS\b" app/models.py
306-311  → внутри _apply_derived_views (запись, вызывается сидированием)
601, 660 → внутри функций, исполняются в рантайме, не на импорте
```

Других чтений на import-time нет.

### 2. Словари обязаны остаться ТЕМИ ЖЕ объектами

`app/manager.py:37` и `app/backend_claude.py:1085` импортируют `CONTEXT_LIMITS`/`TOKEN_PRICES`
по имени; `fetch_models_from_proxy()` мутирует их на лету. Поэтому нельзя пересоздавать —
только наполнять существующие. В коде так и сделано: `MODELS: dict[str,str] = {}` + заполнение
через `_apply_derived_views`, ни одного `MODELS = {...}` после объявления.

### 3. Полнота очистки (enterprise-путь)

`_clear_selectable_models()` дополнен `MODEL_PROVIDERS.clear()`. Прогон:

```
M._clear_selectable_models()
{'MODELS': 0, 'CONTEXT_LIMITS': 0, 'BACKENDS': 0, 'MODEL_PROVIDERS': 0,
 'TOKEN_PRICES': 0, 'MODEL_SPECS': 0, 'ALIASES': 0}
```

`unregister_model()` тоже дополнен `MODEL_PROVIDERS.pop`. До правки он его не трогал — то есть
запись пережила бы удаление модели.

### 4. Семантика цен

```
price_input=0.0   price_output=0.0   -> в TOKEN_PRICES: True
price_input=None  price_output=5.0   -> в TOKEN_PRICES: True
price_input=5.0   price_output=None  -> в TOKEN_PRICES: True
price_input=None  price_output=None  -> в TOKEN_PRICES: False
```

Верно для нашего контракта: `0.0` — это явная нулевая цена (модель бесплатна), а «цен нет
вовсе» = `None/None` → модель не попадает в словарь, и `routes/system.py:_cost_cached_for()`
не переоценивает её. Codex/Grok именно так и остаются вне `TOKEN_PRICES` — проверено тестом
`test_derived_views_carry_exactly_the_declared_specs`.

### 5. `context_length` для `claude-opus-4-6`

Постановка просила перепроверить подозрительное `1000000`. Независимый источник в репозитории —
`app/backend_opencode.py:60`: `"claude-opus-4-6": 200000`. Безсуффиксный id получил 200000,
`[1m]`-вариант сохранил 1000000. Это согласуется и с соседним `claude-haiku-4-5` (200000), и с
общим правилом проекта «`[1m]` — это и есть маркер расширенного окна».

### Что self-review НЕ заменяет

Одна модель, написавшая правку и её же проверившая, — петля усиления, а не независимая
проверка (`CLAUDE.md`, раздел про Codex/Sol). Слепое пятно у меня и у моей проверки общее.
Реальное кросс-рантаймное ревью на этот дифф стоит провести, когда отпустит квота Codex.
