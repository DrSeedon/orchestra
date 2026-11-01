# V-1153 — фактическое состояние после рестарта

Снимок: 31.10.2026, 07:08:21 UTC. Живая БД прочитана `mode=ro` по `ORCHESTRA_DB_PATH` из окружения MainPID 3102453. Источники до/после: `.orchestra/private/V-1152/restart-before.json`, `.orchestra/private/V-1152/restart-receipt.json`. Runtime-снимок и bounded журнал сохранены локально в `.orchestra/private/V-1153/`.

| check | actual | expected | result | evidence-path |
|---|---|---|---|---|
| PID / start | 3102453; Sat Oct 31 08:01:31 CET | новый вместо 2311175; запуск после receipt | pass | `.orchestra/private/V-1153/runtime-evidence.json` |
| cwd / user | `/home/kesha/orchestra`; kesha (UID 1001) | `/home/kesha/orchestra`; kesha | pass | то же |
| root HTTP | 302, без перехода по redirect | 302 | pass | то же |
| `/proc` oom_score_adj | 800 | 800 | pass | то же |
| systemd | active/running, MainPID 3102453, User kesha, MemoryHigh 15032385536, MemoryMax 17179869184 | active; PID 3102453; указанные лимиты | pass | то же |
| cgroup Orchestra | `/sys/fs/cgroup/system.slice/orchestra.service`: high 15032385536, max 17179869184 | high 15032385536, max 17179869184 | pass | то же |
| cgroup процесса | `/system.slice/orchestra.service/orchestra-api`; leaf high/max=`max`/`max`, ограничение унаследовано от service cgroup выше | эффективный предел service cgroup | pass | то же |
| MULTICODE env | 6 ключей присутствуют; значения не читались/не сохранены | ключи только как present bool | pass | то же |
| Kesha | MainPID 1878597, active/running; процесс стартовал Fri Oct 30 04:28:59 CET | MainPID 1878597, без рестарта | pass | то же |
| startup и восстановление фоновых заданий | `Application startup complete`; `bg_jobs: restored 26 jobs, expired 0`. В bounded окне 983 записи журнала; 30 WARNING, 1 ERROR, из них после старта 25 WARNING и 0 ERROR. Единственный ERROR — Telegram polling disconnect во время shutdown до старта; после него журнал фиксирует retry. После старта также: 20 TG-bridge warnings, 2 rate_limited usage-snapshot warnings, 1 malformed JSONL skipped (1 из 3201 файлов), 1 job `nis-local-check` failed (exit 1), 1 symlink mirror skipped. | startup завершён; recovery зафиксирован | pass с перечисленными предупреждениями | `.orchestra/private/V-1153/startup-journal.txt`; `.orchestra/private/V-1153/runtime-evidence.json` |
| V1150 activation | процесс стартовал из HEAD `ffbcd8212af1a2dc78d320414bd51caab276184a`, совпадающего с baseline HEAD; `/static/js/app.js` HTTP 200, 242672 байта, SHA-256 равен локальному файлу | Python-изменения активны новым процессом; compact не запускать | pass; live compact не выполнялся | то же |
| V1151 activation | тот же новый процесс/HEAD содержит изменение `app/private_folder.py` | активировано новым процессом | pass | то же |
| V1152 activation | тот же новый процесс/HEAD содержит код маршрута Luna и сборку prompt-ов | активировано новым процессом | pass; реальный Luna spawn/provider не запускался | то же |

Cut-сессии сверены по receipt с живыми `sessions`, `logs`, `turn_usage` и журналом восстановления. `restart_cut_turns` после восстановления: 0.

| name | task | status | restart-auto-resume-or-queued-evidence | needs-parent-action |
|---|---|---|---|---|
| Orchestra-orchestrator | — | waiting | журнал `Resumed orchestrator`; после старта есть инструменты и `turn_usage end_turn` (07:06:12 UTC) | нет; ход фактически продолжен и завершён |
| materials-method-audit | V-450 | running | журнал `Resumed worker`; 177 событий после старта, включая thinking/tool и tool на 07:08:14 UTC; завершённый turn_usage пока не записан | нет по восстановлению; сессия продолжала работу на снимке |
| feat-nis-rebuild | V-34 | running | журнал `Resumed worker`; post-start tools и `turn_usage end_turn` (07:02:42 UTC), дальнейшие tool-события до 07:08:05 UTC | нет по восстановлению; несмотря на завершившийся `nis-local-check` exit 1, сессия продолжила работу |
| is1-guided-reading | V-452 | idle | журнал `Resumed worker`; post-start tools и `turn_usage end_turn` (07:07:15 UTC) | нет; ход фактически продолжен и завершён |

Журнал ограничен `2026-10-31 06:56:26–07:10:00 UTC`, только `orchestra.service`; отобраны startup/recovery markers и WARNING/ERROR-сообщения. Секретных env-значений и тел логов SQLite в evidence нет. Тестовые suite не запускались; live compact, Luna spawn и provider calls не запускались.
