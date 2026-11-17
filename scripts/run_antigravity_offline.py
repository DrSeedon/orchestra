"""Mock-only runner; invoke through run_antigravity_offline.sh (network namespace)."""
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAKE = ROOT / "tests/acp_mock/fake_agy_acp.py"
SANDBOX = Path(os.environ["HOME"]).resolve()
LOCAL_CONTRACTS = "--local-contracts" in sys.argv
if LOCAL_CONTRACTS:
    sys.argv.remove("--local-contracts")
    allowed = {"tests/test_default_pipeline.py", "tests/test_prompting.py",
               "tests/test_local_delegation_prompts.py", "tests/test_models.py",
               "tests/test_runtime_registry.py", "tests/test_quota_gate.py",
               "tests/test_hub_orchestrator_outbox.py", "tests/test_antigravity_audit_fixes.py"}
    selected = {a.split("::")[0] for a in sys.argv[1:] if a.startswith("tests/")}
    assert selected and selected <= allowed, "local contracts must name the bounded test set"

assert os.environ.get("ORCHESTRA_ACP_OFFLINE") == "1"
assert socket.if_nameindex() == [(1, "lo")], "namespace must contain only loopback"
assert len(Path("/proc/net/route").read_text().splitlines()) == 1, "external route exists"
assert not any(k for k in os.environ if any(x in k for x in ("TOKEN", "PASSWORD", "API_KEY")))


def audit(event, args):
    if event in {"socket.connect", "socket.bind"}:
        address = args[1]
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
            raise PermissionError("offline harness: external network denied")
    if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", None}:
        raise PermissionError("offline harness: external DNS denied")
    if event == "subprocess.Popen":
        executable, argv = args[:2]
        fake = Path(executable).resolve() == FAKE and list(argv)[1:2] == ["acp"]
        git_args = list(argv)
        target = Path(args[2] or os.getcwd()).resolve()
        if "-C" in git_args:
            target = Path(git_args[git_args.index("-C")+1]).resolve()
        elif git_args[1:2] == ["init"] and len(git_args) > 2:
            target = Path(git_args[-1]).resolve()
        local_git = (LOCAL_CONTRACTS and str(executable) in {"git", "/usr/bin/git"} and (
            target.is_relative_to(SANDBOX)
            or (target == Path("/nope/nowhere") and "rev-parse" in git_args)))
        if not (fake or local_git):
            raise PermissionError("offline harness: only fake_agy_acp.py acp or bounded synthetic local Git may execute")
    if event in {"os.system", "os.exec", "os.posix_spawn"}:
        raise PermissionError("offline harness: unapproved process launch")
    if event in {"open", "sqlite3.connect"} and isinstance(args[0], (str, bytes, os.PathLike)):
        raw = os.fsdecode(args[0])
        if event == "sqlite3.connect" and raw == ":memory:":
            return
        if event == "sqlite3.connect" and raw.startswith("file:"):
            from urllib.parse import unquote, urlsplit
            uri = urlsplit(raw)
            if uri.netloc not in {"", "localhost"}:
                raise PermissionError("offline harness: SQLite remote URI denied")
            raw = unquote(uri.path)
        p = Path(raw).resolve()
        production = Path("/home/kesha/orchestra")
        if p.is_relative_to(production) and not p.is_relative_to(production / ".venv"):
            raise PermissionError("offline harness: production repository/data denied")
        if p.is_relative_to(Path("/home/kesha")) and not (
            p.is_relative_to(ROOT) or p.is_relative_to(SANDBOX) or
            p.is_relative_to(production / ".venv") or p.is_relative_to(Path("/home/kesha/.local/share/uv/python"))
        ):
            raise PermissionError("offline harness: private home denied")
        if p.name == ".env" and not (LOCAL_CONTRACTS and p.is_relative_to(SANDBOX)):
            raise PermissionError("offline harness: dotenv denied")


sys.addaudithook(audit)
print(json.dumps({"isolation": "kernel network namespace + Python audit",
                  "interfaces": socket.if_nameindex(), "external_routes": 0,
                  "allowed_executable": str(FAKE), "import_root": str(ROOT),
                  "credentials_in_environment": 0}), flush=True)
if sys.argv[1:2] == ["--instructions"]:
    import runpy
    sys.argv = ["scripts/check_instruction_contract.py"]
    runpy.run_path(str(ROOT / sys.argv[0]), run_name="__main__")
else:
    import pytest
    base = ["--basetemp", str(SANDBOX / "pytest")] if LOCAL_CONTRACTS else []
    raise SystemExit(pytest.main(["-p", "pytest_asyncio.plugin", *base, *(sys.argv[1:] or ["tests/test_antigravity_acp.py", "-q"])]))
