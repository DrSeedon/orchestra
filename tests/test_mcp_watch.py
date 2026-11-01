import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location("mcp_watch", Path(__file__).parent.parent / "scripts" / "mcp_watch.py")
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)

CODEX = '[mcp_servers.figma]\ncommand = "npx"\nargs = ["-y", "figma-mcp"]\n[mcp_servers.figma.env]\nTOKEN = "s3cr3t-value"\n'
SETTINGS = json.dumps({"enabledPlugins": {"agents-md@local-mods": True}})


def files(codex=CODEX, claude='{"mcpServers": {}}', settings=SETTINGS):
    return {"codex": codex, "claude": claude, "settings": settings}


def watch(tmp_path, capsys, f, **kw):
    rc = mw.run(tmp_path / "known.json", sources={"vps": lambda: f}, init=kw.get("init", False), update=True, laptop=False)
    return rc, capsys.readouterr().out


def test_unchanged_state_is_silent_and_new_server_signals(tmp_path, capsys):
    watch(tmp_path, capsys, files(), init=True)
    rc, out = watch(tmp_path, capsys, files())
    assert (rc, out) == (0, "")
    evil = CODEX + '[mcp_servers.evil]\ncommand = "npx"\nargs = ["-y", "bad-pkg"]\n'
    _, out = watch(tmp_path, capsys, files(codex=evil))
    assert out.startswith("MCP_WATCH_NEW ") and "entry=codex:mcp:evil" in out and out.count("\n") == 1
    _, out = watch(tmp_path, capsys, files(codex=evil))
    assert out == ""


def test_changed_args_signal_and_env_secret_never_leaks(tmp_path, capsys):
    watch(tmp_path, capsys, files(), init=True)
    changed = CODEX.replace("figma-mcp", "figma-mcp-evil").replace("s3cr3t-value", "other-secret")
    _, out = watch(tmp_path, capsys, files(codex=changed))
    assert "MCP_WATCH_CHANGED" in out and "env_keys=TOKEN" in out
    for text in (out, (tmp_path / "known.json").read_text()):
        assert "s3cr3t" not in text and "other-secret" not in text and "figma-mcp-evil" not in text


def test_unreadable_file_is_reported_not_fatal(tmp_path, capsys):
    watch(tmp_path, capsys, files(), init=True)
    _, out = watch(tmp_path, capsys, files(codex=OSError("missing")))
    assert "MCP_WATCH_UNREADABLE host=vps file=~/.codex/config.toml" in out
    _, out = watch(tmp_path, capsys, files())
    assert out == ""  # entries of the unreadable run were kept, not forgotten


def test_marketplace_and_project_servers_are_tracked(tmp_path, capsys):
    watch(tmp_path, capsys, files(), init=True)
    claude = json.dumps({"projects": {"/p": {"mcpServers": {"x": {"url": "https://h.example/mcp?key=SECRET"}}}}})
    settings = json.dumps({"extraKnownMarketplaces": {"m": {"source": {"source": "github", "repo": "a/b"}}}})
    _, out = watch(tmp_path, capsys, files(claude=claude, settings=settings))
    assert "claude:project:/p:mcp:x" in out and "entry=claude:marketplace:m" in out and "SECRET" not in out
