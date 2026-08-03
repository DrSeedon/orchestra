"""migrate_agent.py: перенос не должен молча складывать файлы туда, где их никто не прочтёт.

Скрипт логинится по ssh как root, а Orchestra и Claude CLI работают под юзером службы.
Всё, что об этом забывает, ломается тихо: транскрипт «перенесён», а истории нет.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "migrate_agent",
    pathlib.Path(__file__).parent.parent / "scripts" / "migrate_agent.py",
)
migrate_agent = importlib.util.module_from_spec(_SPEC)
sys.modules["migrate_agent"] = migrate_agent
_SPEC.loader.exec_module(migrate_agent)


# ── enc_cli_dir ──

def test_leading_dash_is_part_of_the_name():
    """Ведущий '-' — часть имени каталога CLI. Срезали его → писали мимо."""
    assert migrate_agent.enc_cli_dir("/home/kesha") == "-home-kesha"


def test_nested_path_encodes_every_separator():
    assert migrate_agent.enc_cli_dir(
        "/home/kesha/orchestra/worktrees/home-kesha-orchestra/back"
    ) == "-home-kesha-orchestra-worktrees-home-kesha-orchestra-back"


def test_encoding_matches_real_cli_directories():
    """Сверка с ЖИВЫМИ парами (cwd → имя каталога), взятыми из самих транскриптов.

    Не подгонка под список имён: cwd читается из первой строки .jsonl, то есть
    из того, что CLI записал сам. Нет каталогов на машине → тест пропускается.
    """
    root = pathlib.Path.home() / ".claude" / "projects"
    if not root.is_dir():
        pytest.skip("нет ~/.claude/projects на этой машине")

    pairs = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        transcript = next(iter(sorted(directory.glob("*.jsonl"))), None)
        if not transcript:
            continue
        with transcript.open() as fh:
            for line in fh:
                try:
                    cwd = (json.loads(line) or {}).get("cwd")
                except (json.JSONDecodeError, AttributeError):
                    break
                if cwd:
                    pairs.append((cwd, directory.name))
                    break
    if not pairs:
        pytest.skip("не нашёл ни одной пары cwd → каталог")

    mismatched = [(c, real) for c, real in pairs if migrate_agent.enc_cli_dir(c) != real]
    assert not mismatched, f"кодирование разошлось с реальностью: {mismatched[:3]}"


# ── target_service_user / give_to_service_user ──

def _fake_ssh(monkeypatch, replies: dict, calls: list | None = None):
    def _ssh(host, cmd, *, check=True, capture=True):
        if calls is not None:
            calls.append(cmd)
        for needle, out in replies.items():
            if needle in cmd:
                return subprocess.CompletedProcess([], 0, stdout=out, stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(migrate_agent, "ssh", _ssh)


def test_service_user_comes_from_installation_not_ssh_login(monkeypatch):
    """root@host — это логин, а не юзер службы. Берём владельца каталога установки."""
    _fake_ssh(monkeypatch, {"stat -c %U": "kesha\n", "getent passwd": "/home/kesha\n"})

    user, home = migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra")

    assert (user, home) == ("kesha", "/home/kesha")


def test_unknown_owner_stops_the_migration(monkeypatch):
    """Не смогли определить юзера → падаем, а не продолжаем от root."""
    _fake_ssh(monkeypatch, {"stat -c %U": "\n"})

    with pytest.raises(SystemExit):
        migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra")


def test_unknown_home_stops_the_migration(monkeypatch):
    _fake_ssh(monkeypatch, {"stat -c %U": "kesha\n", "getent passwd": "\n"})

    with pytest.raises(SystemExit):
        migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra")


def test_chown_is_verified_not_assumed(monkeypatch):
    """chown мог не сработать. Молча продолжать нельзя — это и есть тот баг."""
    _fake_ssh(monkeypatch, {"find": "7"})  # 7 чужих файлов и до, и после

    with pytest.raises(SystemExit):
        migrate_agent.give_to_service_user("root@vps", "/path", "kesha")


def test_chown_runs_recursively_for_the_service_user(monkeypatch):
    calls: list[str] = []
    _fake_ssh(monkeypatch, {"find": "0"}, calls)

    migrate_agent.give_to_service_user("root@vps", "/path", "kesha")

    assert any("chown -R kesha:kesha" in c for c in calls)


# ── назначение транскрипта ──

def test_transcript_lands_in_service_user_home_not_root(monkeypatch):
    """'~' под ssh-root раскрывался в /root — CLI туда никогда не смотрит."""
    calls: list[str] = []
    _fake_ssh(monkeypatch, {"test -f": "no"}, calls)

    migrate_agent.copy_transcript(
        "root@laptop", "root@vps", "sess-1",
        "/home/kesha/projects/x", "/home/kesha/projects/x",
        to_user="kesha", to_home="/home/kesha", from_home="/home/kesha",
    )

    mkdir = next(c for c in calls if c.startswith("mkdir -p"))
    assert "/home/kesha/.claude/projects/-home-kesha-projects-x" in mkdir
    assert "~" not in mkdir
