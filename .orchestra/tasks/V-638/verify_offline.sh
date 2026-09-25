#!/usr/bin/env bash
# Запускается через `sudo unshare -n` (пустой network namespace: ни маршрутов, ни DNS).
set -uo pipefail
ARCHIVE="$1"; W=/tmp/orch-offline-verify-$$; PORT=18899
ip link set lo up
echo "--- network check: pypi.org must be unreachable"
python3 - <<'PY'
import socket
try:
    socket.create_connection(("pypi.org", 443), timeout=3); print("REACHABLE (bad)")
except OSError as e: print("unreachable OK:", e)
PY
mkdir -p $W && tar -xzf "$ARCHIVE" -C $W
B=$W/$(ls $W)
"$B/deploy/install-offline.sh" --dir $W/inst --user orchtest --port $PORT --no-service 2>&1 | tail -15
echo "--- start service"
cd $W/inst
runuser -u orchtest -- bash -c "set -a; . ./.env; set +a; exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT" > $W/uvicorn.log 2>&1 &
PID=$!
for i in $(seq 1 30); do sleep 1; c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/ ); [ "$c" != 000 ] && break; done
echo "HTTP / -> $c (after ${i}s)"
curl -s -u "admin:$(grep ^DASHBOARD_PASSWORD .env | cut -d= -f2)" -o /dev/null -w 'HTTP / with auth -> %{http_code}\n' http://127.0.0.1:$PORT/
tail -5 $W/uvicorn.log
pkill -P $PID; kill $PID 2>/dev/null; wait 2>/dev/null
du -sh $W/inst/.venv
