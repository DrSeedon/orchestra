"""Proxy & Tunnel API routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.auth import is_auth_enabled
from app.proxy_manager import proxy_manager
from app.ssh_tunnel import tunnel_status

router = APIRouter(tags=["proxy"])


def _block_if_enterprise():
    if is_auth_enabled():
        raise HTTPException(403, "Not available")


@router.get("/api/proxy/list")
async def proxy_list():
    _block_if_enterprise()
    return await proxy_manager.list_proxies()


@router.post("/api/proxy/check/{proxy_id}")
async def proxy_check(proxy_id: str):
    _block_if_enterprise()
    result = await proxy_manager.check_proxy(proxy_id)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.post("/api/proxy/select/{proxy_id}")
async def proxy_select(proxy_id: str):
    _block_if_enterprise()
    result = await proxy_manager.select_proxy(proxy_id)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/api/tunnel/status")
async def api_tunnel_status():
    _block_if_enterprise()
    return tunnel_status()
