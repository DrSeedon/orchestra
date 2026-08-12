# #228 — план принуждения ограничений

## Решение

Из 48 инвентаризационных пачек только 15 относятся к слоям, которые платформа
может принуждать без понимания процесса: 6 по имени tool и 9 по payload. Ещё 18
требуют состояния и кода Orchestra, а 15 являются методикой. Значит,
**большинство перечисленной policy surface (33 пачки против 15) нельзя перенести
в tool hooks**. Это счёт пачек разной гранулярности, а не процент атомарных правил.

Для `run_in_background` выбираем реальное принуждение через `PreToolUse` и
оставляем формулировку `BLOCKED`. Причины:

1. нарушение не является безвредным: detached-процесс теряется на границе хода,
   а агент получает ложное впечатление о продолжающейся работе;
2. `PreToolUse` уже доказан изолированным прогоном как обязательная врезка:
   deny победил `Bash(*)`, агент получил tool error, marker не появился;
3. payload `run_in_background` однозначен, поэтому гард не требует догадок о
   намерении или состоянии пользователя.

До активации хука живая строка `BLOCKED` остаётся фактически ложной. Поэтому код
можно внедрять только вместе с разрешённым окном перезапуска/реконнекта и
положительной canary-проверкой; отдельно выкатывать одну формулировку нельзя.

## Отбор первого pilot

Критерий отбора: сначала цена состоявшегося нарушения, затем полнота перехвата
именно этого контракта и цена ложного запрета. Pilot берёт две из девяти
PAYLOAD-пачек:

| Пачка | Что физически случится при нарушении | Решение |
|---|---|---|
| P2 — явные destructive Bash signatures | Рекурсивное удаление даёт необратимую потерю файлов; `chmod 777` снимает границу доступа; `curl \| bash` исполняет недоверенный код | **В pilot.** Блокировать только перечисленные, токенизируемые формы; не обещать полноценный shell sandbox |
| P1 — `run_in_background=true` | Работа физически стартует, но не управляется Orchestra и убивается на конце хода; transcript может выглядеть успешным | **В pilot.** Exact boolean invariant, закрывается hook полностью для Claude `Bash` |
| P3 — service/deploy/VCS mutation | Неавторизованный рестарт обрывает ходы, deploy/push меняет внешнее состояние | Не брать: hook не знает о разрешении текущего пользователя и будет либо пропускать запретное, либо запрещать разрешённое |
| P4 — территория записи | Утечка/перезапись чужих файлов | Не брать: structured path-hook обходится через Bash/interpreter; нужен sandbox/broker |
| P5 — immutable oracle | Подмена теста даёт ложную приёмку | Не брать: нужен RED commit и runtime state, которых нет в payload |
| P6 — `kill_worker(force=true)` | Обход lifecycle может навсегда архивировать живую/грязную работу | Не брать: caller identity, owner и lifecycle должны проверяться server-side; Claude-only hook оставит другие runtimes открытыми |
| P7 — message target | Сообщение уходит пользователю/чужому контуру | Не брать: parent identity и ownership — server state |
| P8 — secrets/path/content | Секрет попадает в argv/artifact/чужой sink | Не брать: статические формы неполны, сырой payload нельзя логировать; argv-частью уже владеет #224 |
| P9 — polling/resources | Цикл тратит CPU/память/контекст, tmpfs вытесняет соседей | Не брать: настоящая граница — supervisor/cgroup; сигнатуры дают слабую защиту |

Выбор P1+P2 не означает, что P3–P9 безопаснее. У них выше риск ложного чувства
защиты: hook видит один payload, а нужный инвариант зависит от runtime state или
обходится другим executor.

## Конструкция pilot-хука

Встраивание — управляемый Orchestra in-process hook в
`ClaudeAgentOptions.hooks`, не пользовательский `settings.json`:

- один `HookMatcher(matcher="Bash")` на `PreToolUse` и один callback, чтобы не
  получать конкурирующие решения от нескольких matcher-ов;
- `tool_input.run_in_background is True` → `permissionDecision="deny"` с
  короткой причиной, содержащей `run_in_background`;
- строка `command` токенизируется без исполнения стандартным POSIX `shlex` с
  punctuation `();<>|&`; basename executable определяется только в command
  position: начало строки либо позиция после `;`, `&&`, `||`, `|`, `&`, `(`;
- recursive `rm` означает command basename `rm` и option до `--`, равный
  `--recursive` либо short-option cluster с `r`/`R` (`-r`, `-rf`, `-fr`);
- dangerous `chmod` означает command basename `chmod` и первый mode operand
  после опций/опционального `--`, равный `777` либо `0777`;
