# V-577 — снятие повторов и починка фактов в `.orchestra/pipelines/default/prompts/`

Все `file:line` «до» — по коммиту `a3d8b8f4` (HEAD на начало работы).
Проверочные скрипты и логи лежат рядом: `verify_sections.py`, `verify.log`, `dupscan.py`,
`measure_prompts.py`, `tagscan.py`, `tests.log`, `tests2.log`.

**Граница #V-576 соблюдена, проверено машинно, а не обещанием.** `roles/orchestrator.md`
в диффе отсутствует целиком (`git diff --stat -- …/roles/orchestrator.md` пуст), и
`git diff -U0 | rg 'project_goal|project_wait|portfolio|user-attention'` не даёт ни одного
совпадения. Столкновения при мерже с #V-576 в этих местах быть не может.

## 1. Размеры до и после, в байтах

Каталог `.orchestra/pipelines/default/prompts/` (все файлы, включая `skills/`):

| | до | после | Δ |
|---|--:|--:|--:|
| каталог целиком | 147 130 | 146 585 | −545 (−0.37%) |

Собранный промпт роли — `app.pipeline.build_system_prompt(pipeline, role)`, то есть
`base.md` + тело роли + инлайн модулей манифеста. Индекс KB и каталог ролей добавляются
в `ROLE_SYSTEM_PROMPT` и от правок не зависят, поэтому в замер не входят.

| роль | до | после | Δ |
|---|--:|--:|--:|
| orchestrator | 73 530 | 73 371 | −159 (−0.22%) |
| sub-orchestrator | 66 290 | 66 033 | −257 (−0.39%) |
| worker | 33 293 | 32 964 | −329 (−0.99%) |
| full-cycle | 58 423 | 58 276 | −147 (−0.25%) |
| reducer | 22 512 | 22 512 | 0 |

Поштучно по изменённым файлам: `modules/background-jobs.md` 2319 → 2272,
`modules/orchestration.md` 19 316 → 19 204, `roles/full-cycle.md` 4021 → 3874,
`roles/sub-orchestrator.md` 985 → 887, `roles/worker.md` 3601 → 3272,
`skills/vps-deploy.md` 2267 → 2455 (единственный рост — исправление факта, п. 4).

Экономия маленькая, и это сам по себе результат: каталог НЕ был наполовину дублями.
Ниже — что оказалось настоящим повтором, а что нет.

## 2. Снятые дубли: где было и кто остался владельцем

Дублем считается только то, что попадает в ОДИН собранный промпт дважды. Совпадения
между `roles/worker.md` и `roles/full-cycle.md` (или между двумя ролями оркестратора)
дублями не являются: эти файлы никогда не встречаются в одном промпте.

| правило | места «до» | владелец после |
|---|---|---|
| `owned_dirs` — не запрет на правку | `modules/git-workflow.md:12-14`, `modules/orchestration.md:118`, `roles/sub-orchestrator.md:8-9` | `modules/git-workflow.md:12-14` |
| «Silence is not consent» | `modules/orchestration.md:37`, `modules/user-values.md:11` | `modules/user-values.md:11` |
| «commit before DONE, git status чистый» | `modules/git-workflow.md:23`, `roles/worker.md:12` (дословно), `roles/worker.md:39` (чек-лист) | `modules/git-workflow.md:23` |
| «отчитываться через `mcp__orchestra__send_message`, не built-in» | `base.md:4`, `base.md:45`, `modules/report-format.md:8`, `roles/worker.md:18` | `base.md:45` + адресат в `modules/report-format.md:8` |
| «спрашивать только про scope/authority/cost/контракт» | `modules/code-quality.md:5`, `roles/worker.md:24-25` | `modules/code-quality.md:4-6` |
| «зелёный прогон не закрывает невоспроизведённый дефект» | `modules/code-quality.md:33-35`, `roles/worker.md:16-17`, `roles/full-cycle.md:20` | `modules/code-quality.md:33-35` |
| «test-first, когда контракт известен» | `modules/code-quality.md:34`, `roles/full-cycle.md:33` | `modules/code-quality.md:34` |
| тег `<background-jobs>` открывался дважды | `base.md:30-38` и `modules/background-jobs.md:1` | тег только у `base.md`; модуль стал секцией без обёртки |

Подробности по двум неочевидным пунктам.

