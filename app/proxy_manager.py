"""Proxy manager — switch HTTPS_PROXY for all agents."""

import asyncio
import logging
import os
from dataclasses import dataclass

import httpx

from app.runtime_env import MCP_BASE_ENV

logger = logging.getLogger(__name__)

COUNTRY_FLAGS = {
    "US": "🇺🇸", "GB": "🇬🇧", "DE": "🇩🇪", "NL": "🇳🇱", "FR": "🇫🇷",
    "FI": "🇫🇮", "SE": "🇸🇪", "NO": "🇳🇴", "CH": "🇨🇭", "AT": "🇦🇹",
    "RU": "🇷🇺", "UA": "🇺🇦", "KZ": "🇰🇿", "BY": "🇧🇾",
    "JP": "🇯🇵", "KR": "🇰🇷", "SG": "🇸🇬", "AU": "🇦🇺",
    "CA": "🇨🇦", "BR": "🇧🇷", "IN": "🇮🇳", "TR": "🇹🇷",
    "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
    "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
    "IT": "🇮🇹", "PT": "🇵🇹", "DK": "🇩🇰", "LT": "🇱🇹",
    "LV": "🇱🇻", "EE": "🇪🇪", "IS": "🇮🇸", "MD": "🇲🇩",
}
IP_CHECK_URL = "https://ipinfo.io/json"
IP_CHECK_TIMEOUT = 8


@dataclass
class ProxyEntry:
    id: str
    name: str
    url: str


def _parse_proxy_list() -> list[ProxyEntry]:
    raw = os.environ.get("PROXY_LIST", "")
    if not raw:
        current = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if current:
            return [ProxyEntry(id="default", name="Default", url=current)]
        return []
    entries = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "|" in item:
            parts = item.split("|", 2)
            pid = parts[0].strip().lower().replace(" ", "-")
            name = parts[0].strip()
            url = parts[1].strip()
        else:
            url = item
            pid = url.split(":")[-1] if ":" in url else "proxy"
            name = url
        entries.append(ProxyEntry(id=pid, name=name, url=url))
    return entries


class ProxyManager:
    def __init__(self):
        self._active_id: str | None = None
        self._cache: dict[str, dict] = {}

    def _get_entries(self) -> list[ProxyEntry]:
        return _parse_proxy_list()

    def _get_active_id(self) -> str:
        if self._active_id:
            return self._active_id
        entries = self._get_entries()
        current_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
        if not current_proxy:
            direct = next((e for e in entries if e.url == "direct"), None)
            if direct:
                self._active_id = direct.id
                return direct.id
        for e in entries:
            if e.url == current_proxy:
                self._active_id = e.id
                return e.id
        return entries[0].id if entries else ""

    async def check_proxy(self, proxy_id: str) -> dict:
        entries = self._get_entries()
        entry = next((e for e in entries if e.id == proxy_id), None)
        if not entry:
            return {"error": f"proxy '{proxy_id}' not found"}
        return await self._do_check(entry)

    async def _do_check(self, entry: ProxyEntry) -> dict:
        try:
            kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
            if entry.url and entry.url != "direct":
                kwargs["proxy"] = entry.url
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.get(IP_CHECK_URL)
                if resp.status_code != 200:
                    return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
                data = resp.json()
                ip = data.get("ip", "?")
                country = data.get("country", "??")
                city = data.get("city", "")
                org = data.get("org", "")
                flag = COUNTRY_FLAGS.get(country, "🏳️")
                result = {
                    "id": entry.id, "ok": True,
                    "ip": ip, "country": country, "city": city,
                    "org": org, "flag": flag,
                }
                self._cache[entry.id] = result
                return result
        except Exception as e:
            result = {"id": entry.id, "ok": False, "error": str(e)}
            self._cache[entry.id] = result
            return result

    async def list_proxies(self) -> dict:
        entries = self._get_entries()
        active_id = self._get_active_id()
        proxies = []
        for e in entries:
            cached = self._cache.get(e.id)
            info = {
                "id": e.id, "name": e.name, "url": e.url,
                "active": e.id == active_id,
            }
            if cached:
                info.update({k: cached[k] for k in ("ok", "ip", "country", "city", "flag", "error") if k in cached})
            proxies.append(info)
        return {"proxies": proxies, "active": active_id}

    async def check_all(self) -> list[dict]:
        entries = self._get_entries()
        tasks = [self._do_check(e) for e in entries]
        return await asyncio.gather(*tasks)

    async def select_proxy(self, proxy_id: str) -> dict:
        entries = self._get_entries()
        entry = next((e for e in entries if e.id == proxy_id), None)
        if not entry:
            return {"error": f"proxy '{proxy_id}' not found"}
        if entry.url == "direct":
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
            MCP_BASE_ENV.pop("HTTPS_PROXY", None)
            MCP_BASE_ENV.pop("HTTP_PROXY", None)
        else:
            os.environ["HTTPS_PROXY"] = entry.url
            os.environ["HTTP_PROXY"] = entry.url
            MCP_BASE_ENV["HTTPS_PROXY"] = entry.url
            MCP_BASE_ENV["HTTP_PROXY"] = entry.url
        self._active_id = proxy_id
        logger.info(f"Proxy switched to '{entry.name}' ({entry.url})")
        return {"ok": True, "active": proxy_id, "url": entry.url}


proxy_manager = ProxyManager()
