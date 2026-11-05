#!/usr/bin/env bash
set -euo pipefail
orchestra_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$orchestra_root"
exec "$orchestra_root/.venv/bin/python" -m app.antigravity_auth "$@"
