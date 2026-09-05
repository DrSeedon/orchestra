# competitive-landscape — чем Orchestra отличается от чужих ADE/harness и от субагентов

## Established
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
  `docs/tasks/503/bench_spawn.py`, 40 повторов, чередование A/B, loadavg 2.87 · 02.09.2026, #503
- **По широте рантаймов мы позади рынка: 4 против «any CLI agent» (28 перечисленных) у Orca и 26 у
  Multica.** Наш контракт бэкенда закрыт кодом, чужой CLI конфигом не подключается. · README Orca и
  Multica · 02.09.2026, #503
- **Публичная строка README «Sub-agents spawned — 5 593» вводит в заблуждение: 96,5% строк таблицы
  `subagents` — это `local_bash`, фоновые команды, а не агенты.** Настоящих суб-агентов на основной
  установке 197 (`local_agent` 151 + `codex` 46). · `select task_type, count(*) from subagents` на
  обеих базах · 02.09.2026, #503
- **Метаданные чужих репозиториев брать `gh api repos/<owner>/<repo>`, а не из поисковой выдачи:**
  выдача давала Orca «53k» при фактических 59 427 звёздах. · 02.09.2026, #503

- `fact:archestra-scale-and-dual-license` — Archestra.AI (`archestra-ai/archestra`, 4 243★) — не витрина, а работающая платформа: 5 960 коммитов с 15.07.2025, 495 коммитов за последние 30 дней, 80 контрибьюторов, 320 релизов при темпе ~1 в день, 24 открытых issue (в API видно 44, потому что `open_issues_count` считает вместе с PR); лицензия дуальная — AGPL-3.0-only по умолчанию плюс `LicenseRef-Archestra-Enterprise`, причём enterprise-код НЕ закрыт, а лежит в репозитории (212 файлов помечены, 136 целиком, 381 SPDX-врезка в 76 AGPL-файлах, 94 файла `*.ee.*`), ограничено только право прод-использования свыше 30 пользователей · search: `archestra-ai/archestra`, `LicenseRef-Archestra-Enterprise`, `Small Team Clause`, `open_issues_count`, «дуальная лицензия AGPL enterprise» · evidence: upstream @ `c0f30875`: `LICENSE.md:1-24`, `LICENSE_ENTERPRISE:26-32`, `platform/backend/src/enterprise-tier.ts:7,57`; `gh api repos/archestra-ai/archestra`, `search/issues`, `git rev-list --count HEAD` · 2026-09-03, #470
- `fact:archestra-requires-kubernetes-for-agent-runtime` — У Archestra серверный рантайм агентов и MCP-серверов требует Kubernetes, а не «просто Docker»: гейт включения кода-рантайма пропускает только при явном runner host либо настроенном kubeconfig/in-cluster, а квикстарт `docker run` это не отменяет, а прячет — в образ вкомпилированы KinD и Dagger Engine, поэтому команда с лендинга монтирует `/var/run/docker.sock` · search: `isCodeRuntimeEnabled`, `KIND_VERSION`, `dagger-engine.quickstart.yaml`, `docker.sock`, «нужен ли кубернетес Archestra» · evidence: upstream @ `c0f30875`: `platform/backend/src/config.ts:1941-1944`, `platform/Dockerfile:7,34,160,577`, `platform/docker/supervisord/postgres.conf:3`, `platform/helm/archestra/Chart.yaml:27` · 2026-09-03, #470

## Rejected
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
- Изоляция и межагентный обмен у Multica и cmux, ревью у cmux — в README не описаны, ответ живёт на
  их сайтах документации · один заход на сайт для честной ячейки мал · 02.09.2026, #503
- `herdrdev/herdr` (34 498★) не разобран: README 4,4 КБ, весь предмет на `herdr.dev/docs` ·
  02.09.2026, #503
- Никто из шести не публикует воспроизводимых замеров производительности продукта целиком; сравнить
  их между собой нечем, кроме собственного стенда · 02.09.2026, #503

## Источники
- .orchestra/tasks/470/research.md — Archestra.AI: девять заявок лендинга против кода с `путь:строка`, лицензионные и рантайм-гейты, зрелость репозитория.
- docs/tasks/503/comparison.md — матрица по восьми осям, разбор каждой ячейки, ответ про субагентов
  Claude Code и Codex, раздел «где мы объективно слабее».
- docs/tasks/503/bench_spawn.py — замер in-process против fork+exec.
