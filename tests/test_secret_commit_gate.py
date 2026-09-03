"""#453 — гейт, физически не пускающий секрет в git.

Три плеча, и каждое проверяет своё:
  * значение провайдерского формата ловится и коммит отбивается;
  * РЕАЛЬНЫЕ файлы репозитория с теми же формами проходят (негативный контроль — без него
    гейт мерит не то и будет выключен на второй день);
  * хук, поставленный в общий `.git/hooks`, действует в linked worktree.

Значения-приманки собираются генератором с фиксированным seed, а не пишутся литералом:
литерал секретного формата в этом файле отбивался бы собственным гейтом при коммите.
"""

import random
import string
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCANNER = REPO / "scripts" / "secret_scan.py"
sys.path.insert(0, str(REPO / "scripts"))

from secret_scan import scan_text  # noqa: E402

_B62 = string.ascii_letters + string.digits
_B64URL = _B62 + "_-"


def _payload(alphabet: str, n: int, seed: int) -> str:
    rnd = random.Random(seed)
    return "".join(rnd.choice(alphabet) for _ in range(n))


# Формат каждого провайдера целиком: префикс + точные длина и алфавит нагрузки.
SECRETS = {
    "yandex-oauth": "y0_" + _payload(_B64URL, 55, 1),
    "openrouter": "sk-or-v1-" + _payload("0123456789abcdef", 64, 2),
    "anthropic": "sk-ant-api03-" + _payload(_B64URL, 95, 3),
    "google-oauth": "ya29." + _payload(_B64URL, 60, 4),
    "github": "ghp_" + _payload(_B62, 36, 5),
    "github-pat": "github_pat_" + _payload(_B62 + "_", 82, 9),
    "google-api-key": "AIza" + _payload(_B64URL, 35, 6),
    "bearer": "Authorization: Bearer " + _payload(_B62, 40, 7),
    "pem-private-key": (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + _payload(_B62 + "+/", 64, 8)
        + "\n-----END RSA PRIVATE KEY-----"
    ),
}

# Обходы, найденные ревью Luna (#453). Каждый — точная форма, которая раньше проходила.
EVASIONS = {
    # Ключ Google service-account живёт в JSON с ЭКРАНИРОВАННЫМИ переводами строки.
    "escaped-pem": (
        '{"private_key": "-----BEGIN PRIVATE KEY-----\\n'
        + _payload(_B62 + "+/", 64, 10)
        + '\\n-----END PRIVATE KEY-----\\n"}'
    ),
    # Валидный токен, в нагрузке которого случайно есть слово-заглушка: формат сильнее слова.
    "placeholder-inside-valid-token": "ghp_" + _payload(_B62, 32, 11) + "test",
}

# Реальные файлы репозитория, где те же формы написаны НАМЕРЕННО.
MENTIONS = (
    "tests/test_secret_mask.py",
    ".orchestra/tasks/315/acceptance/fixtures/t5_recovery_records.json",
    "CLAUDE.md",
    ".orchestra/kb/repo-ops.md",
    "app/runtime_history.py",
    "app/secret_mask.py",
)


@pytest.mark.parametrize("rule", sorted(SECRETS))
def test_value_of_provider_format_is_caught(rule):
    findings = scan_text(SECRETS[rule], "probe.txt")
    assert findings, f"{rule}: значение провайдерского формата не поймано"
    assert any(rule in f for f in findings), f"{rule}: поймано другим правилом: {findings}"


@pytest.mark.parametrize("case", sorted(EVASIONS))
def test_known_evasions_are_caught(case):
    assert scan_text(EVASIONS[case], "probe.txt"), f"{case}: обход не закрыт"


@pytest.mark.parametrize("relpath", MENTIONS)
def test_real_files_with_the_same_forms_pass(relpath):
    """Негативный контроль на настоящих файлах, а не на выдуманных."""
    path = REPO / relpath
    assert path.exists(), f"{relpath} исчез — контроль стал вакуумным"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert scan_text(text, relpath) == []


def test_findings_never_print_the_value():
    """Сообщение гейта не должно само публиковать секрет."""
    for value in SECRETS.values():
        for finding in scan_text(value, "probe.txt"):
            assert value.split()[-1] not in finding