- download-execute означает command basename `curl`, за которым в соседнем
  pipeline segment следует command basename `sh` либо `bash`; абсолютные пути
  executables нормализуются до basename;
- безопасный вызов возвращает **без** `permissionDecision`, а не `allow`:
  явный `allow` сам обошёл бы последующий permission resolver/`can_use_tool`;
- reason не включает исходную команду и callback не пишет payload в лог;
- существующая payload-ветка `run_in_background` удаляется из
  `_make_auto_approve`: один инвариант должен иметь одного рабочего owner-а.
  Name-fallback для `AskUserQuestion`/`Monitor` остаётся вне этого pilot.

Это не shell security boundary. В pilot намеренно не разбираются shell keywords,
wrappers (`env`, `command`, `sudo`), newline как separator, alias/function,
expansion, command substitution, heredoc и вложенный `sh/bash -c`; parse error
остаётся обычной permission-проверке, а не получает ложный `allow`. Эти формы и
другие runtimes остаются непринуждаемыми до capability boundary. Frozen oracle
проверяет заявленную мини-грамматику и safe near-misses, а не обещает больше.

## Физический результат и видимость

Unit oracle доказывает только установку matcher, SDK output shape и решения
callback. Отдельная manual canary доказывает runtime-часть: при deny CLI должен
остановить Bash **до исполнения**, вернуть агенту громкий tool error с причиной и
не создать/не удалить marker. Автоматическое уведомление parent этим не
появляется — это отдельная R17. При отсутствии deny вызов должен продолжить
обычную permission-проверку, а не стать автоматически разрешённым.

Активация требует отдельного окна: Python-код живёт в процессе Orchestra, а
options уже подключённых Claude clients зафиксированы до реконнекта. В окне нужна
новая disposable Claude-сессия и marker-canary; живые рабочие сессии как стенд не
использовать.

## Цена

Измерена стоимость **command-hook с отдельным Python process**, а не предлагаемого
in-process callback: 48/48 вызовов; p50 54.806–60.403 ms, p95
98.955–111.988 ms на matching Bash call. Полные batches дали 8259.757 ms без
hook и 7915.497/8547.431 ms с hook. Шум model/tool loop больше наблюдаемой
разницы, поэтому влияние на end-to-end цикл **не установлено**. Для in-process
варианта нет измеренной цифры; оценку из command-hook сюда не переносим.

## 18 ограничений состояния/процесса — сортировка по цене нарушения

Это backlog решений, не проекты реализации. Уровни отсортированы по последствию
состоявшегося нарушения; внутри уровня точный числовой порядок не заявляется.
Текущая hard-защита снижает вероятность, но не цену гипотетического обхода.

### C — необратимое внешнее действие, потеря данных или security boundary

1. **R13 Runtime sandbox/approval:** произвольная команда с полномочиями процесса
   может уничтожить/вывести данные хоста; runtimes сейчас явно permissive.
2. **R18 Provider/credential policy:** утечка credential или запрещённый provider
   даёт чужой/платный доступ и нарушает окончательное решение «subscription only».
3. **R16 Current-user authorization:** неавторизованный deploy/restart/external
   mutation меняет production и может оборвать активные ходы.
4. **R15 Task/payment transitions:** неверный actor/order меняет финансовое или
   договорное состояние до доказанного merge.
5. **R12 Safe cwd roots:** обход admission открывает protected paths/секреты;
   сегодня hard только стартовый cwd, не последующие syscalls.
6. **R10 Semantic lifecycle:** force/ошибка state может навсегда архивировать
   живую, dirty или ещё нужную работу.
7. **R11 Role-specific MCP authority:** worker с full catalog способен мутировать
   sessions/tasks/других workers; измеренно роли видят одинаковые 36 tools.

### H — крупный расход, обход контроля или ложная приёмка

8. **R3 Model policy:** запрещённая модель реально создаётся и расходует не тот
   пул; блокировкой уже владеет **#227**, здесь её не дублировать.
9. **R5 Token/goal budget:** работа не останавливается и может превысить бюджет
   кратно; измерено 8,095 tokens при лимите 1,000.
10. **R4 Weekly worker quota:** обход способен исчерпать недельный рабочий пул;
    текущий hard guard покрывает новые worker turns, но не global budget.
11. **R7 RED/oracle/dependency integrity:** изменённый или отсутствующий oracle
    превращает зелёный результат в ложное доказательство реализации.
12. **R6 Full-cycle gates:** реализация до approval создаёт неразрешённые code/state
    changes; server phase state отсутствует.
