"""#200: one CLI path encoder. A copied body is how the two call sites drifted."""
import importlib.util
import inspect
import sys
from pathlib import Path

from app.manager import SessionManager, enc_cli_dir

_SPEC = importlib.util.spec_from_file_location(
    "migrate_agent",
    Path(__file__).parent.parent / "scripts" / "migrate_agent.py",
)
migrate_agent = importlib.util.module_from_spec(_SPEC)
sys.modules["migrate_agent"] = migrate_agent
_SPEC.loader.exec_module(migrate_agent)


def test_script_reexports_the_manager_owner():
    assert migrate_agent.enc_cli_dir is enc_cli_dir
    assert Path(inspect.getsourcefile(migrate_agent.enc_cli_dir)).name == "manager.py"


def test_leading_dash_and_dot_match_live_cli():
    assert enc_cli_dir("/home/kesha") == "-home-kesha"
    assert enc_cli_dir("/tmp/tmp.2YpeKWs1py") == "-tmp-tmp-2YpeKWs1py"


def test_migrate_cli_session_uses_shared_encoder_not_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr("app.manager.Path.home", lambda: tmp_path)
    old = "/tmp/tmp.2YpeKWs1py"
    new = "/home/kesha/orchestra"
    session_id = "sess-abc"
    # Literal names: deriving them from enc_cli_dir would stay green if that
    # function itself regressed (same helper on both sides of the assert).
    encoded_old = "-tmp-tmp-2YpeKWs1py"
    encoded_new = "-home-kesha-orchestra"
    legacy_old_name = "tmp-tmp.2YpeKWs1py"
    legacy_new_name = "home-kesha-orchestra"

    cli_base = tmp_path / ".claude" / "projects"
    real_old = cli_base / encoded_old
    real_old.mkdir(parents=True)
    (real_old / f"{session_id}.jsonl").write_text("real")

    (cli_base / legacy_old_name).mkdir(parents=True)
    (cli_base / legacy_old_name / f"{session_id}.jsonl").write_text("legacy")

    SessionManager._migrate_cli_session(session_id, old, new)

    assert (cli_base / encoded_new / f"{session_id}.jsonl").read_text() == "real"
    assert not (cli_base / legacy_new_name / f"{session_id}.jsonl").exists()