def _git(cwd, *args, **kw):
    return subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True, **kw)


@pytest.fixture
def scratch_repo(tmp_path):
    """Клон гейта в отдельном репозитории: коммитить в боевой ради теста нельзя."""
    root = tmp_path / "repo"
    (root / "scripts" / "hooks").mkdir(parents=True)
    for name in ("pre-commit", "commit-msg", "pre-push"):
        dst = root / "scripts" / "hooks" / name
        dst.write_text((REPO / "scripts" / "hooks" / name).read_text())
        dst.chmod(0o755)
    (root / "scripts" / "secret_scan.py").write_text(SCANNER.read_text())
    (root / "scripts" / "install_git_hooks.py").write_text(
        (REPO / "scripts" / "install_git_hooks.py").read_text()
    )
    _git(root, "init", "-q", ".", check=True)
    _git(root, "config", "user.email", "t@example.com", check=True)
    _git(root, "config", "user.name", "t", check=True)
    _git(root, "add", "-A", check=True)
    _git(root, "commit", "-qm", "init", check=True)
    install = subprocess.run(
        (sys.executable, str(root / "scripts" / "install_git_hooks.py")),
        cwd=root, capture_output=True, text=True,
    )
    assert install.returncode == 0, install.stderr
    return root


def test_hook_blocks_commit_of_a_secret(scratch_repo):
    (scratch_repo / "leak.json").write_text('{"api_key": "%s"}\n' % SECRETS["openrouter"])
    _git(scratch_repo, "add", "leak.json", check=True)
    res = _git(scratch_repo, "commit", "-m", "leak")
    assert res.returncode != 0, "коммит с секретом прошёл"
    assert "openrouter" in res.stderr
    assert _git(scratch_repo, "log", "--oneline").stdout.count("\n") == 1


def test_hook_lets_a_mention_through(scratch_repo):
    """То же плечо наоборот: правило и фикстура с теми же формами коммитятся."""
    (scratch_repo / "rules.md").write_text(
        (REPO / ".orchestra/tasks/315/acceptance/fixtures/t5_recovery_records.json").read_text()
        + "\nФормы: `y0_`, `sk-or-v1-`, `gh[pousr]_`, `AIza`, `ya29.`, `Bearer <25+>`\n"
    )
    _git(scratch_repo, "add", "rules.md", check=True)
    res = _git(scratch_repo, "commit", "-m", "mention")
    assert res.returncode == 0, res.stderr


def test_hook_from_common_dir_covers_linked_worktree(scratch_repo, tmp_path):
    """Установка одна, а деревьев 37: хук обязан сработать в linked worktree."""
    wt = tmp_path / "wt"
    _git(scratch_repo, "worktree", "add", "-q", str(wt), "-b", "wtbr", check=True)
    (wt / "leak.txt").write_text(SECRETS["github"] + "\n")
    _git(wt, "add", "leak.txt", check=True)
    res = _git(wt, "commit", "-m", "leak from worktree")
    assert res.returncode != 0, "коммит из linked worktree прошёл — хук туда не доехал"
    assert "github" in res.stderr


def test_missing_scanner_fails_closed_and_names_the_cause(scratch_repo):
    """Гейт пропал из чекаута → коммит отбит с названной причиной, а не пропущен молча."""
    (scratch_repo / "scripts" / "secret_scan.py").unlink()
    (scratch_repo / "ok.txt").write_text("совершенно безобидный файл\n")
    _git(scratch_repo, "add", "ok.txt", check=True)
    res = _git(scratch_repo, "commit", "-m", "no scanner")
    assert res.returncode != 0
    assert "secret-gate" in res.stderr and "secret_scan.py" in res.stderr


def test_pre_push_catches_what_no_verify_committed(scratch_repo, tmp_path):
    """Второй рубеж: pre-commit обойдён `--no-verify`, публикация всё равно отбита."""
    remote = tmp_path / "remote.git"
    _git(scratch_repo, "init", "-q", "--bare", str(remote), check=True)
    _git(scratch_repo, "remote", "add", "origin", str(remote), check=True)
    (scratch_repo / "leak.txt").write_text(SECRETS["yandex-oauth"] + "\n")
    _git(scratch_repo, "add", "leak.txt", check=True)
    bypass = _git(scratch_repo, "commit", "--no-verify", "-m", "bypassed")
    assert bypass.returncode == 0, "не удалось воспроизвести обход pre-commit"
    res = _git(scratch_repo, "push", "origin", "HEAD:refs/heads/main")
    assert res.returncode != 0, "секрет опубликован"
    assert "yandex-oauth" in res.stderr


