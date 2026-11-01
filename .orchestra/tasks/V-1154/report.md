# V-1154 — disk inventory and scoped cleanup handoff

## Исходная фаза

Полный исходный отчёт на 147 строк сохранён побайтно: `.orchestra/private/V-1154/report-full-147.md`; SHA-сравнение исходника и копии прошло до сокращения. Все подробные числовые таблицы/paths остались в private inventory.

| область | исходный allocated_bytes | coverage / состояние | eligible |
|---|---:|---|---|
| linked worktrees | 9119084544; 16 project roots | merge state не оценивался; все удержаны | no |
| основные project checkouts | 85476478976; 9 корней | source checkouts удержаны | no |
| `~/.cache` | 43261157376; 130 top-level subdirs | UV 34397569024 | только штатный UV prune |
| `orchestra/data` | 35182477312 lower bound | 1 Permission denied | no |
| `/tmp` | 7687278592 lower bound | 11098 children; 13 Permission denied | только подтверждённые own scopes |
| Trash | 52011008; 15 items | даты/размеры в protected evidence; не очищалась | no |

Первоначальный `uv cache prune` запускался ровно один раз: RC=2, timeout 10s на lock; UV cache до/после 34397569024 B, три открытых lock fd зафиксированы. Повторов/обхода не было.

## Собственные scope

| path | allocated before → after | действие / подтверждение |
|---|---:|---|
| `/home/kesha/.cache/pip` | 338067456 → 2105344 B | штатный pip cache purge RC=0, `Files removed: 261`, stderr пустой; после purge pip сообщил 0 HTTP files/0 wheels. Root/компоненты без symlink, descendants на одном device; process scan, scoped lsof/fuser не нашли активную загрузку/install/open refs. `sudo -n` недоступен (`no new privileges`). |
| `/tmp/orchestra-v1151-host-focused` | 220061696 → 119816192 B | `accept.py:40` и green/full host receipt подтвердили pytest basetemp. `rm-i` только по NUL manifest для 9305 regular files (100245504 B), RC=0; stdout пустой, stderr prompts 1300431 B. Все 265 symlinks и 9656 entries под/на их targets сохранены; прямые regular target data 72511488 B. Root kesha:kesha mode0700; acceptance PID, session path и scoped fuser refs не найдены. |
| `/home/kesha/.cache/electron` | 527921152 → 8192 B | удалены только 4 vendor ZIP через `rm-i`, RC=0; stdout пустой, stderr prompts 608 B. Все файлы были Electron v45.0.0 download ZIPs: linux-x64, darwin-arm64, darwin-x64, win32-x64; central-directory listings не содержали traversal paths. Symlink/special files отсутствовали; один пустой hash-named directory оставлен. Scoped lsof/fuser и process/session checks не нашли активного download/install/open ref. |

Для Electron до удаления записаны SHA-256, размеры, archive entry paths/count/types и версии в `electron-before-manifest.json`; checksum-файлов не было. Первая `sha256sum -c` попытка из repo root получила RC=1 из-за относительного basename; удаление не запускалось. Проверка из private-dir прошла RC=0 перед `rm-i`. Архивы не распаковывались и не исполнялись. PIP/Electron cache CLI/purge не запускал package installation/download.

## df и предел результата

| snapshot | used_bytes | available_bytes | Use% | evidence |
|---|---:|---:|---:|---|
| первая инвентаризация | 292964093952 | 17930543104 | 95% | `inventory-initial.txt` |
| до Electron cleanup | 292566761472 | 18330992640 | 95% | `df-before-electron-delete.txt` |
| после Electron cleanup | 292040536064 | 18854100992 | 94% | `df-after-electron-cleanup.txt` |

Порог `<95%` достигнут; больше ничего не чистилось. Electron ZIP allocated diff: 527912960 B; global df used уменьшился на 526225408 B. Отличие и прежние межснимочные колебания не приписаны cleanup.

V-1150/V-1152 `accept.py` не указывают дополнительных `/tmp`/`--basetemp` scope. Tests, installs, UV commands/process-control, service/config/credential changes: none. Exact RC/stdout/stderr, manifests, lsof/fuser/process receipts, df и подробная исходная фаза: `.orchestra/private/V-1154/` (включая `electron-delete-manifest-check-failed.txt` и corrected check outputs). Secret-shape scan: private evidence и tracked report — 0 findings.
