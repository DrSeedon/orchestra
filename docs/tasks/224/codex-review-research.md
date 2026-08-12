## Summary

Главный вывод исследования опровергнут: `--profile` недоступен для `app-server`, но это не закрывает файловый маршрут Codex. `app-server` штатно читает базовый `$CODEX_HOME/config.toml`; это прямо указано в его `--help`. Поэтому рекомендация wrapper-script преждевременна.

## Findings

blocking: docs/tasks/224/research.md:60 — утверждение «единственный файловый механизм Codex — профиль» неверно: `codex app-server --help` подтверждает загрузку базового `$CODEX_HOME/config.toml`, а `--profile` лишь наслаивает `<name>.config.toml` поверх него → проверить отдельный `CODEX_HOME` на сессию с `config.toml`; учесть auth/session storage и fail-loud запуск MCP. `codex mcp add` — лишь способ записать тот же config, а не отдельный runtime-механизм.

blocking: docs/tasks/224/research.md:257 — вывод «F3 и F4 закрывают обе симметричные опции» логически не следует из экспериментов: F3 проверяет только профиль, не базовый config → не переходить к wrapper-дизайну до прогона `CODEX_HOME=<private-dir> codex app-server --stdio` с MCP из `config.toml`.

blocking: docs/tasks/224/research.md:263 — wrapper-файл с режимом 700 не выполняет заявленный threat model «агент проекта A читает секреты проекта B»: все агенты работают как `kesha`, поэтому могут читать и исполнять файлы владельца `kesha`; документ сам признаёт это ниже, но всё равно называет набор «минимальным полным» → либо сузить security claim до предотвращения случайного попадания в `ps`, либо проектировать настоящую изоляцию процессов/uid.

blocking: docs/tasks/224/research.md:95 — `export` внутри генерируемого shell-скрипта создаёт новый injection/correctness seam: кавычки, переводы строк, `$()`, обратные кавычки и shell-метасимволы в произвольном значении могут изменить скрипт или испортить credential; простой marker-пробник этого не проверяет → не генерировать shell source из значений; если wrapper останется, читать структурированный файл и передавать окружение через `execve` без shell-интерполяции.

suggestion: docs/tasks/224/research.md:105 — F5 проверен только через `codex exec`, тогда как production использует `app-server`; автор корректно помечает перенос как LIKELY, но рекомендация уже зависит от него → до гейта проверить restart/reconnect MCP, несколько одновременных сессий, удаление/повреждение wrapper и повторный spawn сервера именно через app-server.

suggestion: docs/tasks/224/research.md:174 — `db.add_log` подтверждён как единственный INSERT в разрешённом коде, но это доказывает только единый seam персистенции, не единый seam распространения → понизить F9 до «CONFIRMED для записей в logs» и отдельно доказать, что live SSE/TG callbacks не получают исходный event до `add_log`. История и RAG, читающие уже сохранённые строки, будут защищены; текущий model context — нет, что документ признаёт.

blocking: docs/tasks/224/research.md:182 — 0.40% измеряет частоту совпадений, а не безопасность или ложные срабатывания. Суффикс/список пропускает реальные формы `COOKIE`, `SESSION`, `CREDENTIAL`, `PRIVATE_KEY`, `PASSPHRASE`, `DATABASE_URL`, `CONNECTION_STRING`, signed webhook URLs/DSN и `Authorization: Bearer`; одновременно совпадения `TOKEN`, `BY_TOKEN`, `PASSWORD` могут быть счётчиками, именами полей, примерами или политиками → собрать размеченную выборку true/false positives и тестировать форматы JSON, TOML, shell, headers и URL отдельно.

suggestion: docs/tasks/224/research.md:204 — фраза «маскирование не перепашет журнал» не следует из малого процента строк: две затронутые `user_message` и lifecycle-записи могут быть семантически критичнее сотен tool results, а маскирование generic `TOKEN` может портить диагностические данные → оценивать повреждение по содержанию и типу, а не только по числу строк.

suggestion: docs/tasks/224/research.md:277 — ссылка `app/manager.py:393-415` неточна: `_make_mcp_config` начинается раньше указанного диапазона; диапазон захватывает не весь заявленный источник → обновить ссылки по текущим строкам. Остальные проверенные ссылки (`backend_codex.py:413`, `_mcp_config_args:1558`, `db.add_log:1353`) корректны.

question: docs/tasks/224/research.md:288 — документ одновременно говорит, что правка требует рестарта, и рекомендует её как решение, хотя текущие ограничения запрещают рестарт; кроме того, утверждение «рестарт чинит только новые коннекты» двусмысленно, поскольку рестарт самого сервиса обычно уничтожает старые backend-процессы → отделить correctness решения от допустимого окна применения и описать проверяемое состояние после будущего разрешённого запуска, без предложения рестарта сейчас.