def test_commit_msg_hook_blocks_a_secret_in_the_message(scratch_repo):
    """Сообщение коммита публикуется наравне с содержимым, а pre-commit его не видит."""
    (scratch_repo / "ok.txt").write_text("безобидно\n")
    _git(scratch_repo, "add", "ok.txt", check=True)
    res = _git(scratch_repo, "commit", "-m", "чиню токен " + SECRETS["github"])
    assert res.returncode != 0, "коммит с секретом в сообщении прошёл"
    assert "github" in res.stderr


def test_pre_push_scans_every_published_commit_not_the_net_diff(scratch_repo, tmp_path):
    """Файл добавлен одним коммитом и удалён следующим: в итоговом диффе его нет, в истории есть."""
    remote = tmp_path / "remote.git"
    _git(scratch_repo, "init", "-q", "--bare", str(remote), check=True)
    _git(scratch_repo, "remote", "add", "origin", str(remote), check=True)
    (scratch_repo / "leak.txt").write_text(SECRETS["google-api-key"] + "\n")
    _git(scratch_repo, "add", "leak.txt", check=True)
    _git(scratch_repo, "commit", "--no-verify", "-m", "add", check=True)
    (scratch_repo / "leak.txt").unlink()
    _git(scratch_repo, "add", "-A", check=True)
    _git(scratch_repo, "commit", "--no-verify", "-m", "remove", check=True)
    res = _git(scratch_repo, "push", "origin", "HEAD:refs/heads/main")
    assert res.returncode != 0, "секрет опубликован в промежуточном коммите"
    assert "google-api-key" in res.stderr


def test_typechange_to_symlink_is_scanned(scratch_repo):
    """`--diff-filter=ACM` не содержал `T`: токен уезжал в ЦЕЛЬ симлинка."""
    target = scratch_repo / "conf"
    target.write_text("плейсхолдер\n")
    _git(scratch_repo, "add", "conf", check=True)
    _git(scratch_repo, "commit", "-m", "conf", check=True)
    target.unlink()
    target.symlink_to(SECRETS["github"])
    _git(scratch_repo, "add", "-A", check=True)
    res = _git(scratch_repo, "commit", "-m", "symlink")
    assert res.returncode != 0, "смена типа файла не просканирована"
    assert "github" in res.stderr


def test_gitlink_and_non_utf8_path_do_not_block_an_honest_commit(scratch_repo):
    """Обе записи ломали `git show :<путь>` → fail-closed отбивал безобидный коммит."""
    (scratch_repo / b"bad\x80.txt".decode("utf-8", "surrogateescape")).write_text("чисто\n")
    _git(scratch_repo, "add", "-A", check=True)
    # Порядок важен: `git add -A` не видит `sub` на диске и снял бы gitlink из индекса.
    _git(
        scratch_repo, "update-index", "--add", "--cacheinfo",
        f"160000,{'a' * 40},sub", check=True,
    )
    staged = _git(scratch_repo, "diff", "--cached", "--raw").stdout
    assert "160000" in staged and "bad" in staged, f"нечего проверять: {staged!r}"
    res = _git(scratch_repo, "commit", "-m", "submodule + странное имя")
    assert res.returncode == 0, res.stderr


def test_installer_refuses_when_git_uses_another_hooks_dir(scratch_repo, tmp_path):
    """core.hooksPath уводит вызовы мимо `.git/hooks` — установка обязана отказать, а не соврать."""
    other = tmp_path / "other-hooks"
    other.mkdir()
    _git(scratch_repo, "config", "core.hooksPath", str(other), check=True)
    res = subprocess.run(
        (sys.executable, str(scratch_repo / "scripts" / "install_git_hooks.py")),
        cwd=scratch_repo, capture_output=True, text=True,
    )
    assert res.returncode != 0
    assert "core.hooksPath" in res.stderr
