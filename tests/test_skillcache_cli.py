import json
import os
import subprocess
import sys
from pathlib import Path

from app import db
from app.skillcache.pilots import MANIFESTS, catalog
from app.skillcache.qualifier import qualify
from app.skillcache.registry import Registry, SkillSource


REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "scripts" / "orch-capsule-run"


def _run_cli(args, *, env, stdin_text=None, expected_rc=0):
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin_text,
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert proc.returncode == expected_rc, f"rc={proc.returncode} expected={expected_rc} stderr={proc.stderr} stdout={proc.stdout}"
    return json.loads(proc.stdout)


def test_orch_capsule_run_list_describe_exec_readonly_and_exit_codes(tmp_path):
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    db_path = db_dir / "orch.sqlite"
    db.init_db(db_path)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("fixture")
    priv = tmp_path / "priv"
    priv.mkdir(mode=0o700)
    stat_root = tmp_path / "stat"
    stat_root.mkdir()

    cfg = {
        "private_dir": str(priv),
        "scopes": {
            "vps": {
                name: {"skill_path": str(skill_md), "scripts": []}
                for name in MANIFESTS
            }
        },
        "grants": {
            "cli:operator": {
                "scope": "vps",
                "skills": ["vps-health-preflight", "edo-1c-status"],
                "bindings": {},
                "sources": {
                    "vps_allowed_units": ["orchestra.service", "kesha-bot-vps.service", "telegram-bot-api.service"],
                    "vps_stat_path": str(stat_root),
                    "orchestra_db_path": str(db_path),
                    "edo_db_dir": str(stat_root),
                },
            }
        },
    }
    cfg_path = tmp_path / "skillcache.json"
    cfg_path.write_text(json.dumps(cfg))
    cfg_path.chmod(0o600)

    os.environ["ORCHESTRA_DB_PATH"] = str(db_path)
    abi = catalog({("vps", name): SkillSource(skill_md, ()) for name in MANIFESTS})
    reg = Registry(lambda: db._conn(db_path), abi)
    qualify(reg, "vps", MANIFESTS["vps-health-preflight"])
    qualify(reg, "vps", MANIFESTS["edo-1c-status"])

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "ORCHESTRA_DB_PATH": str(db_path),
        "ORCHESTRA_SKILLCACHE_CONFIG": str(cfg_path),
        "ORCHESTRA_SKILLCACHE_RECEIPT_KEY": "k" * 32,
    }

    priv.chmod(0o500)
    db_dir.chmod(0o555)
    db_path.chmod(0o444)
    try:
        listed = _run_cli(["list", "--scope", "vps"], env=env, expected_rc=0)
        assert listed["active_count"] == 2
        by_skill = {c["skill"]: c for c in listed["capsules"]}
        assert by_skill["vps-health-preflight"]["intent"] == "vps_preflight"
        assert "query" in by_skill["vps-health-preflight"]["required_bindings"]
        assert by_skill["vps-health-preflight"]["summary"]

        desc = _run_cli(["describe", "vps-health-preflight"], env=env, expected_rc=0)
        assert desc["intent"] == "vps_preflight"
        assert "exec vps-health-preflight" in desc["cli_examples"]["run_with_defaults"]
        assert desc["mcp_examples"]["run"]["skill"] == "vps-health-preflight"

        res = _run_cli(["exec", "edo-1c-status"], env=env, expected_rc=0)
        assert res["status"] == "complete"
        assert res["result"]["status"]["db_exists"] is True

        bad = _run_cli(["exec", "vps-health-preflight", "--in", '{"unknown_param": 1}'], env=env, expected_rc=2)
        assert bad["status"] == "invalid_request"
        assert bad["unexpected_fields"] == ["unknown_param"]
        assert "units" in bad["allowed_fields"]

        unk = _run_cli(["exec", "nonexistent-capsule"], env=env, expected_rc=2)
        assert unk["status"] == "unknown_skill"

        revoked = _run_cli(["run"], env=env, stdin_text=json.dumps({"action": "run"}), expected_rc=0)
        assert revoked == {"status": "revoked"}
    finally:
        db_dir.chmod(0o755)
        db_path.chmod(0o644)
        priv.chmod(0o700)
