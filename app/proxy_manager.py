"""Proxy list + on-demand health check — READ-ONLY.

Source of truth for the active proxy is .env HTTPS_PROXY (systemd EnvironmentFile
→ os.environ). This module NEVER mutates proxy env or persists anything: it only
reads PROXY_LIST for the dashboard and probes liveness on demand. To switch proxy:
edit .env + restart Orchestra.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

import httpx

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
        # Stable id for direct — name-derived id mangles cyrillic/parens
        # ("Direct (VPN/Соту)" → "direct-(vpn/соту)")
        if url == "direct":
            pid = "direct"
        entries.append(ProxyEntry(id=pid, name=name, url=url))
    return entries


def _active_id(entries: list[ProxyEntry]) -> str:
    """Which entry matches the current HTTPS_PROXY (from .env). Read-only."""
    current = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
    if not current:
        direct = next((e for e in entries if e.url == "direct"), None)
        return direct.id if direct else ""
    match = next((e for e in entries if e.url == current), None)
    return match.id if match else ""


class ProxyManager:
    def _get_entries(self) -> list[ProxyEntry]:
        return _parse_proxy_list()

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
                country = data.get("country", "??")
                return {
                    "id": entry.id, "ok": True,
                    "ip": data.get("ip", "?"), "country": country,
                    "city": data.get("city", ""), "org": data.get("org", ""),
                    "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                }
        except Exception as e:
            return {"id": entry.id, "ok": False, "error": str(e)}

    async def list_proxies(self) -> dict:
        """List proxies from .env. `active` = current HTTPS_PROXY (read-only).

        No liveness here — call check/{id} or check_all for that (on-demand).
        """
        entries = self._get_entries()
        active_id = _active_id(entries)
        proxies = [
            {"id": e.id, "name": e.name, "url": e.url, "active": e.id == active_id}
            for e in entries
        ]
        return {"proxies": proxies, "active": active_id}

    async def check_all(self) -> list[dict]:
        entries = self._get_entries()
        return await asyncio.gather(*(self._do_check(e) for e in entries))


proxy_manager = ProxyManager()
