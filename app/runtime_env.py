"""Shared subprocess env for MCP stdio servers — leaf module.

Lives outside manager.py so proxy_manager (which mutates the proxy vars at
runtime) doesn't have to lazy-import the manager module.
"""

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).parent.parent)
_MCP_SCRIPT = str(Path(__file__).parent / "mcp_stdio.py")
MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]

# Propagate proxy + auth token to the MCP subprocess so it can reach Anthropic
# and call back to Orchestra's own API with internal auth
MCP_BASE_ENV = {"PYTHONPATH": _PROJECT_ROOT}
for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
    if os.environ.get(_k):
        MCP_BASE_ENV[_k] = os.environ[_k]
