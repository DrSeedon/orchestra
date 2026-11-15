#!/usr/bin/env python3
"""Atomically build and load table inet orchestra_oauth_killswitch without touching UFW.

Supports:
  --static-only : zero-DNS fast boot (<30ms) using static CIDRs + persisted last-known-good cache
                  + unconditional skgid=agy_oauth non-loopback reject across ALL ports/protocols.
  --refresh-dns : bounded per-host DNS resolution (2.0s timeout per host) merged into 24h TTL
                  last-known-good cache so transient DNS failures never drop learned IPs.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import grp
import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

NFT_PATH = Path("/etc/nftables.d/orchestra-oauth-killswitch.nft")
LAST_GOOD_PATH = Path("/var/lib/orchestra/oauth-killswitch-last-good.json")
READY_PATH = Path("/run/orchestra-oauth-killswitch.ready")
CACHE_TTL_SECONDS = 86400.0

OAUTH_HOSTS = (
    "chatgpt.com",
    "ab.chatgpt.com",
    "auth.openai.com",
    "api.openai.com",
    "api.anthropic.com",
    "claude.ai",
    "platform.claude.com",
    "api.x.ai",
)

STATIC_V4 = [
    "160.79.104.0/23",  # Anthropic PBC (AS399358)
    "104.18.32.47",
    "172.64.155.209",
    "104.18.41.241",
    "172.64.146.15",
    "162.159.140.245",
    "172.66.0.243",
    "104.18.18.80",
    "104.18.19.80",
]

STATIC_V6 = [
    "2607:6bc0::/48",  # Anthropic PBC (AS399358)
    "2606:4700:4408::ac40:9bd1",
    "2a06:98c1:3101::6812:202f",
    "2606:4700:4400::6812:29f1",
    "2a06:98c1:310c::ac40:920f",
    "2606:4700:7::f3",
    "2a06:98c1:58::f3",
    "2606:4700::6812:1250",
    "2606:4700::6812:1350",
]

NEVER_BLOCK_NETS = [
    ipaddress.ip_network("178.93.29.64/32"),     # Xray NL upstream
    ipaddress.ip_network("158.220.127.161/32"),  # Self
    ipaddress.ip_network("72.56.235.40/32"),     # Seedon VPS
    ipaddress.ip_network("104.16.0.0/16"),       # registry.npmjs.org
    ipaddress.ip_network("172.217.0.0/16"),      # Google GFE (shared with Google Drive/Storage)
    ipaddress.ip_network("142.250.0.0/15"),      # Google GFE
]


def _is_safe_to_block(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return False
    for net in NEVER_BLOCK_NETS:
        if addr.version == net.version and addr in net:
            return False
    return True


def _load_last_good(now: float) -> tuple[dict[str, float], dict[str, float]]:
    if not LAST_GOOD_PATH.is_file():
        return {}, {}
    try:
        data = json.loads(LAST_GOOD_PATH.read_text(encoding="utf-8"))
        v4 = {
            str(ip): float(ts)
            for ip, ts in (data.get("v4") or {}).items()
            if now - float(ts) < CACHE_TTL_SECONDS
        }
        v6 = {
            str(ip): float(ts)
            for ip, ts in (data.get("v6") or {}).items()
            if now - float(ts) < CACHE_TTL_SECONDS
        }
        return v4, v6
    except Exception:
        return {}, {}


def _save_atomic_json(path: Path, payload: dict, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _resolve_one_host(host: str) -> list[tuple[int, str]]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return [(fam, sockaddr[0]) for fam, _, _, _, sockaddr in infos]


def _resolve_hosts_bounded(timeout_per_host: float = 2.0, total_deadline: float = 6.0) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    try:
        futs = {ex.submit(_resolve_one_host, h): h for h in OAUTH_HOSTS}
        done, _not_done = concurrent.futures.wait(futs.keys(), timeout=total_deadline)
        for fut in done:
            try:
                rows = fut.result(timeout=timeout_per_host)
                found.extend(rows)
            except Exception:
                continue
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--static-only", action="store_true", help="Skip DNS resolution for instant boot")
    ap.add_argument("--refresh-dns", action="store_true", help="Resolve OAuth hosts with bounded deadline")
    args = ap.parse_args()

    # Fail closed if required agy_oauth group does not exist!
    try:
        agy_gid = grp.getgrnam("agy_oauth").gr_gid
    except KeyError as exc:
        raise RuntimeError("CRITICAL: required group 'agy_oauth' missing; refusing fail-open killswitch") from exc

    now = time.time()
    anth_v4 = ipaddress.ip_network("160.79.104.0/23")
    anth_v6 = ipaddress.ip_network("2607:6bc0::/48")

    cached_v4, cached_v6 = _load_last_good(now)
    v4_ips: set[str] = set(STATIC_V4[1:]) | set(cached_v4.keys())
    v6_ips: set[str] = set(STATIC_V6[1:]) | set(cached_v6.keys())

    if not args.static_only:
        for fam, ip_str in _resolve_hosts_bounded():
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if not _is_safe_to_block(ip_obj):
                continue
            if fam == socket.AF_INET and ip_obj not in anth_v4:
                s = str(ip_obj)
                v4_ips.add(s)
                cached_v4[s] = now
            elif fam == socket.AF_INET6 and ip_obj not in anth_v6:
                s = str(ip_obj)
                v6_ips.add(s)
                cached_v6[s] = now
        _save_atomic_json(LAST_GOOD_PATH, {"v4": cached_v4, "v6": cached_v6, "updated_at": now})

    # Re-filter cached + static entries through _is_safe_to_block
    clean_v4 = sorted(ip for ip in v4_ips if _is_safe_to_block(ipaddress.ip_address(ip)) and ipaddress.ip_address(ip) not in anth_v4)
    clean_v6 = sorted(ip for ip in v6_ips if _is_safe_to_block(ipaddress.ip_address(ip)) and ipaddress.ip_address(ip) not in anth_v6)

    v4_elems = ", ".join(["160.79.104.0/23", *clean_v4])
    v6_elems = ", ".join(["2607:6bc0::/48", *clean_v6])

    # Note:
    # 1. `oifname "lo" accept` allows local tinyproxy (127.0.0.1:18080) & local IPC/MCP.
    # 2. `meta skgid <agy_gid>` rejects ALL non-loopback packets regardless of port or protocol!
    # 3. `meta skuid "kesha"` rejects ALL ports/protocols to @oauth_provider_v4 / @oauth_provider_v6!
    rules = f"""# Managed by /usr/local/sbin/orchestra-refresh-oauth-killswitch
