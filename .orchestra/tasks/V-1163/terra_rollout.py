#!/usr/bin/env python3
"""Dry-run by default; reconcile every live managed orchestrator through the owner API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request

PRIVATE = (
    pathlib.Path(__file__).resolve().parents[3] / ".orchestra/private/V-1163"
    if __file__ != "<stdin>" else None
)
LAPTOP_SSH_FILE = PRIVATE / "laptop-ssh.json" if PRIVATE else None
API_REFUSALS_FILE = PRIVATE / "vps-api-refusals.json" if PRIVATE else None
TERRA = "gpt-6.1-terra"
TERMINAL_DELIVERIES = (
    "SUBMITTED", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN_ORPHANED", "CANCELLED",
)


def laptop_ssh() -> list[str]:
    cfg = json.loads(LAPTOP_SSH_FILE.read_text())
    return [
        "ssh", "-i", cfg["identity_file"], "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5", "-p", str(cfg["port"]), f"{cfg['user']}@{cfg['host']}",
    ]


def listener_pid() -> int:
    result = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, check=True)
    pids = set()
    for line in result.stdout.splitlines():
        if re.search(r"(?:127\.0\.0\.1|0\.0\.0\.0|\*):8888\b", line):
            pids.update(map(int, re.findall(r"pid=(\d+)", line)))
    if len(pids) != 1:
        raise RuntimeError("expected exactly one local Orchestra API listener")
    return pids.pop()


def process_env(pid: int) -> tuple[pathlib.Path, dict[str, str]]:
    proc = pathlib.Path("/proc") / str(pid)
    if proc.stat().st_uid != os.geteuid():
        raise RuntimeError("run as the Orchestra service user")
    env = {
        k.decode(): v.decode()
        for k, v in (item.split(b"=", 1) for item in (proc / "environ").read_bytes().split(b"\0") if b"=" in item)
    }
    if not env.get("INTERNAL_TOKEN"):
        raise RuntimeError("Orchestra service token is unavailable")
    return pathlib.Path(os.readlink(proc / "cwd")), env


def get_json(path: str, token: str) -> tuple[int, object]:
    req = urllib.request.Request(
        "http://127.0.0.1:8888" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {path} returned HTTP {exc.code}") from None


def read_effort_manifest(cwd: pathlib.Path) -> dict[str, bool]:
    import yaml

    path = cwd / ".orchestra/pipelines/default/pipeline.yaml"
    data = yaml.safe_load(path.read_text())
    roles = {
        name: cfg for name, cfg in data["roles"].items()
        if isinstance(cfg, dict) and cfg.get("kind") == "orchestrator"
    }
    return {
        role: isinstance(cfg.get("effort"), dict) and cfg["effort"].get(TERRA) == "high"
        for role, cfg in roles.items()
    }


def snapshot(machine: str) -> dict:
    pid = listener_pid()
    cwd, env = process_env(pid)
    db_path = pathlib.Path(env.get("ORCHESTRA_DB_PATH", "data/orchestra.db"))
    if not db_path.is_absolute():
        db_path = cwd / db_path
    if not db_path.is_file():
        raise RuntimeError("service database is unavailable")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row

    status, api_rows = get_json("/api/orchestrators", env["INTERNAL_TOKEN"])
    model_status, model_data = get_json("/api/models", env["INTERNAL_TOKEN"])
    if status != 200 or model_status != 200 or not isinstance(api_rows, list):
        raise RuntimeError("live read-only inventory request failed")
    models = model_data.get("models") if isinstance(model_data, dict) else None
    if not isinstance(models, list):
        raise RuntimeError("live model catalog is missing")
    model_ids = {m.get("id") for m in models if isinstance(m, dict)}
    terra = [m for m in models if isinstance(m, dict) and m.get("id") == TERRA]
    effort_high = read_effort_manifest(cwd)
    candidates, excluded = [], []
    for row in api_rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise RuntimeError("live orchestrator inventory contains an invalid row")
        role = row.get("role")
        is_orchestrator = row.get("is_orchestrator") is True
        if not is_orchestrator and role not in effort_high:
            excluded.append({"reason": "live API does not identify this row as a managed orchestrator"})
            continue
        if not is_orchestrator or role not in effort_high:
            raise RuntimeError("live API role and orchestrator flag disagree with the pipeline")
        db_row = conn.execute(
            "SELECT name, scope, role, is_orchestrator, model, effort FROM sessions "
            "WHERE id=? AND status!='archived'", (row["id"],),
        ).fetchone()
        if (
            db_row is None or db_row["is_orchestrator"] != 1
            or db_row["role"] != role or db_row["name"] != row.get("name")
            or db_row["scope"] != row.get("scope") or db_row["model"] != row.get("model")
        ):
            raise RuntimeError("live API and SQLite role/identity/model disagree")
        queued_mail = conn.execute(
            "SELECT COUNT(*) FROM mailbox WHERE recipient=? AND scope=? AND delivered_at IS NULL",
            (db_row["name"], db_row["scope"]),
        ).fetchone()[0]
        pending_deliveries = conn.execute(
            "SELECT COUNT(*) FROM message_deliveries WHERE target_session_id=? "
            "AND state NOT IN (?, ?, ?, ?)", (row["id"], *TERMINAL_DELIVERIES),
        ).fetchone()[0]
        candidates.append({
            "machine": machine, "id": row["id"], "name": db_row["name"], "scope": db_row["scope"],
            "role": role, "model": row.get("model"), "runtime": row.get("runtime"),
            "effort": db_row["effort"], "status": row.get("status"),
            "queued_mail": queued_mail, "pending_deliveries": pending_deliveries,
            "terra_registered": len(terra) == 1 and terra[0].get("runtime") == "codex",
            "effort_high": effort_high.get(role) is True,
        })
    return {
        "machine": machine, "api_status": status, "model_status": model_status,
        "terra_registered": len(terra) == 1,
        "terra_runtime": terra[0].get("runtime") if len(terra) == 1 else None,
        "model_ids": sorted(model_ids), "effort_high": effort_high,
        "records": sorted(candidates, key=lambda row: row["id"]), "excluded": excluded,
    }


def save_private_snapshot(machine: str, data: dict) -> None:
    if PRIVATE is None:
        return
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = PRIVATE / f"{machine}-preflight.json"
    payload = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), **data}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def api_refusals() -> dict[str, dict]:
    if API_REFUSALS_FILE is None or not API_REFUSALS_FILE.is_file():
        return {}
    data = json.loads(API_REFUSALS_FILE.read_text())
    return {
        row["id"]: row for row in data.get("targets", [])
        if row.get("id") and not row.get("resolved_by")
    }


def compact_refusal(row: dict) -> bool:
    response = row.get("api_response")
    detail = (
        row.get("refusal")
        or (response.get("error") if isinstance(response, dict) else "")
        or ""
    )
    return "target context cannot fit the native codex session" in str(detail).lower()


def record_api_refusal(machine: str, row: dict, status_code: int, response: object) -> None:
    if PRIVATE is None:
        return
    path = PRIVATE / f"{machine}-api-refusals.json"
    try:
        receipt = json.loads(path.read_text())
    except FileNotFoundError:
        receipt = {"machine": machine, "targets": []}
    refusals = {item["id"]: item for item in receipt["targets"]}
    refusals[row["id"]] = {
        "id": row["id"], "name": row["name"], "scope": row["scope"],
        "from_model": row["model"], "status_at_refusal": row["status"],
        "http_status": status_code, "api_response": response,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    receipt["targets"] = list(refusals.values())
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def blockers(row: dict, host: dict) -> list[str]:
    out = []
    if not host["terra_registered"] or host["terra_runtime"] != "codex":
        out.append("Terra absent from live API catalog")
    if not row["effort_high"]:
        out.append("manifest lacks explicit Terra: high for this orchestrator role")
    if row["model"] not in host["model_ids"]:
        out.append("current model is unknown to the live API catalog")
    if row["status"] not in {"idle", "waiting"}:
        out.append("session is not at an idle/waiting turn boundary")
    if row["queued_mail"] or row["pending_deliveries"]:
        out.append("queued message/delivery exists")
    return out


def change_one(machine: str, row: dict) -> str:
    host = snapshot(machine)
    current = next((item for item in host["records"] if item["id"] == row["id"]), None)
    if current is None:
        raise RuntimeError("target left the managed-orchestrator inventory")
    reasons = blockers(current, host)
    if reasons:
        return "blocked: " + "; ".join(reasons)
    if current["model"] == TERRA and current["effort_high"]:
        return "already-target"
    url = "http://127.0.0.1:8888/api/sessions/" + urllib.parse.quote(current["name"], safe="") + "/change-model"
    req = urllib.request.Request(
        url, data=json.dumps({"scope": current["scope"], "model": TERRA, "via": "dashboard"}).encode(),
        headers={"Authorization": "Bearer " + process_env(listener_pid())[1]["INTERNAL_TOKEN"],
                 "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read(4096).decode("utf-8", errors="replace").replace("\n", " ").strip()
        try:
            detail = json.loads(raw)
        except (json.JSONDecodeError, AttributeError):
            detail = {"body": raw}
        record_api_refusal(machine, current, exc.code, detail)
        summary = str(detail.get("error") or detail.get("detail") or detail.get("body") or detail)
        return f"blocked: API HTTP {exc.code}: {summary[:300]}"
    if not isinstance(result, dict) or result.get("ok") is not True or result.get("model") != TERRA:
        raise RuntimeError("model change was not confirmed; stopped")
    check = snapshot(machine)
    after = next((item for item in check["records"] if item["id"] == current["id"]), None)
    if after is None or after["model"] != TERRA:
        raise RuntimeError("post-change model verification failed; stopped")
    return "changed" if result.get("changed") else "already-target"


def render(hosts: list[dict], applied: dict[str, dict[str, str]] | None = None) -> str:
    lines = ["machine/session\torchestrator\truntime\tcurrent model\teffort\tstatus\treadiness\tproposed model\tproposed effort\tblocked reason"]
    for host in hosts:
        machine = host["machine"]
        for index, row in enumerate(host["records"], 1):
            reasons = blockers(row, host)
            outcome = (applied or {}).get(machine, {}).get(row["id"])
            readiness = outcome or ("blocked" if reasons else "ready")
            if isinstance(outcome, str) and outcome.startswith("blocked: "):
                reasons = [outcome.removeprefix("blocked: ")]
            if row["model"] == TERRA and row["effort_high"]:
                readiness = "already-target"
                reasons = []
            lines.append("\t".join((
                f"{machine}/{index}", "true", str(row["runtime"] or "unknown"),
                str(row["model"] or "unknown"), str(row["effort"] or "unset"),
                str(row["status"] or "unknown"), readiness, TERRA, "High",
                "; ".join(reasons) if reasons else "none",
            )))
        for index, row in enumerate(host.get("excluded", []), 1):
            lines.append("\t".join((
                f"{machine}/excluded-{index}", "false", "unknown", "unknown", "unknown",
                "unknown", "excluded", TERRA, "High", row["reason"],
            )))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", choices=("both", "vps", "laptop", "local"), default="both")
    parser.add_argument("--apply", action="store_true", help="apply through the owner model-change API")
    parser.add_argument("--pending-watch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-json", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.pending_watch:
        host = snapshot("vps")
        refused = api_refusals()
        model_ready = any(
            row["model"] != TERRA and row["id"] not in refused and not blockers(row, host)
            for row in host["records"]
        )
        records = {row["id"]: row for row in host["records"]}
        refusal_data = json.loads(API_REFUSALS_FILE.read_text()) if API_REFUSALS_FILE and API_REFUSALS_FILE.is_file() else {"targets": []}
        ordered = refusal_data.get("targets", [])
        compact_ready = False
        for ordinal, refusal in enumerate(ordered, 1):
            sid = refusal.get("id")
            if sid not in refused or not compact_refusal(refusal):
                continue
            if (PRIVATE / f"vps-native-compact-{ordinal}.json").exists():
                continue
            row = records.get(sid)
            if row is not None and not blockers(row, host):
                compact_ready = True
                break
        ready = model_ready or compact_ready
        print("READY" if ready else "WAIT")
        return 0
    if args.machine == "local":
        result = snapshot("laptop")
        if args.apply:
            result["outcomes"] = {
                row["id"]: change_one("laptop", row) for row in result["records"]
            }
        print(json.dumps(result) if args.internal_json else render([result], {"laptop": result.get("outcomes", {})}))
        return 0

    machines = ("vps", "laptop") if args.machine == "both" else (args.machine,)
    hosts = {"vps": snapshot("vps")} if "vps" in machines else {}
    applied = {}
    if "laptop" in machines:
        script = pathlib.Path(__file__).read_text()
        cmd = [*laptop_ssh(), "nice", "-n", "15", "python3", "-", "--machine", "local", "--internal-json"]
        if args.apply:
            cmd.append("--apply")
        remote = subprocess.run(cmd, input=script, text=True, capture_output=True, check=False)
        if remote.returncode:
            error_path = PRIVATE / "laptop-script-error.txt"
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(remote.stderr[:4000])
            error_path.chmod(0o600)
            raise RuntimeError("owner-laptop preflight/API operation failed; details are private")
        hosts["laptop"] = json.loads(remote.stdout)
        if args.apply:
            applied["laptop"] = hosts["laptop"].pop("outcomes")
    for machine, host in hosts.items():
        save_private_snapshot(machine, host)
    if args.apply and "vps" in machines:
        refused = api_refusals()
        applied["vps"] = {}
        for row in hosts["vps"]["records"]:
            refusal = refused.get(row["id"])
            if refusal:
                refusal_status = refusal.get("http_status", refusal.get("api_http", "unknown"))
                applied["vps"][row["id"]] = (
                    f"blocked: prior API HTTP {refusal_status}; no retry"
                )
            else:
                applied["vps"][row["id"]] = change_one("vps", row)
    print(render([hosts[machine] for machine in machines], applied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
