**Пилот не закрывает policy surface: 33 инвентарных пачки по-прежнему не
принуждаются платформенными hooks; реализован один вертикальный pilot только для
двух из 15 пачек, которым вообще подходят name/payload seams.**

# Phase 3 report — task #228

## Результат

T1 реализован в `app/backend_claude.py`: каждый новый или переподключённый Claude
client получает ровно один `PreToolUse` matcher для `Bash`. Это обязательная
payload-врезка до исполнения, а не прежний условный `can_use_tool` fallback.

- `run_in_background is True` → deny с `use bg_create(type=run) instead`;
- рекурсивный `rm` в заявленной мини-грамматике → deny с `trash`;
- `chmod 777/0777` → deny с least-privilege альтернативой;
- непосредственный `curl | sh/bash`, включая заявленные command-list/parenthesis
  позиции → deny с требованием сначала скачать и проверить;
- safe input → output без `permissionDecision`, поэтому обычный permission resolver
  продолжает работу;
- exception, неизвестный classifier result, внутренний timeout и отсутствующий
  classifier → `ERROR` без payload и fail-open output без deny;
- matcher не задаёт внешний timeout вообще: SDK не передаёт timeout в CLI при
  `None`; единственная временная граница нашей работы — внутренний fail-open
  `wait_for(0.1)`;
- перевод строки — command boundary; GNU `rm target -rf` и однозначные сокращения
  `--r`/`--recu` входят в recursive-rm мини-грамматику;
- heredoc bodies исключаются как данные, но команды после terminator анализируются;
- прежняя payload-проверка `run_in_background` удалена из `_make_auto_approve`;
  name-guards `AskUserQuestion`/`Monitor` и `disallowedTools` не менялись.

Все Claude-роли намеренно получают один и тот же Bash invariant. Другие runtimes и
не-Bash tools не затронуты: изменён только `app/backend_claude.py`, а matcher равен
точному имени `Bash`.

## Исторический replay grammar

Read-only scan зафиксирован на неизменяемом cutoff `logs.id <= 85251` и ограничен
строками `type='tool'`, `tool_name='Bash'`, `sessions.backend_type='claude'`:

- 2,374 Bash-вызова;
- 2,374/2,374 payload разобраны как JSON;
- 1,073/2,374 (45.2%) команд многострочные;
- classifier predicts 28 `recursive_rm`, 0 `world_writable`, 0 `curl_pipe_shell`;
- после ручной adjudication text-reference содержит 34 настоящих recursive-rm;
- TP 28, FP 0, FN 6 → **precision 100.0%, recall 82.4%**;
- classifier exceptions 0, JSON parse failures 0;
- single-pass classifier interval: p50 0.226 ms, p99 1.061 ms, max 1.753 ms;
  это не end-to-end latency и не замер event-loop scheduling.

Все 28 срабатываний проверены вручную и являются физически исполняемым recursive
`rm`. Два regex-only text-detector match (`68878`, `69082`) исключены из знаменателя,
а не посчитаны пропусками: текущие Bash-вызовы лишь записывают текст `rm -rf` в тела
создаваемых heredoc-скриптов и физически его не исполняют. Шесть FN честно остаются
за границей мини-грамматики: один `rm -rf` в кавычках вложенного SSH shell (`75509`),
четыре тела `for …; do rm -rf …; done` (`76072`, `77322`, `78023`, `78810`) и один
`find -exec rm -rf` wrapper (`82349`).
Поэтому 82.4% — измеренная полнота относительно adjudicated detector candidates,
а не обещание shell sandbox.

До исправления newline было 14 TP и 22 regex-miss; после command-boundary fix стало
29 кандидатов. Heredoc masking убрал два фактических false positive и вернул один
раньше unparsable настоящий вызов, итог — 28 TP / 6 FN / 0 FP. Замаскированные
точные команды, ids и расчёт находятся в `probes/historical-bash-scan.md`;
воспроизводящий read-only скрипт — `probes/historical_bash_scan.py`. Оба артефакта
перед коммитом проходят shape-based token scan.

Codex дополнительно нашёл lawful false positive вне исторических matches:
`chmod --reference=/tmp/ref 777` использует `777` как filename, не mode. Parser
сужен: `--reference=...` завершает chmod mode classification; обычный
`/bin/chmod -R 0777 /tmp/x` продолжает блокироваться.

## Доказательства и тесты

### RED до production-правки

Frozen oracle `0d65d987` перед реализацией:

```text
FFF                                                                      [100%]
3 failed in 1.43s
AssertionError: ClaudeBackend must install exactly one mandatory PreToolUse matcher for Bash
```

