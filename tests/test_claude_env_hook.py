import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HOOK = ROOT / "deploy/orchestra-claude-env.sh"
DROPIN = ROOT / "deploy/orchestra-claude-env.conf"
MANAGER = ROOT / "deploy/manage-claude-env-hook.sh"
PROBE = "CLAUDE_ENV_HOOK_PROBE"


def test_hook_is_only_the_two_function_unsets():
    assert HOOK.read_text() == "unset -f grep find 2>/dev/null || true\n"
    assert DROPIN.read_text() == (
        "[Service]\nEnvironment=CLAUDE_ENV_FILE=/etc/orchestra/claude-env.sh\n"
    )


def test_hook_runs_after_vendor_functions_and_restores_gnu_semantics(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "match.txt").write_text(f"{PROBE}\n")
    command = r'''
grep() { /bin/echo embedded-ugrep "$@"; }
find() { /bin/echo embedded-bfs "$@"; }
source "$HOOK"
printf 'grep_type=%s\n' "$(type -t grep)"
printf 'grep_path=%s\n' "$(type -P grep)"
printf 'find_type=%s\n' "$(type -t find)"
printf 'find_path=%s\n' "$(type -P find)"
grep "$PROBE" "$FIXTURE"
'''
    result = subprocess.run(
        ["bash", "-c", command],
        env={
            **os.environ,
            "HOOK": str(HOOK),
            "PROBE": PROBE,
            "FIXTURE": str(nested),
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert result.stdout.splitlines() == [
        "grep_type=file",
        "grep_path=/usr/bin/grep",
        "find_type=file",
        "find_path=/usr/bin/find",
    ]
    assert "Is a directory" in result.stderr

    recursive = subprocess.run(
        ["bash", "-c", 'source "$HOOK"; grep -r "$PROBE" "$FIXTURE"'],
        env={
            **os.environ,
            "HOOK": str(HOOK),
            "PROBE": PROBE,
            "FIXTURE": str(nested),
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert recursive.stdout == f"{nested}/match.txt:{PROBE}\n"


def _fake_command(path: Path, command: str) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'printf "{command} %s\\n" "$*" >> "$COMMAND_LOG"\n'
    )
    path.chmod(0o755)
    return path


def test_rollback_recovers_after_install_fails_between_files(tmp_path):
    destination = tmp_path / "root"
    existing_hook = destination / "etc/orchestra/claude-env.sh"
    existing_hook.parent.mkdir(parents=True)
    existing_hook.write_text("export PREVIOUS_HOOK=true\n")
    command_log = tmp_path / "commands.log"
    fake_systemctl = _fake_command(tmp_path / "systemctl", "systemctl")
    fake_analyze = _fake_command(tmp_path / "systemd-analyze", "systemd-analyze")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    install_count = tmp_path / "install-count"
    fake_install = fake_bin / "install"
    fake_install.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "count=0\n"
        '[[ ! -e "$INSTALL_COUNT" ]] || count=$(<"$INSTALL_COUNT")\n'
        "count=$((count + 1))\n"
        'printf "%s\\n" "$count" > "$INSTALL_COUNT"\n'
        '[[ "$count" -ne 2 ]] || exit 42\n'
        'exec /usr/bin/install "$@"\n'
    )
    fake_install.chmod(0o755)
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(fake_systemctl),
        "SYSTEMD_ANALYZE": str(fake_analyze),
        "COMMAND_LOG": str(command_log),
        "INSTALL_COUNT": str(install_count),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    failed = subprocess.run(
        [MANAGER, "install"], env=env, text=True, capture_output=True,
    )
    state = destination / "var/lib/orchestra-claude-env-hook/deploy-state"
    assert failed.returncode == 42
    assert state.is_dir()
    assert (state / "installed.sha256").is_file()

    rolled_back = subprocess.run(
        [MANAGER, "rollback"], env=env, text=True, capture_output=True,
    )

    dropin = destination / "etc/systemd/system/orchestra.service.d/211-claude-env.conf"
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert existing_hook.read_text() == "export PREVIOUS_HOOK=true\n"
    assert dropin.exists() is False
    assert list(destination.rglob("*.rollback-claim.*")) == []


def test_manager_rejects_malformed_hook_before_install(tmp_path):
    source_deploy = tmp_path / "source/deploy"
    source_deploy.mkdir(parents=True)
    manager = source_deploy / MANAGER.name
    manager.write_bytes(MANAGER.read_bytes())
    manager.chmod(0o755)
    (source_deploy / HOOK.name).write_text("broken (\n")
    (source_deploy / DROPIN.name).write_bytes(DROPIN.read_bytes())
    destination = tmp_path / "root"
    existing_hook = destination / "etc/orchestra/claude-env.sh"
    existing_hook.parent.mkdir(parents=True)
    existing_hook.write_text("export PREVIOUS_HOOK=true\n")
    command_log = tmp_path / "commands.log"
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(_fake_command(tmp_path / "systemctl", "systemctl")),
        "SYSTEMD_ANALYZE": str(
            _fake_command(tmp_path / "systemd-analyze", "systemd-analyze")
        ),
        "COMMAND_LOG": str(command_log),
    }

    failed = subprocess.run(
        [manager, "install"], env=env, text=True, capture_output=True,
    )

    dropin = destination / "etc/systemd/system/orchestra.service.d/211-claude-env.conf"
    state = destination / "var/lib/orchestra-claude-env-hook/deploy-state"
    assert failed.returncode == 2
    assert "syntax error" in failed.stderr
    assert existing_hook.read_text() == "export PREVIOUS_HOOK=true\n"
    assert dropin.exists() is False
    assert state.exists() is False
    assert command_log.exists() is False


def test_rollback_rejects_malformed_saved_hook_before_claiming(tmp_path):
    destination = tmp_path / "root"
    existing_hook = destination / "etc/orchestra/claude-env.sh"
    existing_hook.parent.mkdir(parents=True)
    existing_hook.write_text("broken (\n")
    command_log = tmp_path / "commands.log"
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(_fake_command(tmp_path / "systemctl", "systemctl")),
        "SYSTEMD_ANALYZE": str(
            _fake_command(tmp_path / "systemd-analyze", "systemd-analyze")
        ),
        "COMMAND_LOG": str(command_log),
    }
    subprocess.run(
        [MANAGER, "install"], env=env, text=True, capture_output=True, check=True,
    )

    refused = subprocess.run(
        [MANAGER, "rollback"], env=env, text=True, capture_output=True,
    )

    dropin = destination / "etc/systemd/system/orchestra.service.d/211-claude-env.conf"
    assert refused.returncode == 2
    assert "syntax error" in refused.stderr
    assert existing_hook.read_bytes() == HOOK.read_bytes()
    assert dropin.read_bytes() == DROPIN.read_bytes()
    assert list(destination.rglob("*.rollback-claim.*")) == []
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
    ]


