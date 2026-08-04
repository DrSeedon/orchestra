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


def test_service_user_comes_from_the_unit_not_the_directory_owner(monkeypatch):
    """Каталог может принадлежать root при `User=kesha` — так и было здесь 03.08.

    Владелец каталога — догадка: в тот момент скрипт сделал бы `chown -R root`
    и отчитался об успехе, то есть закрепил бы чинимый баг.
    """
    _fake_ssh(monkeypatch, {
        "systemctl show": "LoadState=loaded\nUser=kesha\n",
        "stat -c %U": "root\n",           # каталог root'овый — и это НЕ ответ
        "getent passwd": "/home/kesha\n",
    })

    user, home = migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra", "orchestra")

    assert (user, home) == ("kesha", "/home/kesha")


def test_missing_unit_is_not_read_as_root(monkeypatch):
    """`systemctl show <нет-юнита> -p User` печатает пустое и exit 0 — как живой root-юнит.

    Различает только LoadState. Без него мигрированные файлы уехали бы к root.
    """
    _fake_ssh(monkeypatch, {"systemctl show": "LoadState=not-found\nUser=\n"})

    assert migrate_agent.unit_service_user("root@vps", "ghost") == ""


def test_loaded_unit_without_user_field_means_root(monkeypatch):
    """Пустой User= у ЗАГРУЖЕННОГО юнита — дефолт systemd, то есть root."""
    _fake_ssh(monkeypatch, {"systemctl show": "LoadState=loaded\nUser=\n"})

    assert migrate_agent.unit_service_user("root@vps", "orchestra") == "root"


def test_unit_absent_falls_back_to_directory_owner(monkeypatch):
    """Юнита нет (другой хост, другое имя) → владелец каталога как ЯВНО помеченная догадка."""
    _fake_ssh(monkeypatch, {
        "systemctl show": "LoadState=not-found\nUser=\n",
        "stat -c %U": "kesha\n",
        "getent passwd": "/home/kesha\n",
    })

    assert migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra", "orchestra") == (
        "kesha", "/home/kesha",
    )


def test_unknown_owner_stops_the_migration(monkeypatch):
    """Не смогли определить юзера → падаем, а не продолжаем от root."""
    _fake_ssh(monkeypatch, {"systemctl show": "LoadState=not-found\n", "stat -c %U": "\n"})

    with pytest.raises(SystemExit):
        migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra", "orchestra")


def test_unknown_home_stops_the_migration(monkeypatch):
    _fake_ssh(monkeypatch, {
        "systemctl show": "LoadState=loaded\nUser=kesha\n", "getent passwd": "\n",
    })

    with pytest.raises(SystemExit):
        migrate_agent.target_service_user("root@vps", "/home/kesha/orchestra", "orchestra")