**`<background-jobs>`.** Содержательного дубля тут не было: модуль первой же строкой
отдаёт владение (`base.md` already carries the "never sleep or poll" rule) и добавляет три
своих пункта. Дефект был структурный — в промпте оркестратора тег `<background-jobs>`
открывался дважды, и второй блок читается как переопределение первого. Обёртка снята с
модуля; прецедент в том же каталоге — `modules/dynamic-workflows.md`, у которого тега нет
вовсе. Заодно исправлен заголовок: «the two things the tool description does not tell you»
при трёх пунктах.

Отвергнутый вариант: перенести общий блок из `base.md` в модуль и раздать модуль всем
ролям. Он даёт один файл-владелец, но `modules/background-jobs.md` сегодня доезжает только
до оркестраторов, поэтому либо reducer и воркеры получили бы три новых оркестраторских
правила, либо пришлось бы резать модуль надвое. И то и другое — изменение состава правил,
чего задача запрещает.

**`roles/worker.md`.** Из блока критических правил убраны два пункта, дословно (или почти)
повторяющие `modules/git-workflow.md:23` и `base.md:45`. Пункт чек-листа
`<before-done>` «All changes committed (`git status` must be clean)» оставлен: чек-лист
ссылается на правило, а не заводит второе. Сам критерий «Check actual requirements, not
merely a green status» сохранён — `modules/code-quality.md` покрывает только зелёный прогон
поверх НЕВОСПРОИЗВЕДЁННОГО дефекта, а это более широкое требование.

## 3. Чего НЕ снял и почему

**«Не начинать реализацию без слова владельца» остаётся в трёх местах — и это не дубль.**
`modules/user-values.md:8-27` — устав владельца, доезжает до всех пяти ролей.
`modules/orchestration.md` `<approval-gate>` — операционный классификатор A/B/C, только
оркестраторам. `modules/task-management.md:24-25` — применение к `task_create`, и это
единственный носитель правила для роли `full-cycle`: в её `modules` нет `orchestration`
(`pipeline.yaml`, `roles.full-cycle.modules`). Удаление любого из трёх оставляет какую-то
роль без правила. Снята только одна дословно совпадающая фраза — «Silence is not consent».

**`modules/model-routing.md` не «наполовину мёртвые ветки».** Sol, Terra и Fable —
живые записи реестра: `app/models.py:95` (`gpt-5.6-sol`), `:103` (`gpt-5.6-terra`),
`:56` (`claude-fable-5-1[1m]`), и у всех трёх есть алиасы (`app/models.py:156-186`),
в том числе `"codex": "gpt-5.6-sol"` — то есть Sol до сих пор является целью алиаса
`codex`. Поэтому «Terra — do not use», «Fable — do not use» и абзац про Sol — это
действующие ЗАПРЕЩАЮЩИЕ правила, а не описание несуществующего. Удалить их —
это удалить единственную защиту от маршрутизации на них.
По объёму: пункт про Sol — 1 155 Б, Terra и Fable вместе — 50 Б, то есть 18.0% модуля
(6 703 Б), а не половина. Модуль не тронут.