Oracle после реализации остаётся byte-for-byte равен версии из `0d65d987`.

Независимое ревью добавило отдельный RED oracle, не меняя frozen-файл:

```text
docs/tasks/228/acceptance/test_payload_hooks_followup.py
FF.                                                                      [100%]
2 failed, 1 passed in 1.43s
E assert 0.25 is None
E assert None == 'recursive_rm'  # set -e\nrm -rf ...
```

RED timeout/newline commit — `1b4af662`; heredoc false-positive RED — `4b3e4787`.

### GREEN

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q \
  tests/test_backend_claude.py \
  docs/tasks/228/acceptance/test_payload_hooks.py \
  docs/tasks/228/acceptance/test_payload_hooks_followup.py
..............................                                           [100%]
30 passed in 9.47s
```

Тот же focused command перед commit дал ещё два полных зелёных повтора:
`30 passed in 9.21s` и `30 passed in 9.00s`; Python compile-check завершился
`COMPILE_OK`.

Frozen test затем прошёл три последовательных async-repeat (`3 passed in 1.50s`,
`1.37s`, `1.47s`); после каждой мутации также был
обязательный green repeat после `mv` + `touch`.

Fail-open probe дал четыре громких события без payload:

```text
ERROR ... failed open (RuntimeError): classifier failure
ERROR ... failed open: invalid classifier result
ERROR ... failed open (TimeoutError): classifier deadline exceeded
ERROR ... hook unavailable; failed open: classifier is not callable
exception/invalid/timeout/missing: continued=True
```

Acceptance oracle после каждого output исполнил harmless Bash marker и проверил
содержимое, поэтому fail-open доказан не только shape-ом. Полный вывод —
`probes/payload-hook-fail-open.raw.txt`.

### Мутации

Обе мутации исполнялись одной командой `cp → mutate → test → mv → touch → grep →
green repeat`:

1. Удалить только wiring `PreToolUse` → `2 failed, 1 passed`; после отката
   `restored_wiring_marker_count=1`, затем `3 passed`.
2. Составная: удалить wiring и вернуть payload-guard в `can_use_tool` → снова
   `2 failed, 1 passed`; значит fallback не подменяет обязательную врезку. После
   отката hook marker `1`, мутант marker `0`, затем `3 passed`.

Полный компактный вывод — `probes/payload-hook-mutations.raw.txt`.

Четыре follow-up мутации отдельно доказали новые клаузы: возврат matcher timeout
`0.25` краснит assertion `0.25 is None`; поглощение newline как whitespace краснит
два command-boundary случая; возврат stop-at-first-operand краснит
`rm target -rf`; exact-only `--recursive` краснит `rm --r`. Каждый rollback завершён
`touch`, marker-count и `3 passed`. Вывод —
`probes/independent-review-regressions.raw.txt`.

## Pre-mortem следующего потребителя

| Риск | Наблюдаемый симптом | Проверка |
|---|---|---|
| Hook не установлен или duplicate matcher | payload снова исполняется либо callback вызывается дважды | frozen oracle требует ровно один Bash matcher; wiring mutation краснеет |
| Наш classifier ломает весь Bash | разрешённые команды массово denied/timeout | exception, junk, timeout и missing-hook исполняют marker и логируют ERROR fail-open |
| Короткий outer timeout снова fail-closed | Bash ждёт confirmation вместо исполнения | follow-up oracle требует `matcher.timeout is None`; 1-секундный classifier обрывается внутренним 0.1-секундным fail-open |
| Newline или GNU option обходят deny | `set -e\nrm -rf`, `rm target -rf`, `rm --r` исполняются | follow-up oracle + три независимые мутации краснеют |
| Heredoc text даёт false positive | создание безопасного script-файла denied | body-only case обязан быть `None`, команда после terminator — `recursive_rm`; historical FP 0 |
| Parser блокирует законный chmod | `777` filename после `--reference` denied | контрпример Codex воспроизведён RED, после fix обе reference-формы `None`, обычный `0777` всё ещё `world_writable` |
| Старый `can_use_tool` кажется рабочим owner-ом | hook пропал, тесты остаются зелёными | составная мутация с восстановленным fallback остаётся красной |
| Код смержен, но живые clients продолжают старую политику | prompt пишет BLOCKED, а side effect исполняется | rollout не заявлен: нужен отдельный restart/reconnect window и CLI marker-canary |

## Codex review

Раунд 1 истёк по 10-минутному timeout без вердикта, но его command trace дал
контрпример `curl x | (bash)`; потеря pipe через открывающую скобку исправлена.
Раунд 2 дал `APPROVED` с проверяемой дословной цитатой и нашёл suggestion про
`chmod --reference=...`; suggestion принят и исправлен. Раунд 3 снова написал
`APPROVED` и подтвердил fix, однако его якобы дословная цитата отсутствует во всех
reviewed artifacts. По evidence gate этот финальный approval не засчитывается;
потолок трёх раундов исчерпан, четвёртый не запускался. Квалифицирующего Codex-
вердикта именно на post-fix diff нет; финальный gate закрыт отдельным независимым
Opus-review ниже. Полный журнал — `codex-review-impl.md`.

## Independent Phase 3 review

Независимый Opus-review `review-independent-phase3.md` прогоном нашёл два block:
explicit `HookMatcher(timeout=0.25)` fail-closed в CLI и пропуск newline command
boundaries (14 caught / 22 missed у reviewed build). Medium-находки — trailing GNU
rm options и abbreviated `--recursive`; low — слишком широкое имя
`download_execute`. Все четыре направления исправлены: внешний deadline снят,
newline сохранён как punctuation boundary, GNU forms добавлены, class/reason сужены
до `curl_pipe_shell` / `Direct curl-to-shell`.

Повторная независимая проверка дельты `1b4af662 + 4b3e4787 + 67840dff` дала
**APPROVED**. Прод-форма на slow ALLOW/DENY ждала полные 65 секунд: ALLOW исполнил
команду, DENY остановил её, то есть внешнего дедлайна нет. Именованный набор дал
`30 passed in 9.30s`; четыре независимые мутации покраснели по своим причинам и
после каждого отката вернулись к `30 passed`. Исторический replay независимо
совпал до id: 2,374 команд, TP 28 / FP 0 / FN 6, precision 100.0%, recall 82.35%,
регрессий `old blocked → new allowed` — 0. Три проверенных deny-текста дошли до
модели через живой CLI; для `chmod` побочный эффект не произошёл (`dir_mode=0o755`).

Два безопасно направленных edge case оставлены известными, а не замолчаны:

- комментарий с непарной кавычкой при `lexer.commenters = ""` даёт громкий
  parser error и fail-open; на историческом корпусе — 0 вхождений;
- неквотированный `<<` в арифметическом сдвиге маскирует остаток команды и даёт
  fail-open; на историческом корпусе — 0 вхождений.

Полный первичный и повторный вердикт — `review-independent-phase3.md`. Это пилот на
два инварианта, а не закрытие policy surface: 33 пачки остаются вне hooks.

## Breaking / rollout / rollback

Source behavior меняется для новых и переподключённых Claude clients: выбранные
Bash payloads будут denied. Текущие живые clients не изменены; settings, service и
restart этой работой не тронуты. Полный suite не запускался по прямой границе задачи.

Activation остаётся отдельным операторским окном: merge → контролируемый
restart/reconnect → disposable Claude marker-canary с тройным условием `hook event
present AND tool_result error present AND side-effect marker absent`. Если canary
не проходит, rollback — revert implementation commit + тот же контролируемый
restart/reconnect, а prompt `run_in_background — BLOCKED` должен быть заменён на
честную advisory-формулировку до восстановления enforcement.

## Files (`0454aba2..working tree`, task-owned paths: +1,490/−4)

| File | + | − | Назначение |
|---|---:|---:|---|
| `app/backend_claude.py` | 260 | 4 | managed hook, parser и wiring |
| `CHANGELOG.md` | 8 | 0 | source behavior и rollout boundary |
| `docs/tasks/228/acceptance/test_payload_hooks_followup.py` | 84 | 0 | independent-review RED/GREEN oracle |
| `docs/tasks/228/codex-review-impl.md` | 54 | 0 | независимый review и evidence audit |
| `docs/tasks/228/review-independent-phase3.md` | 449 | 0 | independent review + approved re-review |
| `docs/tasks/228/probes/historical_bash_scan.py` | 199 | 0 | read-only precision/recall replay |
| `docs/tasks/228/probes/historical-bash-scan.md` | 72 | 0 | cutoff/counts/exact masked hits |
| `docs/tasks/228/probes/payload-hook-fail-open.raw.txt` | 19 | 0 | fail-open evidence |
| `docs/tasks/228/probes/payload-hook-mutations.raw.txt` | 51 | 0 | mutation evidence |
| `docs/tasks/228/probes/independent-review-regressions.raw.txt` | 62 | 0 | follow-up mutation evidence |
| `docs/tasks/228/report.md` | 232 | 0 | этот отчёт |