class _FakeHost:
    """ssh-заглушка с состоянием: chown реально «убирает» чужих владельцев."""

    def __init__(self, foreign: list[str], modes: list[str] | None = None,
                 probe_rc: int = 0, chown_works: bool = True):
        self.foreign = list(foreign)
        self.modes = modes if modes is not None else ["755 /path"]
        self.probe_rc = probe_rc
        self.chown_works = chown_works
        self.calls: list[str] = []

    def ssh(self, host, cmd, *, check=True, capture=True):
        self.calls.append(cmd)
        if "chown -R" in cmd:
            if self.chown_works:
                self.foreign = []
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if "! -user" in cmd:
            return subprocess.CompletedProcess(
                [], self.probe_rc, stdout="\n".join(self.foreign), stderr="",
            )
        if "-printf '%m" in cmd:
            return subprocess.CompletedProcess([], 0, stdout="\n".join(self.modes), stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")


def test_chown_is_verified_not_assumed(monkeypatch):
    """chown мог не сработать. Молча продолжать нельзя — это и есть тот баг."""
    host = _FakeHost(["/path/a", "/path/b"], chown_works=False)
    monkeypatch.setattr(migrate_agent, "ssh", host.ssh)

    with pytest.raises(SystemExit):
        migrate_agent.give_to_service_user("root@vps", "/path", "kesha")


def test_missing_path_is_not_reported_as_clean(monkeypatch):
    """Пути нет → раньше `find … 2>/dev/null | wc -c` печатал 0, как и при успехе.

    Проверка, дающая одинаковый вывод при успехе и провале, — не проверка.
    """
    host = _FakeHost([], probe_rc=66)
    monkeypatch.setattr(migrate_agent, "ssh", host.ssh)

    with pytest.raises(SystemExit):
        migrate_agent.give_to_service_user("root@vps", "/gone", "kesha")


def test_chown_runs_recursively_for_the_service_user(monkeypatch):
    host = _FakeHost(["/path/a"])
    monkeypatch.setattr(migrate_agent, "ssh", host.ssh)

    migrate_agent.give_to_service_user("root@vps", "/path", "kesha")

    assert any("chown -R kesha:kesha" in c for c in host.calls)


def test_changed_permissions_stop_the_migration(monkeypatch):
    """Правило проекта: меняем ВЛАДЕЛЬЦА, а не режим. Съехал режим — падаем."""
    host = _FakeHost(["/path/a"], modes=["755 /path"])
    original = host.ssh

    def ssh_with_mode_drift(hostname, cmd, **kw):
        result = original(hostname, cmd, **kw)
        if "-printf '%m" in cmd and not host.foreign:  # снимок ПОСЛЕ chown
            return subprocess.CompletedProcess([], 0, stdout="700 /path", stderr="")
        return result

    monkeypatch.setattr(migrate_agent, "ssh", ssh_with_mode_drift)

    with pytest.raises(SystemExit):
        migrate_agent.give_to_service_user("root@vps", "/path", "kesha")


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


# ── сквозная проверка на РЕАЛЬНЫХ владельцах ──
#
# Владение нельзя смоделировать заглушками: нужны два разных юзера и настоящий git.
# Стенд подменяет только транспорт (ssh/scp исполняются локально), логика migrate_git
# работает как в бою. Нет беспарольного sudo → тест пропускается, а не притворяется.

def _sudo_available() -> bool:
    import shutil
    if not shutil.which("sudo"):
        return False
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0


def requires_two_users(test):
    """Пометить тест как требующий двух реальных владельцев и пропустить, если их нет.

    Маркер нужен ОТДЕЛЬНО от `skipif`: по нему `tests/conftest.py` печатает в конце прогона
    громкую строку. Молчаливый `skipped` даёт ту же зелёную сводку, что и пройденный тест, —
    то есть перестаёт быть проверкой ровно там, где проверки нет.
    """
    test = pytest.mark.needs_two_users(test)
    return pytest.mark.skipif(
        not _sudo_available(), reason="нужен беспарольный sudo: стенду нужны два владельца",
    )(test)


def _strip_host(path: str) -> str:
    import re
    return re.sub(r"^[^/][^:]*:", "", path)


@pytest.fixture
def migration_stand(tmp_path, monkeypatch):
    """Исходный репозиторий с веткой воркера + целевой клон, оба у сервисного юзера."""
    import getpass
    me = getpass.getuser()
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    orch = tmp_path / "orch"
    branch = "adhoc-913188/vanilla-frontend"

    def run(*args, cwd=None):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)

    run("git", "init", "-q", "-b", "main", str(src))
    run("git", "-C", str(src), "config", "user.email", "w@t")
    run("git", "-C", str(src), "config", "user.name", "W")
    (src / "a.txt").write_text("base\n")
    run("git", "-C", str(src), "add", "-A")
    run("git", "-C", str(src), "commit", "-qm", "base")
    run("git", "-C", str(src), "branch", branch)
    run("git", "clone", "-q", str(src), str(dst))
    run("git", "-C", str(dst), "config", "user.email", "w@t")
    run("git", "-C", str(dst), "config", "user.name", "W")
    orch.mkdir()

    calls: list[str] = []

    def local_ssh(host, cmd, *, check=True, capture=True):
        calls.append(cmd)
        argv = ["sudo", "bash", "-c", cmd] if host.startswith("root@") else ["bash", "-c", cmd]
        return subprocess.run(argv, check=check, text=True, capture_output=capture)

    def local_scp(source, dest, *, recursive=False):
        argv = ["sudo", "cp"] + (["-r"] if recursive else []) + [_strip_host(source), _strip_host(dest)]
        subprocess.run(argv, check=True, capture_output=True)

    monkeypatch.setattr(migrate_agent, "ssh", local_ssh)
    monkeypatch.setattr(migrate_agent, "scp", local_scp)
    yield SimpleNamespace(me=me, src=src, dst=dst, orch=orch, branch=branch, calls=calls)
    subprocess.run(["sudo", "chown", "-R", f"{me}:{me}", str(tmp_path)], capture_output=True)


