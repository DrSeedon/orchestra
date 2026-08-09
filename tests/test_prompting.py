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


class TestCodexProjectDocPreflight:
    def _config(self, root: Path, budget: int) -> Path:
        root.mkdir(parents=True)
        (root / "config.toml").write_text(
            f"project_doc_max_bytes = {budget}\n", encoding="utf-8",
        )
        return root

    def test_exact_budget_is_not_reported_as_truncated(self, tmp_path):
        from app.prompting import codex_project_doc_preflight

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "AGENTS.md").write_bytes(b"1234")

        result = codex_project_doc_preflight(
            str(repo), codex_home=str(self._config(tmp_path / "codex", 4)),
        )

        assert result.actual_bytes == 4
        assert result.budget_bytes == 4
        assert result.first_truncated_line is None
        assert result.instruction == ""

    def test_multibyte_overflow_reports_first_incomplete_line_and_bounded_fallback(
        self, tmp_path,
    ):
        from app.prompting import codex_project_doc_preflight

        repo = tmp_path / "repo"
        repo.mkdir()
        content = "α\nβ\nγ\n"
        (repo / "AGENTS.md").write_text(content, encoding="utf-8")

        result = codex_project_doc_preflight(
            str(repo), codex_home=str(self._config(tmp_path / "codex", 4)),
        )

        assert result.actual_bytes == len(content.encode("utf-8"))
        assert result.first_truncated_line == 2
        assert "4" in result.diagnostic
        assert "line 2" in result.diagnostic
        assert "from line 2 through EOF once" in result.instruction
        assert len(result.instruction) < 600
        assert (repo / "AGENTS.md").read_text(encoding="utf-8") == content

    def test_malformed_config_diagnoses_unknown_budget_without_claiming_truncation(
        self, tmp_path,
    ):
        from app.prompting import codex_project_doc_preflight

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "AGENTS.md").write_text("large" * 100, encoding="utf-8")
        codex_home = tmp_path / "codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text("not = [toml", encoding="utf-8")

        result = codex_project_doc_preflight(
            str(repo), codex_home=str(codex_home),
        )

        assert result.budget_bytes is None
        assert result.first_truncated_line is None
        assert result.instruction == ""
        assert "budget unavailable" in result.diagnostic


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


class TestHtmlArtifactsSkillInvariants:
    """Скилл обязан ВЫВОДИТЬ палитру, а не носить свою.

    Не сравнение с глобальным `~/.claude/skills/html-artifacts/` — его нет ни в репозитории,
    ни в CI. Поэтому фиксируем то, ради чего правился этот файл (#119): захардкоженный акцент
    сделал пять независимых артефактов одинаково фиолетовыми (`--accent: #7c3aed`, M1 = 1
    уникальный из 5, M2 = 5 фиолетовых из 5).
    """

    SKILL = (
        Path(__file__).parent.parent
        / "pipelines" / "default" / "prompts" / "skills" / "html-artifacts.md"
    )

    def test_accent_is_never_given_a_value(self):
        """Акцент — единственный цвет, которому нельзя иметь значение в скилле.

        Запрет «никаких цветовых литералов вообще» снят в #128: костяк несёт нейтрали и
        шесть тонов серий дословно, и это осознанная правка — принцип без значений
        не исполнялся ни разу из пяти. Защищать надо ровно то, что сломалось в #119:
        готовый `--accent` делает пять независимых артефактов одноцветными.
        """
        import re

        text = self.SKILL.read_text(encoding="utf-8")
        assigned = re.findall(r"--accent\s*:\s*([^;\n]+)", text)
        literals = [v for v in assigned if re.search(r"#[0-9a-fA-F]{3,8}|(?:rgb|hsl)a?\(\s*\d", v)]
        assert literals == [], (
            f"акценту снова задано значение: {literals}. Он обязан выводиться из предмета "
            f"артефакта, иначе все артефакты снова станут одного тона"
        )

    def test_skeleton_forces_two_families_and_closed_type_scale(self):
        """#128: принцип без значений не исполняется — исполняется только закрытый набор.

        Замер по 5 артефактам: шрифтовой пары 0 из 5 (все пять — один системный гротеск
        начертания 400), различных кеглей 11–22 на файл при трёх заявленных ступенях.
        """
        text = self.SKILL.read_text(encoding="utf-8")
        assert "--font-head" in text, "заголовочная семья обязана быть отдельной ручкой"
        for weight in ("430", "500", "600"):
            assert weight in text, f"начертание {weight} пропало — вернулся один вес на всё"
        for step in ("--fs-sm", "--fs-h3", "--fs-h2", "--fs-h1"):
            # объявление И использование: одного упоминания мало, ступень без значения
            # не ступень, а ступень без применения не удержит набор закрытым
            assert f"{step}:" in text, f"ступень {step} не объявлена"
            assert f"var({step})" in text, f"ступень {step} объявлена, но нигде не применена"

    def test_palette_is_derived_from_subject(self):
        text = self.SKILL.read_text(encoding="utf-8").lower()
        assert "выводится из предмета" in text
        assert "color-mix" in text, "должен остаться приём вывода цвета из базовых токенов"

    def test_budget(self):
        """description платится в КАЖДОЙ сессии (индекс скиллов), тело — только при срабатывании."""
        import re

        text = self.SKILL.read_text(encoding="utf-8")
        description = re.search(r"^description:\s*(.*)$", text, re.M).group(1)
        assert len(description) <= 250, f"description {len(description)} симв."
        # Потолок поднят в #128 вместе с костяком: тело выросло 6 598 → 11 796 Б.
        # Платится оно не в каждой сессии — `build_skills_index` кладёт в промпт только
        # строку «имя — описание — путь», тело агент читает при срабатывании скилла.
        assert len(text.split("---", 2)[2].encode()) <= 12500, "тело скилла раздулось"


class TestRefreshWorkerMemory:
    """#137: personal memory must be re-read from disk when the prompt is re-injected.

    Measured before the fix: 11 of 13 live sessions carried a stale <worker-memory>
    block; the worst was running without 61% of its own accumulated file.
    """

    PROMPT = "ROLE: worker.\n\n<worker-memory>\nOLD\n</worker-memory>"

    def _mem(self, tmp_path, filename, text):
        d = tmp_path / "docs" / "workers"
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(text)

    def test_replaces_block_and_keeps_the_blank_line_separator(self, tmp_path):
        from app.prompting import refresh_worker_memory

        self._mem(tmp_path, "w1.md", "FRESH")
        out = refresh_worker_memory(self.PROMPT, "w1", "worker", str(tmp_path))
        assert out == "ROLE: worker.\n\n<worker-memory>\nFRESH\n</worker-memory>", (
            "the block must be swapped in place, still separated from the role text"
        )
        assert refresh_worker_memory(out, "w1", "worker", str(tmp_path)) == out, (
            "re-injection happens on every resume — it must be idempotent"
        )

    def test_missing_unreadable_or_bad_scope_empties_the_block_without_raising(
        self, tmp_path
    ):
        from app.prompting import refresh_worker_memory

        # A raise here would land on the turn boundary, killing the agent's turn.
        assert refresh_worker_memory(
            self.PROMPT, "w1", "worker", str(tmp_path)
        ) == "ROLE: worker."
        assert refresh_worker_memory(
            self.PROMPT, "w1", "worker", "/nope/nowhere"
        ) == "ROLE: worker."

        self._mem(tmp_path, "w1.md", "SECRET")
        (tmp_path / "docs" / "workers" / "w1.md").chmod(0o000)
        try:
            assert refresh_worker_memory(
                self.PROMPT, "w1", "worker", str(tmp_path)
            ) == "ROLE: worker."
        finally:
            (tmp_path / "docs" / "workers" / "w1.md").chmod(0o644)

    def test_memory_containing_regex_escapes_is_inserted_literally(self, tmp_path):
        from app.prompting import refresh_worker_memory

        self._mem(tmp_path, "w1.md", r"backref \1 and \g<0>")
        out = refresh_worker_memory(self.PROMPT, "w1", "worker", str(tmp_path))
        assert r"backref \1 and \g<0>" in out, (
            "memory is arbitrary text; a string replacement would expand \\1 as a group"
        )

    def test_falls_back_to_role_file(self, tmp_path):
        from app.prompting import refresh_worker_memory

        self._mem(tmp_path, "worker.md", "ROLE-LEVEL")
        out = refresh_worker_memory(self.PROMPT, "w1", "worker", str(tmp_path))
        assert "ROLE-LEVEL" in out
