"""Proxy & Tunnel API routes."""

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import is_owner_mode
from app.proxy_manager import proxy_manager, _parse_proxy_list
from app.ssh_tunnel import tunnel_status

router = APIRouter(tags=["proxy"])

# The .env systemd reads (EnvironmentFile + WorkingDirectory = repo root).
# parent.parent.parent: routes/ → app/ → repo root.
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


def _require_owner():
    if not is_owner_mode():
        raise HTTPException(403, "Not available")


def _set_env_proxy(url: str) -> None:
    """Rewrite ONLY the HTTPS_PROXY/HTTP_PROXY lines in .env, in place.

    WHY line-surgery (not load_dotenv/rewrite): .env holds TG/YouGile tokens —
    a full rewrite could mangle them. url=="direct" → empty value (direct exit).
    Does NOT touch os.environ: .env is the source of truth, applied on restart.
    """
    value = "" if url == "direct" else url
    text = ENV_FILE.read_text(encoding="utf-8")
    for key in ("HTTPS_PROXY", "HTTP_PROXY"):
        pattern = rf"(?m)^{key}=.*$"
        line = f"{key}={value}"
        if re.search(pattern, text):
            # lambda replacement — treat `line` literally (no \-escape in URL/pass)
            text = re.sub(pattern, lambda _m: line, text)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    # Atomic write — .env holds tokens; a crash mid-write must not corrupt it
    tmp = ENV_FILE.parent / (ENV_FILE.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, ENV_FILE)  # same fs → atomic rename


@router.get("/api/proxy/list")
async def proxy_list():
    _require_owner()
    return await proxy_manager.list_proxies()


@router.post("/api/proxy/check/{proxy_id}")
async def proxy_check(proxy_id: str):
    _require_owner()
    result = await proxy_manager.check_proxy(proxy_id)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


class SetEnvBody(BaseModel):
    id: str


@router.post("/api/proxy/set-env")
async def proxy_set_env(body: SetEnvBody):
    """Write chosen proxy into .env (HTTPS_PROXY/HTTP_PROXY). Applied on restart.

    NOT hot-switch: os.environ is untouched. .env is the single source of truth.
    """
    _require_owner()
    entry = next((e for e in _parse_proxy_list() if e.id == body.id), None)
    if not entry:
        return JSONResponse({"ok": False, "error": "proxy not found"}, status_code=404)
    _set_env_proxy(entry.url)
    return {"ok": True, "wrote": entry.url, "id": entry.id, "need_restart": True}


@router.get("/api/tunnel/status")
async def api_tunnel_status():
    _require_owner()
    return tunnel_status()
