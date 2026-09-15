#!/bin/bash
# Одноразовая последовательность V-545: остановить Orchestra, вернуть живую БД на обычное
# имя, старую (user_version=0, не пишется с 08.09) убрать в бэкап, поднять сервис.
# Запускается ОТДЕЛЬНО от процесса Orchestra: останавливая сервис, мы обрываем сессию
# оркестратора, поэтому шаги после stop не должны зависеть от неё.
set -u
LOG=/home/kesha/orchestra/data/restart-v545-$(date +%Y%m%d-%H%M%S).log
exec >>"$LOG" 2>&1
echo "=== начало $(date -Is) ==="

R=/home/kesha/orchestra
LIVE=$R/data/storage-final-vps-20260908/orchestra.db
TARGET=$R/data/orchestra.db
STALE_BACKUP=$R/data/orchestra-stale-user_version0-$(date +%Y%m%d).db

echo "--- stop"
sudo systemctl stop orchestra && echo "stopped rc=$?"
sleep 3

echo "--- проверка, что файл больше никем не открыт"
if fuser "$LIVE" 2>/dev/null; then
    echo "ОТКАЗ: живая БД всё ещё открыта процессом; сервис не поднимаю изменённым"
    sudo systemctl start orchestra
    echo "=== прерван, состояние не менялось $(date -Is) ==="
    exit 1
fi

echo "--- целостность живой БД до переноса"
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("/home/kesha/orchestra/data/storage-final-vps-20260908/orchestra.db")
print("integrity:", c.execute("PRAGMA integrity_check").fetchone()[0])
print("user_version:", c.execute("PRAGMA user_version").fetchone()[0])
print("sessions:", c.execute("select count(*) from sessions").fetchone()[0])
c.close()
PY

echo "--- убрать устаревшую копию в бэкап"
mv -n "$TARGET" "$STALE_BACKUP" && echo "stale -> $STALE_BACKUP"

echo "--- перенести живую БД вместе с WAL/SHM"
mv "$LIVE" "$TARGET"
[ -f "$LIVE-wal" ] && mv "$LIVE-wal" "$TARGET-wal"
[ -f "$LIVE-shm" ] && mv "$LIVE-shm" "$TARGET-shm"
ls -la "$TARGET"*

echo "--- .env: путь БД на обычное имя"
cp -p "$R/.env" "$R/.env.V-545-$(date +%Y%m%d-%H%M%S).bak"
sed -i 's#^ORCHESTRA_DB_PATH=.*#ORCHESTRA_DB_PATH=/home/kesha/orchestra/data/orchestra.db#' "$R/.env"
grep -n "ORCHESTRA_DB_PATH\|ORCHESTRA_TASK_REPOSITORY" "$R/.env"

echo "--- целостность после переноса"
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("/home/kesha/orchestra/data/orchestra.db")
print("integrity:", c.execute("PRAGMA integrity_check").fetchone()[0])
print("sessions:", c.execute("select count(*) from sessions").fetchone()[0])
print("turn_usage:", c.execute("select count(*) from turn_usage").fetchone()[0])
c.close()
PY

echo "--- start"
sudo systemctl start orchestra
sleep 20
systemctl is-active orchestra
sudo journalctl -u orchestra -n 25 --no-pager | tail -25
echo "=== конец $(date -Is) ==="