def test_rollback_refuses_to_nest_state_in_existing_archive(tmp_path):
    destination = tmp_path / "root"
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_date = fake_bin / "date"
    fake_date.write_text("#!/usr/bin/env bash\nprintf '20260812T120000Z\\n'\n")
    fake_date.chmod(0o755)
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(_fake_command(tmp_path / "systemctl", "systemctl")),
        "SYSTEMD_ANALYZE": str(
            _fake_command(tmp_path / "systemd-analyze", "systemd-analyze")
        ),
        "COMMAND_LOG": str(command_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    subprocess.run(
        [MANAGER, "install"], env=env, text=True, capture_output=True, check=True,
    )
    state_root = destination / "var/lib/orchestra-claude-env-hook"
    archive = state_root / "rollback-20260812T120000Z"
    archive.mkdir()
    (archive / "retained").write_text("keep\n")

    refused = subprocess.run(
        [MANAGER, "rollback"], env=env, text=True, capture_output=True,
    )

    assert refused.returncode == 1
    assert "without overwriting retained data" in refused.stderr
    assert (archive / "retained").read_text() == "keep\n"
    assert (state_root / "deploy-state").is_dir()
    assert (archive / "deploy-state").exists() is False


def test_manager_installs_without_restart_and_rolls_back_existing_file(tmp_path):
    destination = tmp_path / "root"
    existing_hook = destination / "etc/orchestra/claude-env.sh"
    existing_hook.parent.mkdir(parents=True)
    existing_hook.write_text("previous\n")
    existing_hook.chmod(0o640)
    command_log = tmp_path / "commands.log"
    fake_systemctl = _fake_command(tmp_path / "systemctl", "systemctl")
    fake_analyze = _fake_command(tmp_path / "systemd-analyze", "systemd-analyze")
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(fake_systemctl),
        "SYSTEMD_ANALYZE": str(fake_analyze),
        "COMMAND_LOG": str(command_log),
    }

    subprocess.run(["bash", "-n", MANAGER], check=True)
    installed = subprocess.run(
        [MANAGER, "install"], env=env, text=True, capture_output=True, check=True,
    )

    dropin = destination / "etc/systemd/system/orchestra.service.d/211-claude-env.conf"
    assert existing_hook.read_bytes() == HOOK.read_bytes()
    assert dropin.read_bytes() == DROPIN.read_bytes()
    assert "restart is required and was NOT performed" in installed.stdout
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
    ]

    existing_hook.write_text("manual post-install change\n")
    refused = subprocess.run(
        [MANAGER, "rollback"], env=env, text=True, capture_output=True,
    )
    assert refused.returncode == 1
    assert "changed since install" in refused.stderr
    assert existing_hook.read_text() == "manual post-install change\n"
    assert dropin.read_bytes() == DROPIN.read_bytes()
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
    ]

    existing_hook.write_bytes(HOOK.read_bytes())

    collision_bin = tmp_path / "collision-bin"
    collision_bin.mkdir()
    fake_mv = collision_bin / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'for argument in "$@"; do target=$argument; done\n'
        'if [[ "$target" == *rollback-claim* && ! -e "$COLLISION_FLAG" ]]; then\n'
        '  printf "retained claim\\n" > "$target"\n'
        '  touch "$COLLISION_FLAG"\n'
        "fi\n"
        'exec /usr/bin/mv "$@"\n'
    )
    fake_mv.chmod(0o755)
    collision_env = {
        **env,
        "PATH": f"{collision_bin}:{env['PATH']}",
        "COLLISION_FLAG": str(tmp_path / "collision-injected"),
    }
    collided = subprocess.run(
        [MANAGER, "rollback"], env=collision_env, text=True, capture_output=True,
    )
    assert collided.returncode == 1
    assert "without overwriting retained data" in collided.stderr
    assert existing_hook.read_bytes() == HOOK.read_bytes()
    retained = list(existing_hook.parent.glob(f"{existing_hook.name}.rollback-claim.*"))
    assert len(retained) == 1
    assert retained[0].read_text() == "retained claim\n"
    retained[0].unlink()
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
    ]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sha = fake_bin / "sha256sum"
    fake_sha.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == *rollback-claim* && ! -e "$INJECT_FLAG" ]]; then\n'
        '  printf "concurrent replacement\\n" > "$INJECT_DEST"\n'
        '  touch "$INJECT_FLAG"\n'
        "fi\n"
        'exec /usr/bin/sha256sum "$@"\n'
    )
    fake_sha.chmod(0o755)
    raced_env = {
        **env,
        "PATH": f"{fake_bin}:{env['PATH']}",
        "INJECT_DEST": str(existing_hook),
        "INJECT_FLAG": str(tmp_path / "injected"),
    }
    raced = subprocess.run(
        [MANAGER, "rollback"], env=raced_env, text=True, capture_output=True,
    )
    assert raced.returncode == 1
    assert "Destination appeared during rollback" in raced.stderr
    assert existing_hook.read_text() == "concurrent replacement\n"
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
    ]

    for destination_file in (existing_hook, dropin):
        claims = list(destination_file.parent.glob(f"{destination_file.name}.rollback-claim.*"))
        assert len(claims) == 1
        if destination_file.exists():
            destination_file.unlink()
        claims[0].replace(destination_file)
        for temporary in destination_file.parent.glob(f"{destination_file.name}.restore.*"):
            temporary.unlink()

    rolled_back = subprocess.run(
        [MANAGER, "rollback"], env=env, text=True, capture_output=True, check=True,
    )

    assert existing_hook.read_text() == "previous\n"
    assert existing_hook.stat().st_mode & 0o777 == 0o640
    assert dropin.exists() is False
    assert "restart is required and was NOT performed" in rolled_back.stdout
    assert command_log.read_text().splitlines() == [
        "systemd-analyze verify orchestra.service",
        "systemctl daemon-reload",
        "systemctl daemon-reload",
    ]
    assert list((destination / "var/lib/orchestra-claude-env-hook").glob("rollback-*"))