13. **R9 Review ceiling/verdict authenticity:** пропуск review или выдуманный
    verdict пропускает дефект под видом независимой проверки.
14. **R14 Native delegation contract:** native subagent обходит Orchestra session,
    worktree и ownership tracking; coverage различается по runtime/роли.
15. **R2 Unknown-role policy:** fail-open validator допускает роль без заявленного
    контракта; сейчас полный путь падает раньше случайно, а не policy verdict-ом.
16. **R1 Known-role spawn topology:** обход создаёт запрещённую ветвь делегации;
    для известных ролей текущий validator hard и возвращает 409 до worktree.

### M — потеря наблюдаемости, качества или ограниченный лишний расход

17. **R17 Parent notification:** отказ/опасная попытка остаётся только в child log;
    parent не узнаёт и может принять неполную работу.
18. **R8 Executor route/attempt ledger:** повтор того же executor или неверная
    эскалация тратит пул и усиливает одну ошибку, но обычно не создаёт прямой
    внешний side effect.

15 пачек 3B остаются культурой. В этом pilot их текст и поведение не меняются;
их нельзя описывать как платформенные блокировки без отдельного фактического guard.

## Не трогать

- `.claude/settings.json`, user settings и live config;
- prompt-текст `run_in_background — BLOCKED`: после активации он станет правдой;
- production code до отдельного Phase 3 gate;
- #227 (model blocking), #224 (secret argv);
- 15 recommendation bundles 3B;
- live sessions, `systemctl`, restart/deploy и полный test suite.

## Tickets

### T1 — обязательный Claude `Bash` payload pilot: P1 + точные формы P2

- Files: `app/backend_claude.py`; frozen oracle
  `docs/tasks/228/acceptance/test_payload_hooks.py` не изменять в Phase 3.
- Test: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/228/acceptance/test_payload_hooks.py`
  — re-frozen RED in `4019e87e` before any Phase 3 replay (`179ce498` is
  superseded); current failure:
  `AssertionError: ClaudeBackend must install exactly one mandatory PreToolUse matcher for Bash`.
- AC: named command is green; focused
  `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_backend_claude.py docs/tasks/228/acceptance/test_payload_hooks.py`
  is green; safe cases yield no permission decision; deny reasons contain neither
  the raw command nor the oracle's unique payload markers; in an explicitly
  approved restart/reconnect window a disposable marker
  canary records `PreToolUse` + agent-visible denial and proves the Bash side effect
  absent. The canary is manual because it requires a live authenticated CLI and an
  operator-approved process window; exact pass condition is `hook event present AND
  tool_result error present AND marker absent`.
- blocked-by: none

## Rollout / rollback

The implementation commit alone has no effect on an already loaded Orchestra
process. Activation is a separate operator action after Phase 3 approval. Rollback
is the implementation commit revert plus the same controlled restart/reconnect;
the prompt must be changed to honest advisory wording if the hook is not activated
or is rolled back.

## Phase 3 acceptance addendum

После одобрения плана заказчик расширил AC до внедрения. Это разрешённая смена
контракта, поэтому RED oracle перезамораживается ещё раз до первой production
правки; `4019e87e` заменён `0d65d987`, ни одного implementation replay
от старого commit не было.

- Любой внутренний отказ managed hook — exception, неизвестный classifier result
  или timeout — возвращает корректный `PreToolUse` output **без**
  `permissionDecision`, то есть продолжает обычный permission resolver, и пишет
  `ERROR` без исходного payload. Parser выполняется с внутренним deadline; внешний
  SDK matcher timeout должен быть длиннее, чтобы wrapper успел вернуть fail-open.
- Отсутствующий/non-callable hook при сборке options не устанавливается и даёт
  `ERROR: hook unavailable ... failed open`; это не должно превращать все Bash в
  deny. SDK-level поломка вне managed wrapper остаётся отдельным внешним риском и
  проверяется canary в окне.
- Deny для `run_in_background` дословно направляет к `bg_create(type=run)`;
  recursive `rm` — к `trash`; `chmod 777/0777` — к least-privilege mode;
  `curl | shell` — скачать, проверить и только затем запускать.
- До активации grammar прогоняется над реальными `logs(type=tool,
  tool_name=Bash)`. В `report.md` идут total/parseable/blocked counts, категории и
  замаскированные точные команды; любой законный historical match блокирует rollout
  до сужения grammar.
- Unit fail-open oracle буквально исполняет harmless marker command при отсутствии
  deny и проверяет `ERROR` через logger. Stop-before-execution остаётся manual CLI
  canary в разрешённом окне.