@requires_two_users
def test_migrated_worker_can_actually_commit(migration_stand):
    """Главная проверка: не «права выставлены», а СДЕЛАН коммит в перенесённом worktree.

    Читать мигрированный воркер мог и раньше — падал только коммит, на блокировке
    .git/refs/heads/<branch>. Такой воркер выглядит исправным и тихо теряет работу.
    """
    s = migration_stand
    row = {"name": "vanilla-frontend", "branch": s.branch,
           "scope": str(s.src), "worktree_path": "/old/worktrees/vanilla-frontend"}

    src_repo, dst_repo, target = migrate_agent.target_worktree(
        "root@src", row, str(s.src), str(s.dst), str(s.orch),
    )
    new_wt = migrate_agent.migrate_git(
        "root@src", "root@dst", row, src_repo, dst_repo, target, s.me,
    )

    wt = pathlib.Path(new_wt)
    assert wt.is_dir()
    (wt / "a.txt").write_text("worker edit\n")
    add = subprocess.run(["git", "-C", str(wt), "add", "-A"], capture_output=True, text=True)
    commit = subprocess.run(
        ["git", "-C", str(wt), "commit", "-m", "worker work"], capture_output=True, text=True,
    )
    assert add.returncode == 0, add.stderr
    assert commit.returncode == 0, commit.stderr


@requires_two_users
def test_nothing_is_left_behind_for_the_login_user(migration_stand):
    """Ни worktree, ни .git целевого репозитория не остаются за чужим владельцем."""
    s = migration_stand
    row = {"name": "vanilla-frontend", "branch": s.branch,
           "scope": str(s.src), "worktree_path": "/old/worktrees/vanilla-frontend"}

    src_repo, dst_repo, target = migrate_agent.target_worktree(
        "root@src", row, str(s.src), str(s.dst), str(s.orch),
    )
    new_wt = migrate_agent.migrate_git(
        "root@src", "root@dst", row, src_repo, dst_repo, target, s.me,
    )

    for path in (new_wt, str(s.dst / ".git")):
        foreign = subprocess.run(
            ["find", path, "!", "-user", s.me], capture_output=True, text=True,
        )
        assert foreign.stdout.strip() == "", f"чужие владельцы под {path}: {foreign.stdout}"


@requires_two_users
def test_no_permanent_safe_directory_is_written_on_the_host(migration_stand):
    """safe.directory передаётся на один вызов, а не прописывается в чужой gitconfig."""
    s = migration_stand
    row = {"name": "vanilla-frontend", "branch": s.branch,
           "scope": str(s.src), "worktree_path": "/old/worktrees/vanilla-frontend"}

    src_repo, dst_repo, target = migrate_agent.target_worktree(
        "root@src", row, str(s.src), str(s.dst), str(s.orch),
    )
    migrate_agent.migrate_git("root@src", "root@dst", row, src_repo, dst_repo, target, s.me)

    assert not [c for c in s.calls if "config --global" in c]
    assert [c for c in s.calls if "-c safe.directory=" in c]


