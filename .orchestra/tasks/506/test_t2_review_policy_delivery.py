import subprocess


ANCHORS = (
    "Implementation model review runs only on the final committed task diff after all tickets are complete.",
    "Never run model review on an intermediate edit or ticket.",
    "The threshold is <=40 changed lines AND <=3 files on the complete pinned diff.",
    "Size skip requires the literal JSON boolean `required=false`; omitted, null, unknown, malformed, or `required=true` runs review.",
    "`n=2`, and the first observed blocker sits three lines above it (#502 round 1, 43 lines / 2 files).",
    "`production_paths_json` is never the size oracle.",
    "A size skip writes a completed auditable receipt with the measured lines/files and threshold.",
)


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(path):
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("test\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "base")
    return path


def test_t2_final_diff_threshold_policy_reaches_both_runtime_skill_homes(tmp_path):
    from app.prompting import inject_skills_to_worktree

    repo = _repo(tmp_path / "consumer")
    assert inject_skills_to_worktree(["codex-debate"], str(repo), ".codex") == 1
    assert inject_skills_to_worktree(["codex-debate"], str(repo), ".claude") == 1

    codex = (repo / ".codex/skills/codex-debate/SKILL.md").read_text()
    claude = (repo / ".claude/skills/codex-debate/SKILL.md").read_text()
    assert codex == claude
    for anchor in ANCHORS:
        assert codex.count(anchor) == 1, f"T2 missing delivered policy anchor: {anchor}"

    # Owner kept both after #506: executable ceiling remains three, and Luna-over-Sol/Opus
    # remains a valid route. The policy edit must not remove either while adding the skip.
    assert "| Исполняемый: дифф, код, скрипт | **3 раунда** |" in codex
    assert 'codex_review(model="gpt5.6luna", ...)' in codex
