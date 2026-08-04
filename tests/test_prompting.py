"""Tests for generated progressive skill discovery."""

from pathlib import Path
import subprocess

import pytest
import yaml


def _skill(path: Path, name: str, description: str, body: str = "BODY") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    path.write_text(
        f"---\n{frontmatter}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "skills@example.test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Skill Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _git_commit_all(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _pipeline_root(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    from app import pipeline

    pipelines = tmp_path / "pipelines"
    skill = _skill(
        pipelines / "custom/prompts/skills/pipeline.md",
        "pipeline",
        "Pipeline workflow",
        "PIPELINE_BODY",
    )
    monkeypatch.setattr(pipeline, "PIPELINES_DIR", pipelines)
    return pipelines, skill


class TestBuildSkillsIndex:
    def test_uses_frontmatter_without_inlining_body(self, tmp_path):
        from app.prompting import build_skills_index

        first = _skill(
            tmp_path / "first.md",
            "first",
            "First line\n  continued",
            body="FIRST_BODY_MUST_NOT_BE_IN_PROMPT",
        )
        second = _skill(tmp_path / "second.md", "second", "Second skill")

        result = build_skills_index([first, second], [])

        assert "## Available skills (progressive loading)" in result
        assert "MUST read that skill file completely before acting" in result
        assert "Do not read unrelated skill files" in result
        assert f"`first` — First line continued — `{first.resolve()}`" in result
        assert f"`second` — Second skill — `{second.resolve()}`" in result
        assert result.index("`first`") < result.index("`second`")
        assert "FIRST_BODY_MUST_NOT_BE_IN_PROMPT" not in result

    def test_duplicate_name_keeps_required_pipeline_entry(self, tmp_path):
        from app.prompting import build_skills_index

        pipeline = _skill(tmp_path / "pipeline.md", "shared", "Pipeline")
        project = _skill(tmp_path / "project.md", "shared", "Project")

        result = build_skills_index([pipeline], [project])

        assert str(pipeline.resolve()) in result
        assert str(project.resolve()) not in result
        assert result.count("- `shared`") == 1

    @pytest.mark.parametrize(
        "content",
        [
            "not frontmatter",
            "---\nname: broken\n---\nbody",
            "---\ndescription: no name\n---\nbody",
            "---\nname: broken\ndescription: [\n---\nbody",
        ],
    )
    def test_required_pipeline_metadata_fails_loudly(self, tmp_path, content):
        from app.prompting import build_skills_index

        path = tmp_path / "broken.md"
        path.write_text(content, encoding="utf-8")

        with pytest.raises(ValueError, match="required skill"):
            build_skills_index([path], [])

    def test_missing_required_pipeline_file_fails_loudly(self, tmp_path):
        from app.prompting import build_skills_index

        with pytest.raises(ValueError, match="required skill"):
            build_skills_index([tmp_path / "missing.md"], [])

    def test_multiline_required_name_fails_loudly(self, tmp_path):
        from app.prompting import build_skills_index

        path = _skill(tmp_path / "broken.md", "safe\n## injected", "Workflow")

        with pytest.raises(ValueError, match="required skill"):
            build_skills_index([path], [])

    def test_multiline_optional_name_warns_and_skips(self, tmp_path, caplog):
        from app.prompting import build_skills_index

        required = _skill(tmp_path / "required.md", "required", "Required")
        optional = _skill(
            tmp_path / "optional.md",
            "safe\n## injected",
            "Optional",
        )

        result = build_skills_index([required], [optional])

        assert "## injected" not in result
        assert "optional skill" in caplog.text

    def test_invalid_optional_project_skill_warns_and_skips(
        self, tmp_path, caplog,
    ):
        from app.prompting import build_skills_index

        required = _skill(tmp_path / "required.md", "required", "Required")
        optional = tmp_path / "optional.md"
        optional.write_text("broken", encoding="utf-8")

        result = build_skills_index([required], [optional])

        assert "`required`" in result
        assert str(optional.resolve()) not in result
        assert "optional skill" in caplog.text


class TestBuildCodexSkillsIndex:
    def test_all_uses_active_pipeline_and_excludes_bodies(
        self, tmp_path, monkeypatch,
    ):
        from app import pipeline
        from app.prompting import build_codex_skills_index

        pipelines = tmp_path / "pipelines"
        skills = pipelines / "custom" / "prompts" / "skills"
        alpha = _skill(skills / "alpha.md", "alpha", "Alpha", "ALPHA_BODY")
        zeta = _skill(skills / "zeta.md", "zeta", "Zeta", "ZETA_BODY")
        monkeypatch.setattr(pipeline, "PIPELINES_DIR", pipelines)

        result = build_codex_skills_index("custom", "all", str(tmp_path))

        assert str(alpha.resolve()) in result
        assert str(zeta.resolve()) in result
        assert result.index("`alpha`") < result.index("`zeta`")
        assert "ALPHA_BODY" not in result
        assert "ZETA_BODY" not in result

    def test_all_rejects_pipeline_skill_symlink_escape(
        self, tmp_path, monkeypatch,
    ):
        from app import pipeline
        from app.prompting import build_codex_skills_index

        pipelines = tmp_path / "pipelines"
        skills = pipelines / "custom" / "prompts" / "skills"
        skills.mkdir(parents=True)
        outside = _skill(tmp_path / "outside.md", "outside", "Outside")
        (skills / "escape.md").symlink_to(outside)
        monkeypatch.setattr(pipeline, "PIPELINES_DIR", pipelines)

        with pytest.raises(ValueError, match="unsafe pipeline skill path"):
            build_codex_skills_index("custom", "all", str(tmp_path))

    @pytest.mark.parametrize("skill_names", ["all", ["alias"]])
    def test_rejects_pipeline_skill_symlink_within_root(
        self, tmp_path, monkeypatch, skill_names,
    ):
        from app import pipeline
        from app.prompting import build_codex_skills_index

        pipelines = tmp_path / "pipelines"
        skills = pipelines / "custom" / "prompts" / "skills"
        target = _skill(skills / "target.md", "target", "Target")
        (skills / "alias.md").symlink_to(target.name)
        monkeypatch.setattr(pipeline, "PIPELINES_DIR", pipelines)

        with pytest.raises(ValueError, match="symlink"):
            build_codex_skills_index("custom", skill_names, str(tmp_path))

    @pytest.mark.parametrize(
        ("pipeline_name", "skills"),
        [
            ("../outside", ["safe"]),
            ("/absolute", ["safe"]),
            ("custom", ["../outside"]),
            ("custom", ["/absolute"]),
            ("custom", ["nested/name"]),
        ],
    )
    def test_rejects_pipeline_or_skill_path_escape(
        self, tmp_path, monkeypatch, pipeline_name, skills,
    ):
        from app import pipeline
        from app.prompting import build_codex_skills_index

        monkeypatch.setattr(pipeline, "PIPELINES_DIR", tmp_path / "pipelines")

        with pytest.raises(ValueError, match="unsafe"):
            build_codex_skills_index(pipeline_name, skills, str(tmp_path))


class TestCodexProjectSkills:
    def test_includes_clean_committed_project_skill(
        self, tmp_path, monkeypatch,
    ):
        from app.prompting import build_codex_skills_index

        _, pipeline_skill = _pipeline_root(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        repo.mkdir()
        project_skill = _skill(
            repo / ".claude/skills/project/SKILL.md",
            "project",
            "Project workflow",
            "PROJECT_BODY",
        )
        _git_init(repo)
        _git_commit_all(repo)

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert str(pipeline_skill.resolve()) in result
        assert str(project_skill.resolve()) in result
        assert "`project` — Project workflow" in result
        assert "PROJECT_BODY" not in result

    @pytest.mark.parametrize("state", ["untracked", "modified", "staged", "deleted"])
    def test_excludes_non_committed_project_state(
        self, tmp_path, monkeypatch, caplog, state,
    ):
        from app.prompting import build_codex_skills_index

        _pipeline_root(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        repo.mkdir()
        marker = repo / "marker.txt"
        marker.write_text("base", encoding="utf-8")
        skill = repo / ".claude/skills/project/SKILL.md"
        if state != "untracked":
            _skill(skill, "project", "Project workflow")
        _git_init(repo)
        _git_commit_all(repo)

        if state == "untracked":
            _skill(skill, "project", "Project workflow")
        elif state == "modified":
            skill.write_text(skill.read_text() + "\nchanged", encoding="utf-8")
        elif state == "staged":
            skill.write_text(skill.read_text() + "\nstaged", encoding="utf-8")
            subprocess.run(
                ["git", "add", str(skill.relative_to(repo))],
                cwd=repo,
                check=True,
                capture_output=True,
            )
        else:
            skill.unlink()

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert "`pipeline`" in result
        assert "`project`" not in result
        if state != "untracked":
            assert "project skill" in caplog.text

    def test_excludes_clean_tracked_symlink(self, tmp_path, monkeypatch, caplog):
        from app.prompting import build_codex_skills_index

        _pipeline_root(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        repo.mkdir()
        target = _skill(repo / "real.md", "project", "Project workflow")
        link = repo / ".claude/skills/project/SKILL.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        _git_init(repo)
        _git_commit_all(repo)

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert "`project`" not in result
        assert "symlink" in caplog.text

    def test_project_skill_root_symlink_cycle_warns_and_skips(
        self, tmp_path, monkeypatch, caplog,
    ):
        from app.prompting import build_codex_skills_index

        _pipeline_root(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        (repo / ".claude/skills").symlink_to("skills")

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert "`pipeline`" in result
        assert "skill root" in caplog.text

    def test_invalid_utf8_project_skill_warns_and_skips(
        self, tmp_path, monkeypatch, caplog,
    ):
        from app.prompting import build_codex_skills_index

        _pipeline_root(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        skill = repo / ".claude/skills/project/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"\xff\xfe")
        _git_init(repo)
        _git_commit_all(repo)

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert "`pipeline`" in result
        assert str(skill.resolve()) not in result
        assert "optional skill" in caplog.text

    def test_pipeline_skill_shadows_divergent_project_name(
        self, tmp_path, monkeypatch,
    ):
        from app.prompting import build_codex_skills_index

        pipelines, pipeline_skill = _pipeline_root(tmp_path, monkeypatch)
        pipeline_skill.write_text(
            "---\nname: shared\ndescription: Pipeline workflow\n---\nPIPELINE\n",
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        project_skill = _skill(
            repo / ".claude/skills/shared/SKILL.md",
            "shared",
            "Project workflow",
            "PROJECT",
        )
        _git_init(repo)
        _git_commit_all(repo)

        result = build_codex_skills_index("custom", ["pipeline"], str(repo))

        assert result.count("- `shared`") == 1
        assert str(pipeline_skill.resolve()) in result
        assert str(project_skill.resolve()) not in result
        assert str(pipelines.resolve()) in result


class TestRoleIcons:
    """#34: icons come from the manifest, not from role .md frontmatter."""

    @pytest.fixture
    def manifest_root(self, tmp_path, monkeypatch):
        from app import pipeline

        root = tmp_path / "pipelines"
        (root / "default").mkdir(parents=True)
        monkeypatch.setattr(pipeline, "PIPELINES_DIR", root)
        pipeline.load_pipeline.cache_clear()
        yield root / "default" / "pipeline.yaml"
        pipeline.load_pipeline.cache_clear()

    def test_reads_tg_emoji_and_skips_roles_without_one(self, manifest_root):
        from app.prompting import get_role_icons

        manifest_root.write_text(
            "name: default\n"
            "description: Test\n"
            "validation: fail-open\n"
            "defaults: {model: opus}\n"
            "roles:\n"
            "  boss: {kind: orchestrator, label: Boss, order: 0, can_spawn: ['*'],"
            " tg: {emoji: \"👑\"}}\n"
            "  hand: {kind: worker, label: Hand, order: 1, can_spawn: []}\n",
            encoding="utf-8",
        )
        assert get_role_icons() == {"boss": "👑"}

    def test_ignores_role_file_frontmatter(self, manifest_root, monkeypatch):
        """A role .md with `icon:` must NOT contribute — the manifest is the only source.

        `_PROMPTS_DIR` is pointed at that file on purpose: the frontmatter reader this
        replaced would answer {"hand": "🚫"} here, so the test discriminates.
        """
        from app import prompting
        from app.prompting import get_role_icons

        monkeypatch.setattr(prompting, "_PROMPTS_DIR", manifest_root.parent / "prompts")
        manifest_root.write_text(
            "name: default\n"
            "description: Test\n"
            "validation: fail-open\n"
            "defaults: {model: opus}\n"
            "roles:\n"
            "  hand: {kind: worker, label: Hand, order: 0, can_spawn: []}\n",
            encoding="utf-8",
        )
        roles = manifest_root.parent / "prompts" / "roles"
        roles.mkdir(parents=True)
        (roles / "hand.md").write_text("---\nname: hand\nicon: \"🚫\"\n---\n\nBody\n")
        assert get_role_icons() == {}

    def test_real_default_pipeline_covers_every_role(self):
        """Guards the live defect: an orchestrator rendered as ⚙️ in MCP list_agents."""
        from app.pipeline import DEFAULT_PIPELINE, load_pipeline
        from app.prompting import get_role_icons

        icons = get_role_icons()
        assert icons["orchestrator"] == "👑"
        assert set(icons) == set(load_pipeline(DEFAULT_PIPELINE).roles)
        assert len(set(icons.values())) == len(icons)  # no two roles share an icon