# ── репозиторий воркера: спрашиваем git, а не выводим из scope ──

class TestWorkerRepoIsAskedOfGit:
    """#69: один scope может держать несколько независимых репозиториев.

    У seedon внутри проекта лежат `site/` и `infra/` — свои git root'ы со своими origin.
    Слаг каталога worktree платформа считает от REPO ROOT (`create_worktree`), поэтому
    расчёт от scope уводит перенесённую копию туда, куда платформа никогда не заглянет.
    """

    ROW = {
        "id": "s1", "name": "seo-cro",
        "scope": "/home/kesha/projects/seedon",
        "worktree_path": "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon-site/seo-cro",
    }

    def test_nested_repo_defines_slug_and_target(self, monkeypatch):
        def _ssh(host, cmd, *, check=True, capture=True):
            assert "rev-parse --git-common-dir" in cmd
            return subprocess.CompletedProcess(
                [], 0, stdout="/home/kesha/projects/seedon/site\n", stderr="",
            )

        monkeypatch.setattr(migrate_agent, "ssh", _ssh)

        src, dst, wt = migrate_agent.target_worktree(
            "root@src", self.ROW,
            "/home/kesha/projects/seedon", "/srv/projects/seedon", "/srv/orchestra",
        )

        assert src == "/home/kesha/projects/seedon/site"
        assert dst == "/srv/projects/seedon/site"
        # слаг от РЕПОЗИТОРИЯ: .../srv-projects-seedon-site/..., а не .../srv-projects-seedon/...
        assert wt == "/srv/orchestra/worktrees/srv-projects-seedon-site/seo-cro"

    def test_scope_slug_would_have_been_wrong(self, monkeypatch):
        """Прямая проверка регрессии: расчёт от scope даёт ДРУГОЙ каталог."""
        monkeypatch.setattr(migrate_agent, "ssh", lambda *a, **k: subprocess.CompletedProcess(
            [], 0, stdout="/home/kesha/projects/seedon/site\n", stderr="",
        ))
        _, _, wt = migrate_agent.target_worktree(
            "root@src", self.ROW,
            "/home/kesha/projects/seedon", "/srv/projects/seedon", "/srv/orchestra",
        )
        slug_dir = wt.split("/worktrees/")[1].split("/")[0]
        assert slug_dir == migrate_agent.slugify_repo("/srv/projects/seedon/site")
        assert slug_dir != migrate_agent.slugify_repo("/srv/projects/seedon")

    def test_unreadable_worktree_falls_back_to_scope_loudly(self, monkeypatch, capsys):
        """Каталог не читается → фолбэк на scope, но С ПРЕДУПРЕЖДЕНИЕМ, а не молча."""
        monkeypatch.setattr(migrate_agent, "ssh", lambda *a, **k: subprocess.CompletedProcess(
            [], 128, stdout="", stderr="fatal: not a git repository",
        ))

        repo = migrate_agent.worker_repo("root@src", self.ROW, "/home/kesha/projects/seedon")

        assert repo == "/home/kesha/projects/seedon"
        assert "cannot read the repository" in capsys.readouterr().out

    def test_orchestrator_without_worktree_uses_scope(self, monkeypatch):
        monkeypatch.setattr(migrate_agent, "ssh", lambda *a, **k: pytest.fail(
            "для сессии без worktree git спрашивать незачем"))

        assert migrate_agent.worker_repo(
            "root@src", {"name": "orch", "worktree_path": ""}, "/home/kesha/projects/seedon",
        ) == "/home/kesha/projects/seedon"


