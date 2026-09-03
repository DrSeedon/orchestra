# review324 — личная память

## Эффективный ExecStart сервиса orchestra живёт в drop-in, а не в юните
`systemctl cat orchestra.service` печатает СНАЧАЛА основной юнит, drop-in'ы — в самом низу.
Обрезал вывод `head -60` → увидел `ExecStart=/home/kesha/.local/bin/uv run uvicorn app.main:app
--fd 3` и чуть не принял его за боевую строку. Реально действует
`/etc/systemd/system/orchestra.service.d/60-runtime-isolation.conf` (артефакт #303): `ExecStart=`
(сброс) + прямой `/opt/orchestra/runtimes/<ver>/bin/python -m uvicorn app.main:app --fd 3`.
Смотреть `systemctl cat <unit> | grep -n "^# /\|ExecStart"` целиком, либо `systemctl show -p ExecStart`.

## `uv run` НЕ делает exec — pid приложения отличается от pid'а, которого запустил systemd
Проверка одной командой (эмулирует контракт systemd, root не нужен):
```
LISTEN_PID=$$ exec uv run --no-project python -c "import os;print(os.environ['LISTEN_PID'],os.getpid())"
```
`uv run` → числа РАЗНЫЕ (родитель — uv); прямой путь к python → совпадают. Пригождается всякий
раз, когда что-то опирается на `LISTEN_PID == os.getpid()` (`app/fdstore.py:92`, гард TG-моста #324).

## Мутации в чужой правке — только в СВОЁМ worktree
`git checkout <их-коммит> -- <файлы>` в свой worktree → мутировать там → в конце
`git reset && git checkout -- <файл>` + удалить принесённые новые файлы. Правки в чужом worktree
запрещены, а мутировать надо реальный код.
