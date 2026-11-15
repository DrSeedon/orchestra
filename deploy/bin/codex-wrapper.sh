#!/bin/bash
set -euo pipefail

export PATH="/home/kesha/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
REAL_CODEX_JS="/usr/lib/node_modules/@openai/codex/bin/codex.js"
PROXY_URL="${CODEX_PROXY_URL:-${HTTPS_PROXY:-${ORCHESTRA_RESIDENTIAL_PROXY_URL:-http://127.0.0.1:18080}}}"

case "${1:-}" in
  --version|-V|--help|-h|completion)
    exec /usr/bin/node "$REAL_CODEX_JS" "$@"
    ;;
esac

DISABLED_FILE="${ORCHESTRA_DISABLED_PROVIDERS_FILE:-/home/kesha/orchestra/data/disabled_providers.json}"
if [[ "${CODEX_ALLOW_WHEN_DISABLED:-0}" != "1" ]] && [[ -f "$DISABLED_FILE" ]]; then
  if _ORCH_DISABLED_FILE="$DISABLED_FILE" /usr/bin/python3 -c 'import json,os,sys; d=json.load(open(os.environ["_ORCH_DISABLED_FILE"])); items=d.get("disabled_providers",[]) if isinstance(d,dict) else d; sys.exit(0 if "codex" in items else 1)' 2>/dev/null; then
    echo "codex-wrapper: refusing execution because 'codex' is disabled in $DISABLED_FILE" >&2
    exit 77
  fi
fi

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
    sys.stderr.write("codex-wrapper: invalid proxy URL (expected scheme://host:port)\n")
    sys.exit(78)
try:
    with socket.create_connection((u.hostname, u.port), timeout=1.5):
        pass
except OSError as exc:
    sys.stderr.write(f"codex-wrapper: residential proxy {u.hostname}:{u.port} unreachable ({exc}); refusing direct datacenter egress\n")
    sys.exit(78)
up_port = int(os.environ.get("ORCHESTRA_UPSTREAM_PROXY_PORT", "10809"))
if u.hostname in {"127.0.0.1", "localhost", "::1"} and u.port == 18080 and up_port > 0:
    try:
        with socket.create_connection(("127.0.0.1", up_port), timeout=1.5):
            pass
    except OSError as exc:
        sys.stderr.write(f"codex-wrapper: upstream xray 127.0.0.1:{up_port} unreachable ({exc}); refusing execution\n")
        sys.exit(78)
PY
  export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL" ALL_PROXY="$PROXY_URL" GRPC_PROXY="$PROXY_URL"
  export http_proxy="$PROXY_URL" https_proxy="$PROXY_URL" all_proxy="$PROXY_URL" grpc_proxy="$PROXY_URL"
fi

export NO_PROXY="$SAFE_NP" no_proxy="$SAFE_NP" NO_GRPC_PROXY="$SAFE_NP" no_grpc_proxy="$SAFE_NP"
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE _ORCH_CHECK_PROXY_URL _ORCH_RAW_NP

# Enforce EVERY telemetry/update/shell-proxy-exclude invariant independently via trailing/explicit -c flags!
CANON_EXCL='shell_environment_policy.exclude=["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","GRPC_PROXY","http_proxy","https_proxy","all_proxy","grpc_proxy"]'
HAS_ANALYTICS=0
HAS_FEEDBACK=0
HAS_UPDATE=0
HAS_VALID_EXCL=0
PREV=""
for arg in "$@"; do
  if [[ "$PREV" == "-c" || "$PREV" == "--config" ]]; then
    [[ "$arg" == "analytics.enabled=false" ]] && HAS_ANALYTICS=1
    [[ "$arg" == "feedback.enabled=false" ]] && HAS_FEEDBACK=1
    [[ "$arg" == "check_for_update_on_startup=false" ]] && HAS_UPDATE=1
    if [[ "$arg" == shell_environment_policy.exclude=* ]] && [[ "$arg" == *'"HTTPS_PROXY"'* ]] && [[ "$arg" == *'"https_proxy"'* ]]; then
      HAS_VALID_EXCL=1
    fi
  fi
  PREV="$arg"
done

EXTRA_ARGS=()
[[ "$HAS_ANALYTICS" -eq 0 ]] && EXTRA_ARGS+=(-c "analytics.enabled=false")
[[ "$HAS_FEEDBACK" -eq 0 ]] && EXTRA_ARGS+=(-c "feedback.enabled=false")
[[ "$HAS_UPDATE" -eq 0 ]] && EXTRA_ARGS+=(-c "check_for_update_on_startup=false")
[[ "$HAS_VALID_EXCL" -eq 0 ]] && EXTRA_ARGS+=(-c "$CANON_EXCL")

exec /usr/bin/node "$REAL_CODEX_JS" "${EXTRA_ARGS[@]}" "$@"
