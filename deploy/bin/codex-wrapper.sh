#!/usr/bin/env bash
set -euo pipefail

REAL_CODEX_JS="/usr/lib/node_modules/@openai/codex/bin/codex.js"
PROXY_URL="${CODEX_PROXY_URL:-${HTTPS_PROXY:-${ORCHESTRA_RESIDENTIAL_PROXY_URL:-http://127.0.0.1:18080}}}"

case "${1:-}" in
  --version|-V|--help|-h|completion)
    exec /usr/bin/node "$REAL_CODEX_JS" "$@"
    ;;
esac

if [[ "${ALLOW_DATACENTER_OAUTH_EGRESS:-0}" != "1" ]]; then
  python3 - "$PROXY_URL" <<'PY'
import socket, sys
from urllib.parse import urlparse

u = urlparse(sys.argv[1])
if not u.hostname or not u.port:
    sys.stderr.write(f"codex-wrapper: invalid proxy URL {sys.argv[1]!r}\n")
    sys.exit(78)
try:
    with socket.create_connection((u.hostname, u.port), timeout=1.5):
        pass
except OSError as exc:
    sys.stderr.write(f"codex-wrapper: residential proxy {u.hostname}:{u.port} unreachable ({exc}); refusing direct datacenter egress\n")
    sys.exit(78)
PY
  export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL" ALL_PROXY="$PROXY_URL" GRPC_PROXY="$PROXY_URL"
  export http_proxy="$PROXY_URL" https_proxy="$PROXY_URL" all_proxy="$PROXY_URL" grpc_proxy="$PROXY_URL"
fi

LOOPBACK_NP="localhost,127.0.0.1,::1,[::1]"
if [[ -n "${NO_PROXY:-}" ]]; then
  export NO_PROXY="${LOOPBACK_NP},${NO_PROXY}"
else
  export NO_PROXY="$LOOPBACK_NP"
fi
export no_proxy="$NO_PROXY" NO_GRPC_PROXY="$NO_PROXY" no_grpc_proxy="$NO_PROXY"

HAS_SHELL_EXCL=0
for arg in "$@"; do
  if [[ "$arg" == *"shell_environment_policy.exclude="* ]]; then
    HAS_SHELL_EXCL=1
    break
  fi
done

if [[ "$HAS_SHELL_EXCL" -eq 0 ]]; then
  exec /usr/bin/node "$REAL_CODEX_JS" \
    -c analytics.enabled=false \
    -c feedback.enabled=false \
    -c check_for_update_on_startup=false \
    -c 'shell_environment_policy.exclude=["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","GRPC_PROXY","http_proxy","https_proxy","all_proxy","grpc_proxy"]' \
    "$@"
else
  exec /usr/bin/node "$REAL_CODEX_JS" "$@"
fi
