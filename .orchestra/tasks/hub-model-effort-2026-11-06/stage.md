# Hub effort и benchmark KB — 06.11.2026

Источник задачи: прямое задание Максима в этом треде. Правки в текущем checkout,
без commit/push; существующие незакоммиченные изменения сохранить.

## Расхождения, обнаруженные при чтении

- model-map содержит 33 строки комбинаций, хотя задание называет 31; вводный итог
  «25 оценены, 8 без ответов» устарел относительно добавленной оценки Argon low.
  Сохранить всю таблицу: 26 оценённых, GPT-OSS без результата и 6 OpenCode сбоев.
- В исходной таблице Sol xhigh = 33/40, 21,1 мин; в задании 34/40, 28,6 мин.
- В исходной таблице Terra high = 27/40, 2,2 мин; в задании 28/40, 4,9 мин.
- Argon 34/40 относится к high в argon-trial-r2, не к прямому замеру medium.
- TTFT medium ~4,3 с, 2,5–3× экономия квоты, ~3 скрытых токена на видимый
  и 60-секундные header timeouts даны в задании и решении владельца 04.11;
  пять исследовательских файлов не содержат полного первичного лога этого замера.
- Таблица Sol TB4 30,8/48/51,5/54/56,1% в models-openai прямо помечена
  непроверенной: поисковая сводка не подтвердилась на самой странице OpenRouter.

Решение: не подменять исходные строки цифрами из задания; в KB явно разделить
локальные измерения, вторичный публичный ресерч и дополнения владельца.
Текущие manifest/admission и решение владельца о Hub-данных выше старых рекомендаций.

## Проверки

Ожидаются запрошенные восемь файлов pytest и check_instruction_contract.

## Ошибка подготовки и исправление

При извлечении таблицы фильтр `| ` исключил разделитель; срез [2:] затем
ошибочно пропустил первую модель. Защитный assert остановил запись KB.
Исправление: сначала отделить две строки заголовка, затем выбирать строки данных.

## Найденное падение проверки

Запрошенный pytest: 381 passed, 1 failed (11,27 с).
`tests/test_models.py::test_selectable_models_match_the_curated_catalog`: runtime
registry включает дополнительные antigravity/* и gemini-web/gemini-argon,
которых нет в frozen expected set. Эти записи не менялись в данной задаче.
Не ослаблять frozen acceptance; проверить исходный HEAD в памяти.

Команда `uv run --frozen` сначала попала в shim хаба и завершилась RC=127:
`uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
Найден собственный `.venv/bin/uv`; повторить с локальным venv первым в PATH,
не менять настройки хаба и не устанавливать пакеты.

Проверка через локальный uv запустилась: RC=1, 4 broken references в новой KB.
Исторические имена файлов бенчмарка в code spans валидатор принимал за файлы
Orchestra (`batch_index.py`, `poller.py`, `tools/tgbot/poller.py`, `write.md`).
Исправление — обозначить имена обычным текстом; контракт проверки не менять.

## Итог и проверяемые артефакты

Обе задачи реализованы локально. Без commit/push/deploy/restart. Пять исходных
изменённых tracked-файлов сохранены побайтно (`existing-changes.json` + `final-checks.log`);
существующие untracked-файлы не редактировались.

Изменены файлы задачи:

- `.orchestra/pipelines/default/pipeline.yaml` — Argon medium в двух anchors и specialist.
- `app/models.py` — `agy-argon` medium и Hub hint.
- `app/mcp_stdio.py` — две tool docstrings.
- `.orchestra/pipelines/default/prompts/modules/model-routing.md` — medium и alias-only guide.
- `tests/test_hub_effort.py` — Argon medium / Luna high для общих ролей,
  sub-orchestrator, переход Sol low/high → Argon medium, rollback при ошибке.
  Specialist проверен в его профильном тесте: роль предназначена Argon, её default medium.
- `tests/test_gemini_specialist_v1257.py` — разрешённый effort и spawn medium.
- `tests/test_models.py` — alias medium и точный effort в hint; frozen catalog test не менялся.
- `.orchestra/kb/hub-model-benchmarks.md` — 455 строк, все 33 исходные комбинации,
  отдельный trial r2, пять источников, effort/скорость/квоты/NDA и расхождения данных.
- `.orchestra/kb/README.md` — описательная индексируемая ссылка на новую тему.

Запрошенный прогон (без исключения/ослабления теста):

```sh
.venv/bin/pytest tests/test_default_pipeline.py tests/test_prompting.py tests/test_local_delegation_prompts.py tests/test_pipeline_manifest.py tests/test_hub_effort.py tests/test_gemini_specialist_v1257.py tests/test_models.py tests/test_agent_hub_routing.py -q
```

Результат: **381 passed, 1 failed, 0 skipped, 11,27 с** (`pytest.log`). Единственное
падение — `test_selectable_models_match_the_curated_catalog`, существовавшее до
задачи. Подтверждение: исходный `HEAD:app/models.py` исполнен только в памяти
отдельного процесса, исходник frozen test сопоставлен с HEAD без различий, затем
тот же test снова упал (**1 failed, 2,54 с**, `baseline-catalog.log`). Код registry
содержит дополнительные Antigravity/Gemini Web selectable IDs, не внесённые нами.
Этот соседний контракт не исправлялся и не ослаблялся.

```sh
PATH="$PWD/.venv/bin:$PATH" uv run --frozen python scripts/check_instruction_contract.py
```

Результат: **OK**, RC=0 (`instruction-contract-final.log`). PATH нужен потому, что
глобальный uv — shim, который здесь не находит собственный uv; используется уже
установленный `.venv/bin/uv`, без изменения настроек или установки зависимостей.
Предыдущие неуспешные попытки сохранены отдельно, не скрыты.

`final-checks.log`: `git diff --check` OK; исходная таблица 33/33 совпадает;
KB индексируется и попадает в `kb_index_block`; exact SELECTABLE_MODEL_SPECS IDs
в routing отсутствуют; Argon medium во всех шести ролях; alias medium;
не осталось pytest-сирот. Пропущенных обязательных проверок нет; общий pytest красный
из-за подтверждённого исходного каталожного несоответствия.

Проверенный импорт: `/mnt/claude-data/astrahancev-maxim-911aird/orchestra/app/__init__.py`.
Это изменения на диске, а не подтверждение активации в боевом процессе.