## Verdict

Не одобрено. Load-bearing claim о невозможности файлового конфига Codex опровергнут собственным CLI: app-server читает `$CODEX_HOME/config.toml`. Из-за этого wrapper выбран до проверки более прямого механизма, а его защита не соответствует кросс-проектному threat model и добавляет shell-injection seam. Исследование нужно пересобрать вокруг app-server + отдельного `CODEX_HOME`, затем заново сравнить варианты.

## Round (2026-08-12T10:35:26Z)

## Summary

Two new blocking issues remain in F14’s proposed integration: copying the base Codex config would reintroduce global MCP servers into every worker, and token accounting will not automatically follow a child-only `CODEX_HOME`.

The wrapper may reasonably remain as a documented fallback if it uses structured input plus `execve` and is tested under `app-server`.

## Findings

blocking: docs/tasks/224/research.md:F14 — generating each worker’s config “из живого базового” would copy global `mcp_servers.yandex-direct` and `openaiDeveloperDocs` into every worker, bypassing the deliberate `context.mcp_servers` selection in `runtime_registry.py:230-245` and potentially restoring cross-project tool/secret exposure → parse and construct an allowlisted config: preserve required scalar settings such as `project_doc_max_bytes`, but emit only that worker’s trusted `context.mcp_servers`; do not clone global MCP or unrelated `[projects.*]` entries.

blocking: docs/tasks/224/research.md:F14 — “учёт токенов поедет за каталогом сам” is wrong for the proposed child-only environment. `backend_codex.py:1534` reads `os.environ` of the long-lived Orchestra Python process, while `connect()` passes a separate `env` mapping only to `create_subprocess_exec` at lines 415-443. Setting `CODEX_HOME` there does not mutate `os.environ`, so `_runtime_context()` will continue searching the shared home and can lose rollout/token accounting → store the per-backend Codex home on `CodexBackend` and use that path directly in both child environment and `_runtime_context()`.

suggestion: docs/tasks/224/research.md:F14 — “Codex writes trust_level, sessions, history, therefore the copied config diverges” conflates the directory with `config.toml`; sessions/history are separate state, while the recommendation says only `config.toml` is regenerated → identify exactly which process writes which file, and preserve the per-agent sessions directory across reconnects so resume IDs remain discoverable.

suggestion: docs/tasks/224/research.md:20-24 — H3 remains labelled **CONFIRMED** “на любом рантайме”, although F5 explicitly says it was tested only with `codex exec`, not production `app-server`, and shows no Claude measurement → mark H3 **PARTIALLY CONFIRMED / LIKELY for app-server** until the stated Phase 3 probe.

suggestion: docs/tasks/224/research.md:F10 — “+17 строк сверх 323” compares 323 matches from an 80,880-row snapshot with coverage shapes measured over 81,207 rows; it therefore does not establish a strict additive delta, and some named categories overlap within the same row → report the snapshots separately or rerun both rules over one fixed snapshot and compute set difference.

suggestion: docs/tasks/224/research.md:F9 — a shared sanitizer should be applied to the `content` leaf before all four `broker.publish` calls, not generically to the entire payload: metadata such as IDs, event types and patch structure must remain stable → state this boundary explicitly and test persisted completed events plus ephemeral `tool_stream`/`subagent_event`.

## Re-review status

1. CODEX_HOME alternative — **FIXED**, with the two new integration bugs above.
2. “F3+F4 close both options” — **FIXED**.
3. Wrapper shell injection — **FIXED**; retaining an `execve` fallback is reasonable.
4. Threat-model overclaim — **FIXED**.
5. `add_log` as the sole egress seam — **FIXED**; the live-broker correction matches `session.py`.
6. Explicit-list coverage/blast radius — **FIXED in design**, but the cross-snapshot delta remains unsupported.
7. Restart semantics — **FIXED** based on the documented cgroup measurement; no restart is proposed now.
8. Semantic corruption risk — **FIXED** by separating blast radius from coverage, subject to fixed-snapshot validation.
9. File reference — **WITHDRAWN**. `app/manager.py:393-415` is correct; `_make_mcp_config` begins exactly at line 393. My round-1 finding was wrong.
10. Deployment-window ambiguity — **FIXED**.

## Verdict

Not approved yet because the current primary recommendation would copy global MCP servers into per-agent configs and would break rollout discovery/token accounting unless `CodexBackend` tracks its own home explicitly.

## Round 2

The new F9 and restart corrections are substantively sound. F14 proves the platform mechanism, but its production integration needs the two blocking corrections above.
