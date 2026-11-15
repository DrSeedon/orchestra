#!/usr/bin/env bash
set -euo pipefail

IS_OFFLINE_META=0
case "${1:-}" in
  --version|-v|-V|--help|-h|agents)
    IS_OFFLINE_META=1
    ;;
  --output-format)
    if [[ "${3:-}" == "agents" || "${3:-}" == "--version" || "${3:-}" == "--help" ]]; then
      IS_OFFLINE_META=1
    fi
    ;;
esac

DISABLED_FILE="${ORCHESTRA_DISABLED_PROVIDERS_FILE:-/home/kesha/orchestra/data/disabled_providers.json}"
if [[ "$IS_OFFLINE_META" != "1" ]] && [[ "${AGY_ALLOW_WHEN_DISABLED:-0}" != "1" ]] && [[ -f "$DISABLED_FILE" ]]; then
  if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); items=d.get("disabled_providers",[]) if isinstance(d,dict) else d; sys.exit(0 if "antigravity" in items else 1)' "$DISABLED_FILE" 2>/dev/null; then
    echo "agy-wrapper: refusing execution because 'antigravity' is disabled in $DISABLED_FILE" >&2
    exit 77
  fi
fi

PROXY_URL="${ANTIGRAVITY_PROXY_URL:-${HTTPS_PROXY:-${ORCHESTRA_RESIDENTIAL_PROXY_URL:-http://127.0.0.1:18080}}}"
if [[ "${ALLOW_DATACENTER_OAUTH_EGRESS:-0}" != "1" ]]; then
  python3 - "$PROXY_URL" <<'PY'
import socket, sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
if not u.hostname or not u.port:
    sys.stderr.write(f"agy-wrapper: invalid proxy URL {sys.argv[1]!r}\n")
    sys.exit(78)
try:
    with socket.create_connection((u.hostname, u.port), timeout=1.5):
        pass
except OSError as exc:
    sys.stderr.write(f"agy-wrapper: residential proxy {u.hostname}:{u.port} unreachable ({exc}); refusing direct datacenter egress\n")
    sys.exit(78)
PY
  export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL" ALL_PROXY="$PROXY_URL" GRPC_PROXY="$PROXY_URL"
  export http_proxy="$PROXY_URL" https_proxy="$PROXY_URL" all_proxy="$PROXY_URL" grpc_proxy="$PROXY_URL"
fi
export NO_PROXY="localhost,127.0.0.1,::1,[::1]${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="$NO_PROXY" NO_GRPC_PROXY="$NO_PROXY" no_grpc_proxy="$NO_PROXY"
export AGY_CLI_DISABLE_AUTO_UPDATE=true
export SHELL="/home/kesha/.local/bin/agy-clean-shell"
export BASH_ENV="/home/kesha/.local/share/orchestra/agy-bash-clean-env.sh"
unset GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_GENAI_USE_VERTEXAI

if [[ "${1:-}" == "acp" ]]; then
  HAS_NO_TELEM=0
  for arg in "$@"; do
    if [[ "$arg" == "--disable-telemetry" ]]; then
      HAS_NO_TELEM=1
      break
    fi
  done
  if [[ "$HAS_NO_TELEM" -eq 0 ]]; then
    shift
    exec /home/kesha/.local/bin/agy.real acp --disable-telemetry "$@"
  fi
fi

exec /home/kesha/.local/bin/agy.real "$@"
