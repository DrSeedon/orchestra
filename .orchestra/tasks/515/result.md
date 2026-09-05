# #515 — точечный перенос четырёх кусков из веток простаивающих воркеров

Ветки целиком не мержились. Каждый файл извлечён через `git show <ветка>:<путь>`.
Проверка окружения: `python -m pytest` из `/mnt/data/Projects/Python/orchestra/.venv/bin/python`,
импортированный модуль — `<worktree>/app/knowledge_pipeline.py` (системный `/usr/bin/python`
не годится: в нём нет `dotenv`, и `tests/conftest.py` падает на импорте до любого теста).

## Что взято

| Кусок | Файл | Статус |
|---|---|---|
| 1 (#489) | `app/knowledge_pipeline.py` | взят, **без потребителей** |
| 1 (#489) | `.orchestra/knowledge-pipeline.json` | взят |
| 2 (#504) | `.orchestra/kb/model-text-control-flow.md` | взят как есть |
| 4 (#424) | `.orchestra/kb/self-improvement-loop.md` | взят, схема разделов мигрирована |
| 4 (#449) | `.orchestra/kb/review-context.md` | взят, 4 факта помечены как устаревшие |

## Что НЕ взято и почему

### `app/provider_signals.py` (#504) — дубль живого кода, потребителей нет

Модуль на ветке — незавершённое извлечение из `app/session.py`/`app/backend_claude.py`.
На текущем main оба его символа не заводятся как «готовый кусок»:

- `is_safeguard_refusal` побайтно повторяет живой `app/session.py:282 _is_safeguard_refusal`
  (те же `_SAFEGUARD_MARKER`/`_SAFEGUARD_PREFIX`, `app/session.py:273,281`). Живая функция
  используется в `app/session.py:2510` и `app/session_turns.py:41,49`. Второй экземпляр
  того же правила — второй владелец одного решения.
- `legacy_subscription_limit_type` возвращает `overage|seven_day|five_hour|unknown`, тогда
  как живой классификатор `app/session.py:246 _subscription_limit_kind` возвращает
  `monthly|timed`. Это не перенос, а другой контракт.
- Его единственный вызов на ветке — `app/backend_claude.py:1271`. На текущем main этого
  вызова нет вообще: `backend_claude.py` перешёл на типизированный `RateLimitEvent`
  (`app/backend_claude.py:41,1390`), а текстовый классификатор лимитов оттуда удалён.

Взять файл = вернуть в репозиторий текстовый классификатор, от которого main уже ушёл,
без единого вызывающего. Ровно та практика, против которой написан взятый в этой же задаче
`fact:model-text-control-flow-typed-replacement`.

### `tests/test_model_text_control_flow_504.py` (#504) — 4 из 5 assert'ов красные на main

`python -m pytest tests/test_model_text_control_flow_504.py -q` → `4 failed, 1 passed`.
Это RED-оракулы под неснятую починку #504:

- 3× T2 — `app/mcp_stdio.py:3633 _CODEX_EXECUTION_FAILURE_JSONL_CHECK` до сих пор грепает
  прозу модели в `item.agent_message.text` и объявляет её отказом исполнения. Тест на
  успешном `command_execution(exit_code=0)` с процитированной прозой ждёт `rc=1`, получает `0`.
- 1× T4 — классификаторы текста модели живы: `app/tool_call_guard.py`
  (`looks_like_unexecuted_tool_call`, `mark_unexecuted_tool_call`), `app/tg_bridge.py`
  (`mark_unexecuted_tool_call`), `app/static/js/chat.js` (`_looksLikeUnexecutedToolCall`,
  `_markUnexecutedToolCall`).

Красный тест в `tests/` красит весь прогон для всех. Файл сохранён вне сборки pytest как
`.orchestra/tasks/515/test_model_text_control_flow_504.py.red` (`testpaths = ["tests"]`,
`pyproject.toml:70` — не собирается; проверено `pytest --collect-only`: 0 совпадений).
Он остаётся исполняемым описанием дефекта и станет зелёным, когда починку #504 сделают.

### Пункт 3 (#490, три модуля промпта) — не взят, развилка вынесена

Подробности — раздел «Развилка» ниже.

## Изменения внутри взятых файлов

Файлы #424 и #449 писались по прежней схеме KB и не проходят действующий
`scripts/check_kb_contract.py`. В main ни один из 43 существующих топиков не использует
русские заголовки разделов и ни одна строка факта не обходится без `search:`-якорей —
`review-context.md` был единственным файлом с 7 такими строками.

- `## Установлено|Отвергнуто|Пробелы|Источники` → `## Established|Rejected|Gaps|Sources`,
  `· искать:` → `· search:` (переименования из `SCHEMA_RENAMES`, `scripts/check_kb_contract.py:27-36`).
- Записи в `Gaps` у #424 несли префикс `` - `fact:<key>` — ``, которого в действующей схеме
  в этом разделе быть не должно; префикс снят, ключ сохранён первым `search:`-якорем.
- В `review-context.md` добавлены `search:`-якоря — взяты дословно из символов самого факта.

Результат: `python scripts/check_kb_contract.py --root .orchestra/kb --diff <kb-only.patch>`
→ `KB contract OK`.

## Противоречия с текущим кодом (пункт 4)

Противоречий с уже принятыми фактами KB нет: тем `review-context` и `self-improvement-loop`
в main не существовало, а `.orchestra/kb/auto-work.md` (#422) описывает реактивный контур
`📝 RULE` и дополняет #424, а не спорит с ним. Спорят с текущим **кодом** четыре записи #449,
и молча их выбрасывать нельзя — это снятый срез, по которому потом восстанавливают
происхождение решения. Помечены прямо в тексте по конвенции KB:

- `fact:review-context-current-owner` → **SUPERSEDED**. Калибровка теперь грузится из
  источника, принадлежащего репозиторию: `_load_review_project_context`,
  `_validate_project_context`, `_project_context_error_message`
  (`app/mcp_stdio.py:3853-3971,4452-4471`).
- `fact:review-context-no-structured-source` → **SUPERSEDED**. `CLAUDE.md`/`AGENTS.md` теперь
  16061 байт каждый, не 181149; структурированный источник существует.
- `fact:review-context-kb-validator-path-debt` → **RESOLVED**, причём наоборот: валидатор
  теперь *требует* `.orchestra/kb` и отвергает всё вне его (`scripts/check_kb_contract.py:122,162`).
- Gap про missing-file → **CLOSED решением, не ранжированием**: `codex_review` отказывает до
  старта модели и возвращает путь владельца плюс шаблон (`app/mcp_stdio.py:3869-3885,4452-4461`).

Проверено и подтвердилось на текущем main (взято как есть): `fact:review-context-no-extra-tool`
(отдельного MCP-тула контекста нет), `fact:self-improvement-dormant-rule-registry`
(`improvement_rules` — только слой данных, `app/db.py:820,3796-3828`, потребителя нет),
`fact:self-improvement-existing-archive-seam` (`commit_session_archive` — единственное
упоминание `app/manager.py:1255`, вызывающих нет).

Легаси-пути `docs/tasks/…` внутри #424 не переписаны: такие ссылки уже есть в 8 топиках main
(`token-efficiency.md` — 13 штук), это принятая практика для датированных фактов.

## Что осталось незавершённым в перенесённом

`app/knowledge_pipeline.py` попадает в main **без единого вызывающего**. Его точка включения на
ветке — `app/tm.py:1451-1458`: при `outcome == "complete"` статус закрытия становится
`knowledge_pending` вместо `done`, если найден маркер. Эту правку я не тащил — `app/tm.py` на
ветке `task-489/knowledge-loop` отстал от main. Следствия:

- `.orchestra/knowledge-pipeline.json` (`enabled: true`) сейчас читает только
  `knowledge_pipeline_configured()`, которую никто не зовёт. Инертно, но это взведённый маркер:
  как только появится вызов из `tm.py`, задачи этого проекта начнут закрываться в
  `knowledge_pending`. Проверено на месте: `knowledge_pipeline_configured(<worktree>)` → `True`.
- Модуль не покрыт тестами — на ветке `task-489/knowledge-loop` тестов для него нет вообще
  (`git grep -l knowledge_pipeline task-489/knowledge-loop -- tests/` → пусто).

Дизайн, который он реализует, в main уже принят: `.orchestra/kb/knowledge-pipeline.md`,
`fact:task-knowledge-pending-lifecycle-decision`. Проводка — отдельная задача.

## Развилка, вынесенная наверх: пункт 3 (#490)

Три модуля — это не добавление, а **перевод и переписывание блоков, которые уже собираются
в промпт каждого агента каждого проекта**.

- `.orchestra/pipelines/default/prompts/base.md:68-98` уже содержит инлайновый
  `<communication-style>`, строки `100-126` — `<user-values>`. `base.md` попадает в каждый
  промпт; модули подключаются отдельно, по списку `modules:` роли.
- Модули с ветки — английский пересказ этих же блоков, не побайтная копия: `user-values.md`
  добавляет правила про рестарт, `Same goal, or a new one?`, «новый путь полностью заменяет
  старый» и «критерий, придуманный агентом»; `communication-style.md` переносит в себя
  языковое правило из `<rules priority="standard">`.
- На ветке это связная правка: `base.md` там теряет 84 строки (`1 insertion, 84 deletions`),
  а `pipeline.yaml` дописывает `knowledge-and-context, communication-style, user-values` в
  `modules:` всех пяти ролей.

Отсюда ровно два исхода, и оба менять нельзя без владельца:

1. Взять только три файла модулей — их никто не грузит, три мёртвых файла.
2. Взять их с проводкой — каждый агент получает `communication-style` и `user-values`
   **дважды, в двух разошедшихся редакциях**, либо надо вырезать блоки из `base.md`, то есть
   переписать базовый промпт всех проектов.

Дополнительно: ветка `task-490/prompt-engineer` откатывает роли к более старой редакции.
Её `roles/worker.md` возвращает жёсткие формулировки, от которых main уже ушёл (например
«Never author the acceptance test» и запрет трогать любые тесты вместо действующего правила
про замороженные приёмочные тесты). Мерж её ролевых файлов = регресс правил.

`tests/test_prompt_contract_490.py` (14478 байт) не переносился: он проверяет ту сборку
промпта, которой на main нет.

## Побочный эффект переноса

Три новых топика KB добавлены в `.orchestra/kb/README.md`, оглавление в корневых файлах
пересобрано `python scripts/check_instruction_contract.py --sync` (руками не правилось).
Корневые файлы выросли до **16370 байт** при потолке 16 KiB = 16384. Осталось 14 байт.
Следующий топик KB не влезет — оглавление придётся сокращать или менять его форму.

## Проверки

| Команда | Результат |
|---|---|
| `python -m pytest tests/test_instruction_contract.py tests/test_kb_markdown_contract.py tests/test_knowledge_instruction_source.py tests/test_default_pipeline.py tests/test_workspace.py -q` | `264 passed` |
| `python scripts/check_instruction_contract.py --sync` | `Instruction contract OK` |
| `python scripts/check_kb_contract.py --root .orchestra/kb --diff <kb-only.patch>` | `KB contract OK` |
| `python -c "import app.knowledge_pipeline"` | ok, `<worktree>/app/knowledge_pipeline.py` |
| `python -m pytest --collect-only -q` | `4060/4064 collected`, ошибок сбора нет, `.red`-файл не собран |

Полный прогон сьюта не запускался: глобальный тест-лок не брался, продовый код не менялся
(единственный новый модуль в `app/` не имеет вызывающих).

## Маршрут ревью

`codex_review(mode="implementation", model="gpt5.6luna")` отказал:
`weekly_quota_blocked: Codex quota is 99% — utilization 99% is at or above the hard stop 99%`.
По правилу скилла — `Review: none — Codex unavailable`; замена ревьюеру не поднималась.
Вместо ревью — самопроверка выше и просмотр диффа постановщиком.