table inet orchestra_oauth_killswitch
delete table inet orchestra_oauth_killswitch

table inet orchestra_oauth_killswitch {{
    set oauth_provider_v4 {{
        type ipv4_addr
        flags interval
        elements = {{ {v4_elems} }}
    }}

    set oauth_provider_v6 {{
        type ipv6_addr
        flags interval
        elements = {{ {v6_elems} }}
    }}

    chain output {{
        type filter hook output priority filter - 10; policy accept;
        oifname "lo" accept
        meta skgid {agy_gid} limit rate 6/minute burst 10 packets log prefix "[AGY-DIRECT-BLOCK] "
        meta skgid {agy_gid} counter reject with icmpx type admin-prohibited
        meta skuid != "kesha" accept
        ip daddr @oauth_provider_v4 limit rate 6/minute burst 10 packets log prefix "[OAUTH-DIRECT-BLOCK] "
        ip daddr @oauth_provider_v4 counter reject with icmpx type admin-prohibited
        ip6 daddr @oauth_provider_v6 limit rate 6/minute burst 10 packets log prefix "[OAUTH-DIRECT-BLOCK] "
        ip6 daddr @oauth_provider_v6 counter reject with icmpx type admin-prohibited
    }}
}}
"""

    NFT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".orchestra-oauth-killswitch.", suffix=".nft", dir=str(NFT_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rules)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o644)
        subprocess.run(["/usr/sbin/nft", "-c", "-f", tmp_name], check=True)
        os.replace(tmp_name, NFT_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    subprocess.run(["/usr/sbin/nft", "-f", str(NFT_PATH)], check=True)
    _save_atomic_json(
        READY_PATH,
        {
            "ok": True,
            "agy_gid": agy_gid,
            "mode": "static_only" if args.static_only else "dns_refreshed",
            "v4_count": len(clean_v4) + 1,
            "v6_count": len(clean_v6) + 1,
            "updated_at": now,
        },
        mode=0o644,
    )
    print(
        f"Loaded orchestra_oauth_killswitch ({'static' if args.static_only else 'dns'}): "
        f"agy_gid={agy_gid}, {len(clean_v4)+1} IPv4 entries, {len(clean_v6)+1} IPv6 entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
