# Чужие харнесы и агенты: что у них есть и что мы взяли

Разборы чужих продуктов: заявки лендинга против их же кода, механизмы, которые стоит перенять, и оси, по которым нас сравнивают.

## Established

### Prime Agent и Hermes

- **Из жизненного цикла Prime Agent у нас УЖЕ есть почти всё: непрерывность на демоне, иерархический спавн, прямой обмен сообщениями между агентами, отдельный worktree на воркера по умолчанию и сохранённые расписания.** Незакрытыми остаются три вещи, и сохранение сессии в их число не входит: видимое модели пространство имён IPython, объединённые долгие цели с автономией и общее дерево транскриптов через разные рантаймы · ищи: `Prime Agent`, `auto_resume_all`, `spawn_worker`, `send_message`, `bg_create`, `worktree` · `app/main.py:401-407`; `app/manager.py:2207-2329`; `app/mcp_stdio.py:930-963,1152-1200,2857-2904`; `app/workspace.py:492-570`; `app/session_turns.py:24-66`; `.orchestra/tasks/421/research.md` M3/M7/M8/M9 · 2026-08-30, #421
- **Аналога Prime RLM — «контекст как переменная» и живое состояние ядра IPython — у нас нет вовсе.** Исправленный поиск по нескольким выражениям пуст, а положительный контроль подтверждает: у нас отдельное сохранённое хранилище сессий в JSONL, без вычислительного пространства имён · ищи: `RLM`, `context-as-variable`, `IPython`, `kernel-state`, «персистентный REPL» · `rg -n -i --glob '!app/static/css/vendor/**' -e 'ipython' -e 'jupyter' -e 'kernel[-_]state' -e 'prompt-as-a-variable' -e 'context-as-variable' app pipelines pyproject.toml` → `RC=1`; `app/harness/sessions.py:23-79`; `.orchestra/tasks/421/research.md` M1/M2/F2 · 2026-08-30, #421
- **`/refine` у Prime Agent правит память САМ, у нас канонический факт требует апрува — и это конфликт только про канон, а не про всю личную память.** Prime автоматически применяет проверенный по форме CRUD к дополнительному слою харнеса: база неизменяема, есть локальная и глобальная область, отказ при конкурентной правке и снимки для отката. У нас канонический `links:` требует предложения в артефакте задачи и явной квитанции одобренного тикета · ищи: `/refine`, `proposal`, `approval receipt`, `rollback`, «самоизменение памяти» · [Prime refinement source](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/core/refinement/refinement.ts#L673-L844); `.orchestra/pipelines/default/prompts/modules/research-method.md:144-169`; `.orchestra/pipelines/default/prompts/modules/self-improvement.md:65-84`; `.orchestra/tasks/421/research.md` M5/§1 · 2026-08-30, #421
- **Накопление навыков умеет ЗАКРЕПИТЬ нарушение правил, за которое локально дали награду.** Prime Agent прямо сообщает о наблюдавшихся навыках жульничества через RCON в Factorio. Наш аналог — личная память, в которой закрепляется пропуск тестов, — назван ГИПОТЕТИЧЕСКИМ: измеренного случая у нас не было · ищи: `Factorio`, `RCON`, `cheating skills`, `.orchestra/workers`, `xfail`, «вредный навык» · [Prime technical post](https://www.primeintellect.ai/blog/prime-agent); `.orchestra/pipelines/default/prompts/modules/self-improvement.md:65-84`; `.orchestra/pipelines/default/prompts/roles/full-cycle.md:118-135`; `.orchestra/tasks/421/research.md` §3 · 2026-08-30, #421
- **`bg_create` переживает гибернацию агента, но не рестарт сервиса: рестарт восстанавливает джобы всех типов, КРОМЕ активного `run`, который превращается в явный прерванный исход.** Значит `run` — не аналог восстановимого вычисления из снимков ядра Prime · ищи: `bg_create`, `restore_from_db`, `run`, `interrupted`, «фоновые джобы после рестарта» · `app/bg_jobs.py:488-529`; `app/mcp_stdio.py:2857-2904`; `.orchestra/tasks/421/research.md` M7/M9 · 2026-08-30, #421
- **В текущем контуре Hermes v0.20.1 записи навыков и памяти — и в переднем, и в фоновом плане — проходят БЕЗ апрува:** `write_approval` по умолчанию выключен, и в действующем конфиге его никто не переопределил. Автономных писателей навыков в архитектуре два — самоулучшение по расписанию и опциональная консолидация куратором с созданием зонтичного навыка, — но второй сейчас выключен через `consolidate=false` · ищи: `Hermes`, `write_approval`, `background_review`, `curator consolidation`, `create umbrella`, «кто пишет навык» · `/home/maxim/.hermes/hermes-agent/tools/write_approval.py:62-89,253-289`; `/home/maxim/.hermes/config.yaml:79-90`; `/home/maxim/.hermes/hermes-agent/agent/background_review.py:182-285`; `/home/maxim/.hermes/hermes-agent/agent/curator.py:430-539`; `/home/maxim/.hermes/hermes-agent/tools/skill_manager_tool.py:454-460,1561-1581`; `.orchestra/tasks/421/research.md` M5/M12 · 2026-08-30, #421
- **У куратора Hermes ДВА разных права, и они не совпадают.** Фоновая LLM жёстко отказывается трогать поставочные, хабовые, закреплённые и пользовательские навыки; а детерминированный путь «по бездействию» при значении по умолчанию `prune_builtins=true` архивирует именно поставочные. Хаб не архивируется, автоудаления нет, архив восстановим · ищи: `Hermes Curator`, `prune_builtins`, `bundled`, `archive`, `consolidate`, «LLM не трогает bundled» · `/home/maxim/.hermes/hermes-agent/tools/skill_manager_tool.py:301-420`; `/home/maxim/.hermes/hermes-agent/agent/curator.py:192-201,305-383`; [official curator docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/curator.md); `.orchestra/tasks/421/research.md` M12 · 2026-08-30, #421
- **«3 навыка из 84 созданы агентом» у Hermes НИЧЕГО не доказывает — ни осторожности политики, ни малой наработки.** Живой инвентарь: 3 созданных агентом из 84 (3.57%; 81 поставочный). Число не равно счётчику созданий фоновым ревью, потому что ручное принятие ставит ту же управляемую метку. `curator runs=2` — знаменатель обслуживания, а количество форков, кандидатов и отказов не измерено вовсе · ищи: `3 agent-created`, `84 total`, `81 bundled`, `curator runs`, `adopt`, «осторожная конструкция или мало наработано» · живой `hermes curator status`, снятый 2026-08-30; `/home/maxim/.hermes/config.yaml:88-90`; `/home/maxim/.hermes/hermes-agent/agent/turn_finalizer.py:732-766`; [Hermes curator docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/curator.md); `.orchestra/tasks/421/research.md` F11 · 2026-08-30, #421

### Сравнение с чужими ADE и субагентами

- **Worktree-изоляция агентов больше НЕ является нашим отличием: она есть у Orca, omp и Paseo,
  и её же предлагает Claude Code (`isolation: worktree`).** Отличие сместилось в то, кому
  принадлежит жизненный цикл агента и ходит ли он через границу вендора. · README трёх репозиториев
  + `code.claude.com/docs/en/sub-agents` · 02.09.2026, #503
- **Субагенты Claude Code умеют то, что мы считали своим: свой контекст, `SendMessage` между
  агентами, вложенность до трёх уровней, resume с полной историей, опциональный worktree.**
  Дословно: «Each subagent runs in its own context window», «a subagent can spawn subagents of its
  own, up to three layers below the main conversation», «Resumed subagents retain their full
  conversation history». · `code.claude.com/docs/en/sub-agents` · 02.09.2026, #503
- **Разница с субагентами измерима по времени жизни, а не по описанию: субагенты в нашем же
  контуре живут медиану 12,5 с (p90 75,1 с, максимум 587,2 с, дольше 10 минут — 0,0%), сессии
  воркеров — медиану 0,8 ч при p90 130,6 ч и максимуме 531,8 ч (22 дня), дольше суток жили 81 из
  431.** · боевая БД, `subagents` и `sessions` · 02.09.2026, #503
- **Через границу ВЕНДОРА субагент не ходит: субагенты Claude Code — это Claude, субагенты
  Codex — это Codex.** Поэтому «написал Codex, ревьюит Claude» остаётся структурным отличием
  Orchestra, а не настройкой. · обе документации · 02.09.2026, #503
- **Заявка omp «тулинг внутри харнесса» — правда и документирована, а «миллисекунды» — вывод, а не
  их замер.** Дословно: «~80,000 lines of Rust, doing the work other harnesses shell out for …
  all in-process on the libuv pool. No fork/exec on the hot path», плюс 58 CLI-утилит вкомпилированы
  в builtins-крату. Числовых замеров задержки нет ни в README, ни в их посте про harness-проблему. ·
  `can1357/oh-my-pi` README + `stencil.so/blog/the-harness-problem` · 02.09.2026, #503
- **Цена внешнего тул-вызова на этом VPS: медиана 3 667,6 мкс против 20,2 мкс у in-process, при
  голом `fork+exec` 2 170,0 мкс — то есть ~180× разницы, и 60% её это запуск процесса.** Для нас
  малозначимо (узкое место — round-trip к модели), для интерактивного харнесса значимо. · замер
  `docs/tasks/503/bench_spawn.py`, 40 повторов, чередование A/B, loadavg 2.87 · 02.09.2026, #503 · открыть: docs/tasks/503/bench_spawn.py → `.orchestra/archive/laptop-tasks/503/bench_spawn.py`
- **По широте рантаймов мы позади рынка: 4 против «any CLI agent» (28 перечисленных) у Orca и 26 у
  Multica.** Наш контракт бэкенда закрыт кодом, чужой CLI конфигом не подключается. · README Orca и
  Multica · 02.09.2026, #503
- **Публичная строка README «Sub-agents spawned — 5 593» вводит в заблуждение: 96,5% строк таблицы
  `subagents` — это `local_bash`, фоновые команды, а не агенты.** Настоящих суб-агентов на основной
  установке 197 (`local_agent` 151 + `codex` 46). · `select task_type, count(*) from subagents` на
  обеих базах · 02.09.2026, #503
- **Метаданные чужих репозиториев брать `gh api repos/<owner>/<repo>`, а не из поисковой выдачи:**
  выдача давала Orca «53k» при фактических 59 427 звёздах. · 02.09.2026, #503

- **Archestra.AI (`archestra-ai/archestra`, 4 243★) — не витрина, а работающая платформа.** Числа: 5 960 коммитов с 15.07.2025, 495 коммитов за последние 30 дней, 80 контрибьюторов, 320 релизов при темпе около одного в день, 24 открытых issue (в API видно 44, потому что `open_issues_count` считает их вместе с PR). Лицензия дуальная: AGPL-3.0-only по умолчанию плюс `LicenseRef-Archestra-Enterprise`. Важное про неё: enterprise-код НЕ закрыт, он лежит в том же репозитории — 212 файлов помечены, 136 целиком, 381 SPDX-врезка в 76 AGPL-файлах, 94 файла `*.ee.*`; ограничено только право промышленного использования свыше 30 пользователей · ищи: `archestra-ai/archestra`, `LicenseRef-Archestra-Enterprise`, `Small Team Clause`, `open_issues_count`, «дуальная лицензия AGPL enterprise» · upstream @ `c0f30875`: `LICENSE.md:1-24`, `LICENSE_ENTERPRISE:26-32`, `platform/backend/src/enterprise-tier.ts:7,57`; `gh api repos/archestra-ai/archestra`, `search/issues`, `git rev-list --count HEAD` · 2026-09-03, #470
- **Серверному рантайму агентов и MCP-серверов Archestra нужен Kubernetes, а не «просто Docker».** Гейт включения кода-рантайма пропускает только при явно заданном runner host либо при настроенном kubeconfig/in-cluster. Квикстарт `docker run` это требование не отменяет, а ПРЯЧЕТ: в образ вкомпилированы KinD и Dagger Engine, поэтому команда с лендинга и монтирует `/var/run/docker.sock` · ищи: `isCodeRuntimeEnabled`, `KIND_VERSION`, `dagger-engine.quickstart.yaml`, `docker.sock`, «нужен ли кубернетес Archestra» · upstream @ `c0f30875`: `platform/backend/src/config.ts:1941-1944`, `platform/Dockerfile:7,34,160,577`, `platform/docker/supervisord/postgres.conf:3`, `platform/helm/archestra/Chart.yaml:27` · 2026-09-03, #470

## Rejected

### Prime Agent и Hermes

- **«Prime Agent надо переносить целиком ради daemon sessions, A2A, memory и background work» отвергнуто.** У всех этих контрактов в Orchestra уже есть боевые владельцы, а полный перенос добавил бы нового владельца состояния ядра и контекста — без единого локального A/B · ищи: `Prime Agent`, `daemon sessions`, `A2A`, `memory`, `background work`, «перенести целиком» · опровергнуто: `.orchestra/tasks/421/research.md` M1–M11; `app/manager.py:2207-2329`; `app/mcp_stdio.py:930-963,1152-1200,2857-2904` · 2026-08-30, #421
- **«Prime `/refine` без ограничений переписывает базовый prompt» отвергнуто.** Реализация прямо запрещает править `base_system_prompt`, по умолчанию работает в локальной области, отказывает при конкурентных изменениях записи и хранит снимки «до/после» для отката. Открытый риск там другой — истинность и согласованность записанного, а не отсутствие ограничителей · ищи: `/refine`, `base_system_prompt`, `local scope`, `baselineState`, `rollback` · опровергнуто: [Prime refinement source](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/core/refinement/refinement.ts#L673-L844); `.orchestra/tasks/421/research.md` Counter-evidence 1 · 2026-08-30, #421
- **«Вся долговечная память Orchestra одобрена человеком» отвергнуто.** Канонические связи действительно за гейтом апрува, но `.orchestra/workers/<name>.md` НАМЕРЕННО имеет низкий порог: апрува не требует и сам подставляется в промпт на resume и после сжатия · ищи: `.orchestra/workers`, `approval`, `auto-inject`, `personal memory`, «личная память без апрува» · опровергнуто: `.orchestra/pipelines/default/prompts/modules/self-improvement.md:65-84`; `.orchestra/pipelines/default/prompts/modules/research-method.md:159-169`; `.orchestra/tasks/421/research.md` §1/§3 · 2026-08-30, #421
- **Утверждение `curator --help` у Hermes «Bundled and hub-installed skills are never touched» отвергнуто как описание поведения.** Установленный исходник по умолчанию делает поставочные навыки детерминированными кандидатами на архивацию; отказывается их трогать только путь через LLM. То есть help описывает безопасный путь и умалчивает про второй · ищи: `curator --help`, `Bundled`, `never touched`, `prune_builtins`, «help против source» · опровергнуто: отозванный ввод живого help; `/home/maxim/.hermes/hermes-agent/agent/curator.py:192-201,305-383`; `/home/maxim/.hermes/hermes-agent/tools/skill_manager_tool.py:355-380`; `.orchestra/tasks/421/research.md` «Расхождение Hermes» · 2026-08-30, #421

### Сравнение с чужими ADE и субагентами

- **«Orca — это агент-оркестратор, который сам режет задачу»** · опровергнуто их же README:
  распределяет человек («Fan one prompt across five agents … compare the results and merge the
  winner»), а «The AI Orchestrator for 100x builders» — заголовок шапки без механизма за ним ·
  02.09.2026, #503
- **«Наше отличие от субагентов — в изоляции и в том, что субагенты не общаются между собой»** ·
  опровергнуто документацией Claude Code: есть и `SendMessage` между агентами, и
  `isolation: worktree` · 02.09.2026, #503
- **«omp отвечает за миллисекунды вместо вызова внешних программ» как ИХ замер** · опровергнуто
  чтением обоих их первоисточников: цифры там только про качество редактирования (6.7% → 68.3%,
  −61% токенов, 2.1×), задержек нет · 02.09.2026, #503

## Gaps

### Prime Agent и Hermes

- Неизвестно, снижает ли optional RLM compute стоимость/ошибки на Orchestra-shaped long-context задачах относительно current tools + files + focused subagents · Prime/RLM публикуют чужие benchmark domains, локальный runtime запрещено запускать в #421; `.orchestra/tasks/421/research.md` F5 · 2026-08-30, #421
- Неизвестно, какой текущий consumer механически ловит reward-hacked запись в `.orchestra/workers/<name>.md` до следующего task; shared-rule triage и canonical-link validator personal memory не покрывают · `.orchestra/pipelines/default/prompts/modules/self-improvement.md:65-84`; `.orchestra/tasks/421/research.md` §3 · 2026-08-30, #421
- Не найден production consumer Orchestra, которому нужны session branch/fork/leaf semantics вместо линейного immutable log; без consumer цена новой state machine не соотнесена с outcome · `app/db.py:1605-1639,2347-2357`; `.orchestra/tasks/421/research.md` M8 · 2026-08-30, #421
- Неизвестно, сколько Hermes background skill-review forks реально запускалось, сколько proposals они дали и сколько writes/guards отказали; без этих чисел нельзя оценить precision или conservatism трёх agent-created skills · live status даёт curator runs, не creation-review runs; `.orchestra/tasks/421/research.md` F11 · 2026-08-30, #421

### Сравнение с чужими ADE и субагентами

- Изоляция и межагентный обмен у Multica и cmux, ревью у cmux — в README не описаны, ответ живёт на
  их сайтах документации · один заход на сайт для честной ячейки мал · 02.09.2026, #503
- `herdrdev/herdr` (34 498★) не разобран: README 4,4 КБ, весь предмет на `herdr.dev/docs` ·
  02.09.2026, #503
- Никто из шести не публикует воспроизводимых замеров производительности продукта целиком; сравнить
  их между собой нечем, кроме собственного стенда · 02.09.2026, #503

## Источники

### Prime Agent и Hermes

- `.orchestra/tasks/421/research.md` — дельта Prime Agent ↔ Hermes ↔ Orchestra по каждому механизму, модели доверия при записи навыка, риск reward hacking и карта источников.

### Сравнение с чужими ADE и субагентами

- .orchestra/tasks/470/research.md — Archestra.AI: девять заявок лендинга против кода с `путь:строка`, лицензионные и рантайм-гейты, зрелость репозитория.
- docs/tasks/503/comparison.md — матрица по восьми осям, разбор каждой ячейки, ответ про субагентов · открыть: docs/tasks/503/comparison.md → `.orchestra/archive/laptop-tasks/503/comparison.md`
  Claude Code и Codex, раздел «где мы объективно слабее». По пути `docs/tasks/503/` его нет — он в архиве ноутбучных задач (проверено 06.09.2026, #523).
- docs/tasks/503/bench_spawn.py — замер спавна в процессе против `fork+exec`. По пути `docs/tasks/503/` его нет — он в архиве ноутбучных задач (проверено 06.09.2026, #523). · открыть: docs/tasks/503/bench_spawn.py → `.orchestra/archive/laptop-tasks/503/bench_spawn.py`