@pytest.fixture
def nested_stand(tmp_path, monkeypatch):
    """Проект с ВЛОЖЕННЫМ независимым репозиторием — как `seedon/site` у seedon."""
    import getpass
    me = getpass.getuser()
    src_proj, dst_proj, orch = tmp_path / "src", tmp_path / "dst", tmp_path / "orch"
    branch = "feat/site-worker"

    def run(*args, cwd=None):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)

    for proj in (src_proj, dst_proj):
        run("git", "init", "-q", "-b", "main", str(proj))
        run("git", "-C", str(proj), "config", "user.email", "w@t")
        run("git", "-C", str(proj), "config", "user.name", "W")
        (proj / "root.txt").write_text("root\n")
        run("git", "-C", str(proj), "add", "-A")
        run("git", "-C", str(proj), "commit", "-qm", "root")

    src_site = src_proj / "site"
    run("git", "init", "-q", "-b", "main", str(src_site))
    run("git", "-C", str(src_site), "config", "user.email", "w@t")
    run("git", "-C", str(src_site), "config", "user.name", "W")
    (src_site / "site.txt").write_text("site\n")
    run("git", "-C", str(src_site), "add", "-A")
    run("git", "-C", str(src_site), "commit", "-qm", "site")
    run("git", "-C", str(src_site), "branch", branch)
    run("git", "clone", "-q", str(src_site), str(dst_proj / "site"))
    run("git", "-C", str(dst_proj / "site"), "config", "user.email", "w@t")
    run("git", "-C", str(dst_proj / "site"), "config", "user.name", "W")

    # рабочая копия воркера на ИСХОДНОМ хосте — принадлежит вложенному репозиторию
    src_wt = tmp_path / "src-worktrees" / "site-worker"
    run("git", "-C", str(src_site), "worktree", "add", "-q", str(src_wt), branch)
    orch.mkdir()

    def local_ssh(host, cmd, *, check=True, capture=True):
        argv = ["sudo", "bash", "-c", cmd] if host.startswith("root@") else ["bash", "-c", cmd]
        return subprocess.run(argv, check=check, text=True, capture_output=capture)

    def local_scp(source, dest, *, recursive=False):
        argv = ["sudo", "cp"] + (["-r"] if recursive else []) + [_strip_host(source), _strip_host(dest)]
        subprocess.run(argv, check=True, capture_output=True)

    monkeypatch.setattr(migrate_agent, "ssh", local_ssh)
    monkeypatch.setattr(migrate_agent, "scp", local_scp)
    yield SimpleNamespace(me=me, src_proj=src_proj, dst_proj=dst_proj, orch=orch,
                          src_wt=src_wt, branch=branch)
    subprocess.run(["sudo", "chown", "-R", f"{me}:{me}", str(tmp_path)], capture_output=True)


@requires_two_users
def test_nested_repo_worker_migrates_into_its_own_repo(nested_stand):
    """#69 сквозняком: воркер вложенного репозитория приезжает в СВОЙ репозиторий и коммитит.

    До правки бандл собирался из корневого репо (ветки там нет), а путь считался от scope —
    копия оказывалась в каталоге, куда платформа не заглядывает.
    """
    s = nested_stand
    row = {"id": "s1", "name": "site-worker", "branch": s.branch,
           "scope": str(s.src_proj), "worktree_path": str(s.src_wt)}

    src_repo, dst_repo, target = migrate_agent.target_worktree(
        "root@src", row, str(s.src_proj), str(s.dst_proj), str(s.orch),
    )

    assert src_repo == str(s.src_proj / "site"), "репозиторий обязан прийти из git, а не из scope"
    assert dst_repo == str(s.dst_proj / "site")
    assert target.split("/worktrees/")[1].split("/")[0] == migrate_agent.slugify_repo(dst_repo)

    new_wt = migrate_agent.migrate_git("root@src", "root@dst", row,
                                       src_repo, dst_repo, target, s.me)

    wt = pathlib.Path(new_wt)
    assert (wt / "site.txt").is_file(), "приехало содержимое вложенного репо, а не корневого"
    (wt / "site.txt").write_text("worker edit\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, capture_output=True)
    commit = subprocess.run(["git", "-C", str(wt), "commit", "-m", "work"],
                            capture_output=True, text=True)
    assert commit.returncode == 0, commit.stderr
