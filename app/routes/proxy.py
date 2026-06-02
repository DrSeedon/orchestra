"""Proxy & Tunnel API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.proxy_manager import proxy_manager
from app.ssh_tunnel import tunnel_status

router = APIRouter(tags=["proxy"])


@router.get("/api/proxy/list")
async def proxy_list():
    return await proxy_manager.list_proxies()


@router.post("/api/proxy/check/{proxy_id}")
async def proxy_check(proxy_id: str):
    result = await proxy_manager.check_proxy(proxy_id)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.post("/api/proxy/select/{proxy_id}")
async def proxy_select(proxy_id: str):
    result = await proxy_manager.select_proxy(proxy_id)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/api/tunnel/status")
async def api_tunnel_status():
    return tunnel_status()
