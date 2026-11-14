#!/usr/bin/env python3
"""Atomically build and load table inet orchestra_oauth_killswitch without touching UFW."""
from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import tempfile
from pathlib import Path

NFT_PATH = Path("/etc/nftables.d/orchestra-oauth-killswitch.nft")

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
    ipaddress.ip_network("172.217.0.0/16"),      # Google GFE (shared with Gmail MCP)
    ipaddress.ip_network("142.250.0.0/15"),      # Google GFE
]


def _is_safe_to_block(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return False
    for net in NEVER_BLOCK_NETS:
        if addr.version == net.version and addr in net:
            return False
    return True


def main() -> int:
    anth_v4 = ipaddress.ip_network("160.79.104.0/23")
    anth_v6 = ipaddress.ip_network("2607:6bc0::/48")
    v4_ips: set[str] = set()
    v6_ips: set[str] = set()

    for raw in STATIC_V4[1:]:
        v4_ips.add(raw)
    for raw in STATIC_V6[1:]:
        v6_ips.add(raw)

    for host in OAUTH_HOSTS:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except OSError:
            continue
        for fam, _, _, _, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if not _is_safe_to_block(ip_obj):
                continue
            if fam == socket.AF_INET and ip_obj not in anth_v4:
                v4_ips.add(str(ip_obj))
            elif fam == socket.AF_INET6 and ip_obj not in anth_v6:
                v6_ips.add(str(ip_obj))

    v4_elems = ", ".join(["160.79.104.0/23", *sorted(v4_ips)])
    v6_elems = ", ".join(["2607:6bc0::/48", *sorted(v6_ips)])

    rules = f"""# Managed by /usr/local/sbin/orchestra-refresh-oauth-killswitch
# Blocks direct Contabo datacenter egress from uid=kesha to OAuth provider VIPs;
# xray (uid=nobody), tinyproxy (uid=tinyproxy), and orchestra-proxy (uid=root) pass freely.
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
        meta skuid != "kesha" accept
        ip daddr @oauth_provider_v4 meta l4proto {{ tcp, udp }} th dport {{ 80, 443 }} limit rate 6/minute burst 10 packets log prefix "[OAUTH-DIRECT-BLOCK] "
        ip daddr @oauth_provider_v4 meta l4proto {{ tcp, udp }} th dport {{ 80, 443 }} counter reject with icmpx type admin-prohibited
        ip6 daddr @oauth_provider_v6 meta l4proto {{ tcp, udp }} th dport {{ 80, 443 }} limit rate 6/minute burst 10 packets log prefix "[OAUTH-DIRECT-BLOCK] "
        ip6 daddr @oauth_provider_v6 meta l4proto {{ tcp, udp }} th dport {{ 80, 443 }} counter reject with icmpx type admin-prohibited
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
    print(f"Loaded orchestra_oauth_killswitch: {len(v4_ips)+1} IPv4 entries, {len(v6_ips)+1} IPv6 entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
