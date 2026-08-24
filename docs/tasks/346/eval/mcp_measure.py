#!/usr/bin/env python3
"""Raw MCP/resource probe for frozen experiment #346; prints one JSON document."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _proc_table() -> dict[int, tuple[int, int, str]]:
    table: dict[int, tuple[int, int, str]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            close = raw.rfind(")")
            fields = raw[close + 2 :].split()
            ppid = int(fields[1])
            rss_pages = int(fields[21])
            name = raw[raw.find("(") + 1 : close]
            table[int(entry.name)] = (ppid, rss_pages * os.sysconf("SC_PAGE_SIZE"), name)
        except (OSError, ValueError, IndexError):
            continue
    return table


def _tree_sample(root: int) -> dict[str, Any]:
    table = _proc_table()
    descendants = {root}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _, _) in table.items():
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    rows = [
        {"pid": pid, "ppid": table[pid][0], "rss_bytes": table[pid][1], "name": table[pid][2]}
        for pid in sorted(descendants)
        if pid in table
    ]
    return {"rss_bytes": sum(row["rss_bytes"] for row in rows), "processes": rows}


def _resolve_unit_cgroup(unit: str) -> Path | None:
    if not unit:
        return None
    proc = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=ControlGroup", "--value"],
        text=True,
        capture_output=True,
    )
    rel = proc.stdout.strip()
    path = Path("/sys/fs/cgroup") / rel.lstrip("/") if rel else None
    return path if path is not None and path.is_dir() else None


def _cgroup_sample(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_dir():
        return None
    pids: set[int] = set()
    try:
        for procs_file in path.rglob("cgroup.procs"):
            pids.update(int(value) for value in procs_file.read_text().split())
    except (OSError, ValueError):
        pass
    table = _proc_table()
    rows = [
        {"pid": pid, "ppid": table[pid][0], "rss_bytes": table[pid][1], "name": table[pid][2]}
        for pid in sorted(pids)
        if pid in table
    ]
    result: dict[str, Any] = {
        "path": str(path),
        "rss_bytes": sum(row["rss_bytes"] for row in rows),
        "processes": rows,
    }
    for name in ("memory.current", "memory.peak", "memory.swap.current", "memory.swap.peak"):
        try:
            result[name.replace(".", "_")] = int((path / name).read_text().strip())
        except (OSError, ValueError):
            result[name.replace(".", "_")] = None
    try:
        result["memory_events"] = (path / "memory.events").read_text()
    except OSError:
        result["memory_events"] = ""
    return result


class Client:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str], systemd_unit: str = "") -> None:
        self.started = time.monotonic()
        self.proc = subprocess.Popen(
            command,
            cwd=cwd,
            env={**os.environ, **env},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.next_id = 0
        self.raw_lines: list[str] = []
        self.stderr_lines: list[str] = []
        self.samples: list[dict[str, Any]] = []
        self.systemd_unit = systemd_unit
        self.cgroup_path: Path | None = None
        self._stop = threading.Event()
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self.stderr_thread.start()
        self.monitor_thread.start()

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_lines.append(line.rstrip("\n"))

    def _monitor(self) -> None:
        while not self._stop.is_set():
            sample = _tree_sample(self.proc.pid)
            if self.systemd_unit and self.cgroup_path is None:
                self.cgroup_path = _resolve_unit_cgroup(self.systemd_unit)
            sample["cgroup"] = _cgroup_sample(self.cgroup_path)
            sample["elapsed_s"] = time.monotonic() - self.started
            self.samples.append(sample)
            self._stop.wait(0.05)

    def request(self, method: str, params: dict[str, Any], timeout: float = 120.0) -> tuple[dict[str, Any], float]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.next_id += 1
        req_id = self.next_id
        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        before = time.monotonic()
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        deadline = before + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited rc={self.proc.returncode} while waiting for {method}")
            line = self.proc.stdout.readline()
            if not line:
                continue
            self.raw_lines.append(line.rstrip("\n"))
            message = json.loads(line)
            if message.get("id") == req_id:
                return message, time.monotonic() - before
        raise TimeoutError(f"timeout waiting for {method}")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> int:
        if self.proc.poll() is None:
            if self.proc.stdin is not None:
                try:
                    self.proc.stdin.close()  # stdio server exits on EOF; systemd-run --wait follows it
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
        self._stop.set()
        self.monitor_thread.join(timeout=2)
        self.stderr_thread.join(timeout=2)
        return int(self.proc.returncode or 0)


def _text(envelope: dict[str, Any]) -> str:
    result = envelope.get("result") or {}
    content = result.get("content") if isinstance(result, dict) else None
    if not isinstance(content, list):
        return ""
    return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))


def _call(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    envelope, elapsed = client.request("tools/call", {"name": name, "arguments": arguments})
    return {"tool": name, "arguments": arguments, "elapsed_s": elapsed, "envelope": envelope, "text": _text(envelope)}


def _serena_scenario(client: Client, root: Path, tool_names: set[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for optional in ("initial_instructions", "get_current_config"):
        if optional in tool_names:
            calls.append(_call(client, optional, {}))
    calls.append(_call(client, "get_symbols_overview", {"relative_path": "python/plain.py", "depth": 1}))
    queries = [
        ("R1", "plain_target", "python/plain.py"),
        ("R2-route", "refresh_models_endpoint", "python/registry.py"),
        ("R2-tool", "update_progress", "python/registry.py"),
        ("R3", "dynamic_target", "python/dynamic_dispatch.py"),
        ("R4", "openDeleteOrchModal", "web/app.js"),
        ("R5-dead-leaf", "dead_leaf", "python/dead_cluster.py"),
        ("R5-dead-root", "dead_root", "python/dead_cluster.py"),
        ("R5-live-root", "live_root", "python/dead_cluster.py"),
        ("R6-old-before", "stale_target", "python/stale.py"),
    ]
    for case, symbol, path in queries:
        row = _call(client, "find_referencing_symbols", {"name_path": symbol, "relative_path": path})
        row["case"] = case
        calls.append(row)
    stale = root / "python/stale.py"
    before = stale.read_text(encoding="utf-8")
    changed = before.replace("stale_target", "stale_renamed")
    temp = stale.with_suffix(".py.swap346")
    temp.write_text(changed, encoding="utf-8")
    os.replace(temp, stale)
    for case, symbol in (("R6-old-immediate", "stale_target"), ("R6-new-immediate", "stale_renamed")):
        row = _call(client, "find_symbol", {
            "name_path_pattern": symbol, "relative_path": "python/stale.py", "include_body": False,
        })
        row["case"] = case
        calls.append(row)
    time.sleep(1.0)
    for case, symbol in (("R6-old-after-1s", "stale_target"), ("R6-new-after-1s", "stale_renamed")):
        row = _call(client, "find_symbol", {
            "name_path_pattern": symbol, "relative_path": "python/stale.py", "include_body": False,
        })
        row["case"] = case
        calls.append(row)
    return calls


def _light_scenario(client: Client, root: Path) -> list[dict[str, Any]]:
    calls = [_call(client, "code_outline", {"path": "python/plain.py"})]
    queries = [
        ("R1", "plain_target", "python/plain.py"),
        ("R2-route", "refresh_models_endpoint", "python/registry.py"),
        ("R2-tool", "update_progress", "python/registry.py"),
        ("R3", "dynamic_target", "python/dynamic_dispatch.py"),
        ("R4", "openDeleteOrchModal", "web/app.js"),
        ("R5-dead-leaf", "dead_leaf", "python/dead_cluster.py"),
        ("R5-dead-root", "dead_root", "python/dead_cluster.py"),
        ("R5-live-root", "live_root", "python/dead_cluster.py"),
        ("R6-old-before", "stale_target", "python/stale.py"),
    ]
    for case, symbol, path in queries:
        row = _call(client, "code_references", {"symbol": symbol, "definition_path": path})
        row["case"] = case
        calls.append(row)
    stale = root / "python/stale.py"
    before = stale.read_text(encoding="utf-8")
    changed = before.replace("stale_target", "stale_renamed")
    temp = stale.with_suffix(".py.swap346")
    temp.write_text(changed, encoding="utf-8")
    os.replace(temp, stale)
    for case, symbol in (("R6-old-immediate", "stale_target"), ("R6-new-immediate", "stale_renamed")):
        row = _call(client, "code_references", {"symbol": symbol, "definition_path": "python/stale.py"})
        row["case"] = case
        calls.append(row)
    return calls


def _serena_edit_scenario(client: Client, tool_names: set[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if "get_current_config" in tool_names:
        calls.append(_call(client, "get_current_config", {}))
    calls.append(_call(client, "get_symbols_overview", {"relative_path": "app/limits_card.py", "depth": 1}))
    for case, path, old, new in (
        ("E1", "app/limits_card.py", "pace_text", "format_pace_text"),
        ("E2", "app/prompting.py", "inject_skills_to_worktree", "install_skills_to_worktree"),
    ):
        row = _call(client, "rename_symbol", {
            "name_path": old,
            "relative_path": path,
            "new_name": new,
        })
        row["case"] = case
        calls.append(row)
    return calls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--scenario", choices=("serena", "serena-edit", "light"), required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--command-json", required=True)
    parser.add_argument("--env-json", default="{}")
    parser.add_argument("--systemd-unit", default="")
    args = parser.parse_args()

    root = Path(args.cwd).resolve()
    command = json.loads(args.command_json)
    env = {str(k): str(v) for k, v in json.loads(args.env_json).items()}
    result: dict[str, Any] = {
        "name": args.name,
        "scenario": args.scenario,
        "cwd": str(root),
        "command": command,
        "loadavg_start": os.getloadavg(),
        "started_wall": time.time(),
    }
    client = Client(command, root, env, args.systemd_unit)
    try:
        initialize, init_s = client.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "task346-probe", "version": "1"},
        })
        client.notify("notifications/initialized", {})
        tools, tools_s = client.request("tools/list", {})
        names = {tool.get("name", "") for tool in (tools.get("result") or {}).get("tools", [])}
        result.update({
            "initialize": initialize,
            "initialize_elapsed_s": init_s,
            "tools_list": tools,
            "tools_list_elapsed_s": tools_s,
            "ready_elapsed_s": time.monotonic() - client.started,
            "ready_sample": _cgroup_sample(client.cgroup_path) or _tree_sample(client.proc.pid),
        })
        if args.scenario == "serena":
            result["calls"] = _serena_scenario(client, root, names)
        elif args.scenario == "serena-edit":
            result["calls"] = _serena_edit_scenario(client, names)
        else:
            result["calls"] = _light_scenario(client, root)
        result["post_query_sample"] = _cgroup_sample(client.cgroup_path) or _tree_sample(client.proc.pid)
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["server_exit_code"] = client.close()
        result["stderr"] = client.stderr_lines
        result["raw_protocol_lines"] = client.raw_lines
        result["samples"] = client.samples
        result["peak_tree_rss_bytes"] = max((sample["rss_bytes"] for sample in client.samples), default=0)
        result["peak_cgroup_rss_bytes"] = max(
            (sample["cgroup"]["rss_bytes"] for sample in client.samples if sample.get("cgroup")),
            default=0,
        )
        result["peak_cgroup_memory_bytes"] = max(
            (sample["cgroup"]["memory_peak"] or 0 for sample in client.samples if sample.get("cgroup")),
            default=0,
        )
        result["loadavg_end"] = os.getloadavg()
        result["wall_elapsed_s"] = time.monotonic() - client.started
        result["ended_wall"] = time.time()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