**Исторические иллюстрации с номерами задач и суммами оставлены.** Запрет из проектного
`CLAUDE.md` («Не добавляй в корневые инструкции отчёты… длинные примеры») адресован
КОРНЕВЫМ файлам с потолком 16 KiB; тот же документ прямо отдаёт правила поведения агентов
каталогу `.orchestra/pipelines/default/prompts/`. Проверил каждое вхождение с числом:
`base.md:35` (#415), `modules/code-quality.md:32` (#398), `modules/worker-lifecycle.md:28-35`
(V-548/V-550, #219), `modules/model-routing.md:19,22,25` (#334, #498/#505, #222),
`modules/orchestration.md:206` (#184), `roles/orchestrator.md:21-25` (#418),
`roles/reducer.md:20-22` (#231) — каждое обосновывает действующее правило рядом с собой.
Вырезать замер, оставив вывод, — это ослабить правило, а не сократить текст.

## 4. Факты, расходящиеся с реальностью машины

**Почему этот файл вообще в диффе.** В постановке `skills/vps-deploy.md` назван не был —
в неё попали только примеры дублей, но результатом задачи объявлен весь каталог
`.orchestra/pipelines/default/prompts/`, включая «утверждения, расходящиеся с реальностью
VPS». Я прошёл каталог целиком (п. 4 целиком — это тот проход) и нашёл там ровно одно
расхождение с машиной. Строго говоря, к снятию дублей эта правка относится косвенно:
она снимает не повтор между файлами, а ПРОТИВОРЕЧИЕ ВНУТРИ одного файла — строка 34
разрешала полагаться на автоматический `uv sync`, строка 54 того же файла запрещала
`uv sync` в проде. Из двух несовместимых версий одного правила осталась та, которая
совпадает с юнитом. Если оркестратор считает это выходом за границу — правка
изолирована в одном файле и снимается одним `git checkout` без последствий для остального
диффа.

**Исправлено: `skills/vps-deploy.md:34`** утверждал «`uv sync` runs automatically via
`ExecStartPre` — dependencies install themselves». `ExecStartPre` в юните НЕТ:
`systemctl show orchestra -p ExecStartPre --value` пуст, а эффективный
`ExecStart` задан drop-in'ом `/etc/systemd/system/orchestra.service.d/60-runtime-isolation.conf`
и равен `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m uvicorn
app.main:app --fd 3` (живой процесс: `/proc/1016880/cmdline` — то же самое). Утверждение
противоречило и правилу в том же файле (строка 54: «do not run an unpinned `uv sync` in
production»). Заменено на описание закреплённого рантайма.

**Проверено и НЕ тронуто:** `https://orc.seedon.ru` → HTTP 302 (живой адрес; при этом
`https://orchestra.seedon.ru` → 404, то есть устарел глобальный `~/.claude/CLAUDE.md`,
а не скилл). `scripts/wf_run.py` существует, и путь `data/workflow-runs/<run-id>/manifest.json`
из `modules/dynamic-workflows.md:31` совпадает с `scripts/wf_run.py:1058,1018`. Туннель
ноутбука из `skills/laptop-access.md`: ключ `/home/kesha/.ssh/tunnel_laptop` на месте,
на `127.0.0.1:2222` есть слушатель. Все имена инструментов, упомянутые в каталоге, есть
в живом MCP-наборе.

## 5. Критерий 4 — строка про интерпретатор

`roles/full-cycle.md:39` предписывает
`uv run --frozen python -m pytest <test-paths> -q`. **Оставлена без изменений: она верна.**

Проверено прямым прогоном в этом worktree, где `.venv` не было вовсе:
`uv run --frozen` создал локальное окружение («Installed 76 packages in 2.93s»), и
`uv run --frozen python -m pytest …` дал `213 passed`, RC=0. Абсолютный путь
импортированного модуля: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/clean-prompts/app/__init__.py`.
`UV_PROJECT_ENVIRONMENT` и `VIRTUAL_ENV` не выставлены ни в моём окружении, ни в окружении
службы (`/proc/1016880/environ`), ни в `/home/kesha/orchestra/.env`.

Посылка задачи («рабочий интерпретатор здесь `/opt/orchestra/runtimes/…-rag-v2/bin/python`»)
верна ровно наполовину и относится к другому: по этому пути работает СЛУЖБА (см. п. 4),
а не тесты. Про тесты правильный факт другой, и он объясняет старую спотыкачку — если
воркер САМ выставит `UV_PROJECT_ENVIRONMENT` на этот рантайм, обычный `uv run --frozen`
попытается доустановить в него пакеты и упадёт на read-only, из-за чего в `V-543` пришлось
добавлять `--no-sync` (`.orchestra/tasks/V-543/report.md:75-77`). Промпт никого туда
не посылает, так что чинить в нём нечего. Оба интерпретатора — один и тот же CPython 3.12.3
(`/opt/.../bin/python` — симлинк на `/usr/bin/python3.12`, `pyvenv.cfg: version_info = 3.12.3`).

## 6. Критерий 2 — проверка, что ни одна категория правил не потерялась

`verify_sections.py` пересобирает промпт каждой роли ДВАЖДЫ — из `git show HEAD:` и из
рабочего дерева — по слоям и `modules` из `pipeline.yaml`, и проверяет три вещи:

1. присутствие восьми категорий-якорей в промпте роли до и после: `<safety>`,
   `<approval-gate>`, `<git-workflow>`, `<worker-lifecycle>`, `<knowledge>`,
   `<communication-style>`, `<model-routing>`, `<user-values>`. Ни у одной роли состав
   не изменился (orchestrator / sub-orchestrator / full-cycle — все восемь; worker —
   safety, git, knowledge, style, values; reducer — safety, knowledge, style, values);
2. каждое ИСЧЕЗНУВШЕЕ предложение: либо в промпте той же роли остался похожий текст
   (Jaccard по словам ≥ 0.5, печатается «kept as»), либо это одна из шести вручную
   разобранных перефразировок из таблицы `PARAPHRASED`, и тогда скрипт требует, чтобы
   названный текст-наследник ФАКТИЧЕСКИ присутствовал в промпте;
3. ни один тег-обёртка не открывается в промпте дважды.

Итог: `RESULT: OK`, RC=0, полный вывод — `verify.log`. До правок пункт 3 давал
`{'background-jobs': 2}` у обоих оркестраторов (`tagscan.py`), после — `none` у всех ролей.

Ограничение проверки названо честно: Jaccard ловит переписанное близко к тексту; правило,
переписанное совсем другими словами, скрипт бы не сопоставил и показал как ORPHANED —
именно поэтому шесть таких случаев разобраны руками и в таблице указан их новый дом.

## 7. Критерий 5 — тесты доставки модулей

Такие тесты есть, и это не мои: `tests/test_default_pipeline.py` —
`test_modules_resolve_from_manifest`, `test_shared_conduct_modules_reach_every_role` (#490),
`test_shared_project_rules_are_delivered_once_to_their_readers` (проверяет `count(module) == 1`,
то есть ровно один экземпляр), `test_code_quality_has_one_owner_and_reaches_implementation_roles`,
`test_model_routing_reaches_only_spawn_capable_roles`, плюс классы про изоляцию
`<telegram-formatting>` и `<user-answer-format>`.

Прогоны интерпретатором из п. 5:
- `tests/test_default_pipeline.py test_prompting.py test_pipeline.py test_check_pipeline_manifest.py test_reducer_role.py test_legacy_pipeline_skills.py test_prompt_parent_selection.py test_review_requester_roles.py test_validate_spawn_unknown_role.py test_unified_html_skill.py test_laptop_skill_delivery_572.py` → **287 passed**, RC=0 (`tests.log`);
- всё, что упоминает снятые формулировки, найдено через `rg` и прогнано отдельно:
  `test_mcp_stdio.py test_api.py test_kb_index_injection_522.py test_adhoc_switch.py test_manager.py test_owned_dirs_migration_473.py test_hot_apply.py` → **505 passed**, RC=0 (`tests2.log`).

Полный сьют не гонялся: он требует глобального тест-лока и согласия PM.

Нового теста не добавлял. Проверка «тег-обёртка не повторяется» механическая, но в
продакшене от её отсутствия ничего не ломается, а покраснеть она может от законной правки
владельца — по правилу «Test the core, never the wording» такой тест писать нельзя.
Разовый `verify_sections.py` живёт в задаче как доказательство, а не в `tests/`: он
сравнивает с `HEAD` и после мержа теряет смысл.

## 8. Нужен ли рестарт

**Нет, ни для промптов, ни для скиллов.** Пути доставки у них разные, поэтому проверил оба.

*Модули и роли (всё, кроме `skills/`).* Промпт роли пересобирается из
`.orchestra/pipelines/**` на горячем пути: при первом сообщении после резюма
`app/session.py:1365` зовёт `manager.assemble_prompt` (`app/manager.py:1875`) →
`ROLE_SYSTEM_PROMPT` (`app/manager.py:265`) → `build_system_prompt`
(`app/pipeline.py:587`), который на строке 603 и ниже читает слои и модули с диска заново.
`load_pipeline` кэширован по `(st_mtime_ns, st_size)` манифеста (`app/pipeline.py:428-438`),
так что правка файла инвалидирует кэш сама. Ветка пересборки работает при
`prompt_overlay is not None` (`app/session.py:1354` — отрицательное плечо), а обычный спавн
кладёт туда `""`, а не `None` (`app/manager.py:677`): `None` означает полную замену промпта
оператором и намеренно не пересобирается.

*Скиллы (`skills/vps-deploy.md`).* Здесь доставка файловая, а не текстовая, и владеет ею
`app/prompting.py`: `inject_skills_to_worktree_report` копирует `prompts/skills/<name>.md`
в `<worktree>/.claude/skills/<name>/SKILL.md` (для Codex — `.codex/`), сравнивая байты и
пропуская совпадающие (`app/prompting.py:307`). Зовётся это не при создании worktree, а на
КАЖДОМ (пере)подключении бэкенда — `session.py:1942` и `:3760` через `_refresh_skills`
(`session.py:1512`), который каждый раз перечитывает список скиллов роли из манифеста.
То есть отредактированный скилл доезжает на следующем переподключении сессии, а не
на следующем ходе, как модули; рестарт службы и здесь не нужен.

Общая оговорка для обоих путей: сначала мерж в `main`. Живая служба читает
`/home/kesha/orchestra/.orchestra/pipelines/`, а не мой worktree.

Уточнение к подсказке оркестратора: `assemble_prompt` лежит в `app/manager.py:1875`, а
чтение файлов — в `app/pipeline.py:587`; `app/prompting.py` владеет инъекцией скиллов,
`prompt_template_hash` и `refresh_worker_memory`. Подсказка оказалась права по существу
(ответ про рестарт закрывается через `app/prompting.py`), но только для скиллов —
для модулей владелец другой.

Оговорка про пометку в шапке: `prompt_template_hash` (`app/prompting.py:216`) хеширует только
`base.md + role_prompt_file(role)`, а `role_prompt_file` берёт `modules` из frontmatter
файла роли, которого у ролей нет. Значит правки ЛЮБОГО модуля не поднимают
`templates_changed`, и агент получает пометку «refreshed context» вместо «your role
instructions were updated». Текст при этом доставляется. Дефект не мой и не новый
(так уже живут `user-values`, `code-quality`, `git-workflow`); занесён в `TODO.md`.

## 9. Что проверил сам вместо модельного ревью

Codex-пул выжран, ревью не было. Что сделано руками и машиной:

- **Инвентаризация повторов машиной, а не на глаз.** `dupscan.py` сравнивает все пары
  предложений между файлами каталога по Jaccard ≥ 0.5 и печатает `file:line` обеих сторон.
  Из 14 найденных пар 8 оказались между файлами, которые никогда не попадают в один
  промпт, — они в работу не пошли и названы в п. 2.
- **Проверка состава правил после каждой правки** — `verify_sections.py`, п. 6.
  Первый прогон нашёл мою собственную ошибку: вместе с дублем я срезал
  «Check actual requirements, not merely a green status», которого в `code-quality`
  нет. Восстановлено, в `verify.log` этот пункт теперь `[COVERED 1.00]`.
- **Каждое «мёртвое» правило проверено по коду, а не по памяти**: Sol/Terra/Fable — по
  `app/models.py` и словарю алиасов; имена инструментов — по своему MCP-набору; пути и
  адреса — `curl`, `ss`, `systemctl show`, `/proc/<pid>/cmdline`, `ls`.
- **Путь применения правок прочитан в коде** (п. 8), а не выведен из того, что «тесты зелёные».
- **Прогон тестов** — 287 + 505 passed, RC=0, тем же интерпретатором, что назван в промпте.
- **`verify_sections.py` привязан к базовому коммиту `a3d8b8f4`, а не к `HEAD`.** После
  первого коммита сравнение с `HEAD` стало бы пустым и «зелёным» ни о чём; лог
  перегенерирован уже с этой привязкой, так что доказательство воспроизводимо и после мержа.
- **Границы:** `AGENTS.md`/`CLAUDE.md` не тронуты (`git diff a3d8b8f4 --stat` пуст), поэтому
  `check_instruction_contract.py --sync` не требовался; сам контракт на всякий случай
  прогнан — «Instruction contract OK», RC=0. `roles/orchestrator.md` и территория #V-576 —
  см. шапку. Артефакты задачи прогнаны через `app.secret_mask.mask_secrets`: совпадений
  по форме секрета нет.

Что осталось непроверенным: живой ход живого агента с новым промптом (для этого нужен мерж
в `main`, а это решение оркестратора); полный сьют (нужен тест-лок); содержимое скиллов
`grill-me.md`, `orchestra-agents.md`, `html-artifacts.md`, `codex-debate.md` на предмет
внутренних противоречий — я проверил там только имена инструментов и пути, а не смысл.
