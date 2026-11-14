"""Shared subprocess env for MCP stdio servers — leaf client configuration.

The external ai-proxy-manager owns route selection; this module only propagates
the current client environment into MCP subprocesses.
"""

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).parent.parent)
_MCP_SCRIPT = str(Path(__file__).parent / "mcp_stdio.py")
MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]

# Propagate proxy + auth token to the MCP subprocess so it can reach Anthropic
# and call back to Orchestra's own API with internal auth.
#
# `ORCHESTRA_*` belong here for a different reason, and it is a defect we paid for:
# the live process was moved onto another database and another task repository by
# environment variables, and subprocesses did not inherit them. A subprocess then
# opened the DEFAULT `data/orchestra.db` — non-empty and still at `user_version=0` —
# and every start died on the schema guard (`app/db.py:73`,
# `database schema needs offline migration before starting Orchestra`). That is what
# broke `codex_review` for every project on 12.09.2026, and it looked like a review
# problem rather than a wrong database. Whatever selects state for the parent must
# select the same state for its children.
MCP_BASE_ENV = {"PYTHONPATH": _PROJECT_ROOT}
for _k in (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "INTERNAL_TOKEN",
    "ORCHESTRA_DB_PATH",
    "ORCHESTRA_TASK_REPOSITORY",
    "ORCHESTRA_TASK_PREFIX",
    "ORCHESTRA_RESIDENTIAL_PROXY_URL",
    "CLAUDE_PROXY_URL",
    "CODEX_PROXY_URL",
    "GROK_PROXY_URL",
    "ANTIGRAVITY_PROXY_URL",
    "ORCHESTRA_DISABLED_PROVIDERS",
    "ORCHESTRA_DISABLED_PROVIDERS_FILE",
    "ALLOW_DATACENTER_OAUTH_EGRESS",
    "ORCHESTRA_ENFORCE_PROVIDER_EGRESS",
    "ORCHESTRA_EGRESS_VERIFY_TTL_SECONDS",
):
    if os.environ.get(_k):
        MCP_BASE_ENV[_k] = os.environ[_k]

# Ensure local Orchestra callbacks (`127.0.0.1:8888`) never ride an inherited HTTP proxy.
_existing_no_proxy = MCP_BASE_ENV.get("NO_PROXY") or os.environ.get("no_proxy") or ""
_loopback = ["localhost", "127.0.0.1", "::1", "[::1]"]
_parts = [p.strip() for p in _existing_no_proxy.split(",") if p.strip() and p.strip() != "*"]
for _host in _loopback:
    if _host.lower() not in {p.lower() for p in _parts}:
        _parts.append(_host)
MCP_BASE_ENV["NO_PROXY"] = ",".join(_parts)
MCP_BASE_ENV["no_proxy"] = MCP_BASE_ENV["NO_PROXY"]
