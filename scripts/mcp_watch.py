#!/usr/bin/env python3
"""Watch MCP servers, Claude plugins and marketplaces on the VPS and the owner's laptop (V-1112).

Reads ~/.codex/config.toml, ~/.claude.json and ~/.claude/settings.json, compares the
definitions with a stored list of known ones and prints one signal line per new or changed
entry. Silent when nothing changed. Secrets never reach the output or the known list: env values,
headers and query strings are dropped, args are kept only as a hash.

  mcp_watch.py --init        take the baseline of the current state (no signals)
  mcp_watch.py               compare, print MCP_WATCH_NEW / MCP_WATCH_CHANGED / MCP_WATCH_UNREADABLE
  mcp_watch.py --no-update   compare without recording the signalled entries as known

Isolated session homes (~/.orchestra/codex-home/*) are written by Orchestra itself and are
deliberately not inspected.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

FILES = {
    "codex": ".codex/config.toml",
    "claude": ".claude.json",
    "settings": ".claude/settings.json",
}
LAPTOP_SSH = [
    "ssh", "-i", str(Path.home() / ".ssh/tunnel_laptop"), "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", "2222", "maxim@127.0.0.1",
]
SEP = "\x1e@@MCP_WATCH_FILE@@"


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def _safe_url(url):
    if not isinstance(url, str) or not url:
        return None
    p = urlsplit(url)
    return f"{p.scheme}://{p.hostname or ''}{':%s' % p.port if p.port else ''}{p.path}"


def _server(d: dict) -> dict:
    d = d if isinstance(d, dict) else {}
    args = d.get("args") or []
    rec = {
        "command": d.get("command"),
        "url": _safe_url(d.get("url")),
        "type": d.get("type"),
        "nargs": len(args) if isinstance(args, list) else 0,
        "args_sha": _sha(args),
        "env_keys": sorted((d.get("env") or {}).keys()) if isinstance(d.get("env"), dict) else [],
    }
    return rec


def parse_codex(text: str) -> dict:
    servers = tomllib.loads(text).get("mcp_servers") or {}
    return {f"codex:mcp:{n}": _server(d) for n, d in servers.items()}


def parse_claude_json(text: str) -> dict:
    data = json.loads(text)
    out = {f"claude:mcp:{n}": _server(d) for n, d in (data.get("mcpServers") or {}).items()}
    for proj, pd in (data.get("projects") or {}).items():
        for n, d in ((pd or {}).get("mcpServers") or {}).items():
            out[f"claude:project:{proj}:mcp:{n}"] = _server(d)
    return out


def parse_settings(text: str) -> dict:
    data = json.loads(text)
    out = {f"claude:plugin:{n}": {"enabled": bool(v)} for n, v in (data.get("enabledPlugins") or {}).items()}
    for n, d in (data.get("extraKnownMarketplaces") or {}).items():
        src = (d or {}).get("source") or {}
        out[f"claude:marketplace:{n}"] = {
            "source": src.get("source"),
            "repo": src.get("repo"),
            "url": _safe_url(src.get("url")),
            "path": src.get("path"),
        }
    return out


PARSERS = {"codex": parse_codex, "claude": parse_claude_json, "settings": parse_settings}


def read_vps() -> dict:
    """{file_kind: text | None-with-reason} for the local host."""
    out = {}
    for kind, rel in FILES.items():
        try:
            out[kind] = (Path.home() / rel).read_text()
        except OSError as e:
            out[kind] = e
    return out


def read_laptop() -> dict:
    script = "; ".join(
        f'printf "%s{kind}\\n" "{SEP}"; if [ -r "$HOME/{rel}" ]; then cat "$HOME/{rel}"; else echo "@@MISSING@@"; fi'
        for kind, rel in FILES.items()
    )
    try:
        r = subprocess.run(LAPTOP_SSH + [script], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"ssh failed: {type(e).__name__}") from e
    if r.returncode != 0:
        raise RuntimeError(f"ssh rc={r.returncode}: {r.stderr.strip()[:120]}")
    out = {}
    for chunk in r.stdout.split(SEP)[1:]:
        kind, _, body = chunk.partition("\n")
        out[kind] = OSError("not readable on host") if body.strip() == "@@MISSING@@" else body
    return out


def collect(host: str, files: dict) -> tuple[dict, list]:
    """Return (entries keyed 'host|...', problems)."""
    entries, problems = {}, []
    for kind, parser in PARSERS.items():
        text = files.get(kind)
        if text is None or isinstance(text, OSError):
            problems.append(f"MCP_WATCH_UNREADABLE host={host} file=~/{FILES[kind]} reason={text or 'absent'}")
            continue
        try:
            parsed = parser(text)
        except Exception as e:  # malformed file: report the class only, never its content
            problems.append(f"MCP_WATCH_UNREADABLE host={host} file=~/{FILES[kind]} reason=parse:{type(e).__name__}")
            continue
        for k, v in parsed.items():
            entries[f"{host}|{k}"] = v
    return entries, problems


def readable_prefixes(host: str, files: dict) -> set:
    """Entry-key prefixes whose source file was read; only those may be pruned from the known list."""
    pref = {"codex": f"{host}|codex:", "claude": f"{host}|claude:mcp:", "settings": f"{host}|claude:plugin:"}
    ok = set()
    for kind, text in files.items():
        if isinstance(text, str):
            ok.add(pref[kind])
            if kind == "claude":
                ok.add(f"{host}|claude:project:")
            if kind == "settings":
                ok.add(f"{host}|claude:marketplace:")
    return ok


def describe(key: str, rec: dict) -> str:
    host, _, rest = key.partition("|")
    bits = [f"host={host}", f"entry={rest}"]
    for f in ("command", "url", "type", "enabled", "source", "repo", "path", "nargs", "args_sha"):
        if rec.get(f) not in (None, ""):
            bits.append(f"{f}={rec[f]}")
    if rec.get("env_keys"):
        bits.append("env_keys=" + ",".join(rec["env_keys"]))
    return " ".join(bits)


def compare(known: dict, current: dict) -> list:
    lines = []
    for key, rec in sorted(current.items()):
        if key not in known:
            lines.append("MCP_WATCH_NEW " + describe(key, rec))
        elif known[key] != rec:
            lines.append("MCP_WATCH_CHANGED " + describe(key, rec))
    return lines


def known_path() -> Path:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=Path(__file__).parent,
        ).stdout.strip()
        root = Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        root = Path(__file__).resolve().parent.parent
    return root / ".orchestra" / "private" / "mcp_watch_known.json"


def run(known_file: Path, init: bool, update: bool, laptop: bool, sources: dict | None = None) -> int:
    sources = sources or {"vps": read_vps, **({"laptop": read_laptop} if laptop else {})}
    current, problems, prefixes = {}, [], set()
    for host, reader in sources.items():
        try:
            files = reader()
        except RuntimeError as e:
            problems.append(f"MCP_WATCH_UNREADABLE host={host} reason={e}")
            continue
        entries, probs = collect(host, files)
        current.update(entries)
        problems += probs
        prefixes |= readable_prefixes(host, files)
    if init:
        known = {k: v for k, v in current.items()}
        known_file.parent.mkdir(parents=True, exist_ok=True)
        known_file.write_text(json.dumps(known, indent=1, sort_keys=True))
        for k, v in sorted(known.items()):
            print("MCP_WATCH_BASELINE " + describe(k, v))
        for p in problems:
            print(p)
        return 0
    if not known_file.exists():
        print(f"MCP_WATCH_NO_BASELINE known list missing: {known_file}; run with --init")
        return 2
    known = json.loads(known_file.read_text())
    lines = compare(known, current)
    for line in lines + problems:
        print(line)
    if update:
        merged = {k: v for k, v in known.items() if not (k not in current and k.startswith(tuple(prefixes)))}
        merged.update(current)
        if merged != known:
            known_file.write_text(json.dumps(merged, indent=1, sort_keys=True))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="write the baseline of the current state")
    ap.add_argument("--no-update", action="store_true", help="do not record signalled entries as known")
    ap.add_argument("--no-laptop", action="store_true", help="skip the laptop")
    ap.add_argument("--known", type=Path, default=None, help="known-list file (default: .orchestra/private/)")
    a = ap.parse_args()
    return run(a.known or known_path(), a.init, not a.no_update, not a.no_laptop)


if __name__ == "__main__":
    sys.exit(main())
