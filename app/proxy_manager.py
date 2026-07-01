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
# Liveness = can we reach Anthropic (what we actually use)? ANY HTTP response
# (200/401/403/404) means the proxy tunnels fine. ipinfo.io was giving false
# "dead" for live proxies (intermittent timeouts) — it's now best-effort geo only.
LIVENESS_URL = "https://api.anthropic.com"
GEO_URL = "https://ipinfo.io/json"
CHECK_TIMEOUT = 8
GEO_TIMEOUT = 5


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
        """Two-tier: liveness via Anthropic (any HTTP response = alive), geo via
        ipinfo (best-effort — its flakiness must NOT mark a live proxy dead)."""
        proxy = entry.url if entry.url and entry.url != "direct" else None
        try:
            async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, verify=False, proxy=proxy) as client:
                await client.get(LIVENESS_URL)  # any response (200/401/403/404) = tunnel works
        except Exception as e:
            return {"id": entry.id, "ok": False, "error": str(e) or "unreachable"}
        result = {"id": entry.id, "ok": True}
        try:
            result.update(await self._geo(proxy))  # best-effort, never flips ok
        except Exception:
            pass  # geo is decoration — its failure must not mark a live proxy dead
        return result

    async def _geo(self, proxy: str | None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=GEO_TIMEOUT, verify=False, proxy=proxy) as client:
                resp = await client.get(GEO_URL)
                if resp.status_code != 200:
                    return {}
                data = resp.json()
                country = data.get("country", "")
                return {
                    "ip": data.get("ip", ""), "country": country,
                    "city": data.get("city", ""), "org": data.get("org", ""),
                    "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                }
        except Exception:
            return {}  # geo unavailable — proxy still reported alive

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
