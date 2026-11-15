#!/bin/bash
set -euo pipefail

export PATH="/home/kesha/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

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
  if _ORCH_DISABLED_FILE="$DISABLED_FILE" /usr/bin/python3 -c 'import json,os,sys; d=json.load(open(os.environ["_ORCH_DISABLED_FILE"])); items=d.get("disabled_providers",[]) if isinstance(d,dict) else d; sys.exit(0 if "antigravity" in items else 1)' 2>/dev/null; then
    echo "agy-wrapper: refusing execution because 'antigravity' is disabled in $DISABLED_FILE" >&2
    exit 77
  fi
fi

PROXY_URL="${ANTIGRAVITY_PROXY_URL:-${HTTPS_PROXY:-${ORCHESTRA_RESIDENTIAL_PROXY_URL:-http://127.0.0.1:18080}}}"
SAFE_NP="$(_ORCH_RAW_NP="${NO_PROXY:-${no_proxy:-}}" /usr/bin/python3 - <<'PY'
import ipaddress, os
SAFE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".test", ".invalid")
kept, seen = [], set()
for part in os.environ.get("_ORCH_RAW_NP", "").split(","):
    tok = part.strip()
    if not tok or "*" in tok or "/" in tok:
        continue
    low = tok.lower()
    h = low[1:low.index("]")] if low.startswith("[") and "]" in low else (low.split(":", 1)[0] if low.count(":") == 1 else low)
    if not h or h.startswith("."):
        continue
    ok = h in {"localhost", "127.0.0.1", "::1"}
    if not ok:
        try:
            ip = ipaddress.ip_address(h)
            ok = ip.is_loopback or ip.is_private
        except ValueError:
            ok = "." in h and any(h.endswith(s) for s in SAFE_SUFFIXES)
    if ok and low not in seen:
        kept.append(tok)
        seen.add(low)
for req in ("localhost", "127.0.0.1", "::1", "[::1]"):
    if req not in seen:
        kept.append(req)
        seen.add(req)
print(",".join(kept))
PY
)"

if [[ "${ALLOW_DATACENTER_OAUTH_EGRESS:-0}" != "1" ]]; then
  _ORCH_CHECK_PROXY_URL="$PROXY_URL" /usr/bin/python3 - <<'PY'
import os, socket, sys
from urllib.parse import urlparse

raw = os.environ.get("_ORCH_CHECK_PROXY_URL", "")
u = urlparse(raw)
if u.scheme.lower() not in {"http", "https", "socks5", "socks5h"} or not u.hostname or not u.port:
    sys.stderr.write("agy-wrapper: invalid proxy URL (expected scheme://host:port)\n")
    sys.exit(78)
try:
    with socket.create_connection((u.hostname, u.port), timeout=1.5):
        pass
except OSError as exc:
    sys.stderr.write(f"agy-wrapper: residential proxy {u.hostname}:{u.port} unreachable ({exc}); refusing direct datacenter egress\n")
    sys.exit(78)
up_port = int(os.environ.get("ORCHESTRA_UPSTREAM_PROXY_PORT", "10809"))
if u.hostname in {"127.0.0.1", "localhost", "::1"} and u.port == 18080 and up_port > 0:
    try:
        with socket.create_connection(("127.0.0.1", up_port), timeout=1.5):
            pass
    except OSError as exc:
        sys.stderr.write(f"agy-wrapper: upstream xray 127.0.0.1:{up_port} unreachable ({exc}); refusing execution\n")
        sys.exit(78)
PY
  export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL" ALL_PROXY="$PROXY_URL" GRPC_PROXY="$PROXY_URL"
  export http_proxy="$PROXY_URL" https_proxy="$PROXY_URL" all_proxy="$PROXY_URL" grpc_proxy="$PROXY_URL"
fi
export NO_PROXY="$SAFE_NP" no_proxy="$SAFE_NP" NO_GRPC_PROXY="$SAFE_NP" no_grpc_proxy="$SAFE_NP"
export AGY_CLI_DISABLE_AUTO_UPDATE=true
export SHELL="/home/kesha/.local/bin/agy-clean-shell"
export BASH_ENV="/home/kesha/.local/share/orchestra/agy-bash-clean-env.sh"
unset GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_GENAI_USE_VERTEXAI _ORCH_CHECK_PROXY_URL _ORCH_RAW_NP

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
