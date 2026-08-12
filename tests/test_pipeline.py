"""Тесты loader'а пайплайнов (app/pipeline.py).

Изолированный модуль: фикстуры строят временные pipelines/<name>/pipeline.yaml
на tmp_path и патчат app.pipeline.PIPELINES_DIR. На реальные pipelines/ НЕ опираемся.
"""
from __future__ import annotations

import textwrap

import pytest

import app.pipeline as P


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest.fixture
def pipelines_root(tmp_path, monkeypatch):
    """Подменяет корень пайплайнов на tmp + чистит lru_cache load_pipeline.

    Возвращает Path к временной директории pipelines/.
    """
    root = tmp_path / "pipelines"
    root.mkdir()
    monkeypatch.setattr(P, "PIPELINES_DIR", root)
    P.load_pipeline.cache_clear()
    yield root
    P.load_pipeline.cache_clear()


def _write_pipeline(root, name: str, yaml_text: str, prompts: dict | None = None):
    """Создаёт pipelines/<name>/pipeline.yaml (+ опц. prompts/<rel>=content)."""
    d = root / name
    (d / "prompts").mkdir(parents=True, exist_ok=True)
    (d / "pipeline.yaml").write_text(textwrap.dedent(yaml_text))
    for rel, content in (prompts or {}).items():
        f = d / "prompts" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return d


# Минимальный валидный манифест с двумя ролями (оркестратор + воркер).
_MINIMAL = """\
    name: {name}
    description: Test pipeline
    validation: fail-closed
    defaults:
      model: opus
      skills: all
      mcp_servers: all
    roles:
      lead:
        kind: orchestrator
        label: Lead
        order: 0
        can_spawn: [hand]
        allow_unrouted_workers: true
      hand:
        kind: worker
        label: Hand
        can_spawn: []
"""


# ── load_pipeline ────────────────────────────────────────────────────────

class TestLoadPipeline:
    def test_loads_valid_manifest(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
        cfg = P.load_pipeline("demo")
        assert cfg.name == "demo"
        assert cfg.description == "Test pipeline"
        assert cfg.validation == "fail-closed"
        assert set(cfg.roles) == {"lead", "hand"}
        assert cfg.roles["lead"].kind == "orchestrator"
        assert cfg.roles["hand"].kind == "worker"

    def test_missing_file_raises_filenotfound(self, pipelines_root):
        with pytest.raises(FileNotFoundError):
            P.load_pipeline("nope")

    def test_name_mismatch_raises(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="other"))
        with pytest.raises(ValueError, match="name"):
            P.load_pipeline("demo")

    def test_is_cached_while_file_unchanged(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
        first = P.load_pipeline("demo")
        assert P.load_pipeline("demo") is first  # нетронутый файл не перечитывается

    def test_cache_invalidated_when_file_changes(self, pipelines_root):
        """#214: правка манифеста при живом сервере видна БЕЗ рестарта.

        Контракт сменился намеренно: раньше кеш держал первый разбор до
        ``cache_clear()``, теперь ключ включает mtime+размер файла. Это цена за то,
        чтобы «всем Opus поставить high» делалось одной правкой yaml, а живые агенты
        подхватывали её на своём следующем ходе (`AgentSession._apply_manifest_effort`).
        """
        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
        first = P.load_pipeline("demo")
        assert first.roles["hand"].effort is None

        (d / "pipeline.yaml").write_text(
            _MINIMAL.format(name="demo").replace(
                "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1))
        second = P.load_pipeline("demo")
        assert second is not first
        assert second.roles["hand"].effort == "high"

    def test_file_changed_during_read_is_not_cached(self, pipelines_root, monkeypatch):
        """Неатомарная запись извне: содержимое не должно попасть в кеш и наружу.

        Опасен не битый YAML (его отвергнет схема), а НЕДОПИСАННЫЙ, но синтаксически
        валидный: роль получила бы неполную карту эффорта, и та уехала бы живым агентам.
        """
        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
        target = d / "pipeline.yaml"
        full = _MINIMAL.format(name="demo").replace(
            "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1)
        real_read = P.Path.read_text
        torn = {"n": 0}

        def read_then_grow(self, *a, **kw):
            text = real_read(self, *a, **kw)
            if self == target and torn["n"] == 0:
                torn["n"] += 1
                target.write_text(full)  # «дописали» файл ровно между read и stat
            return text

        monkeypatch.setattr(P.Path, "read_text", read_then_grow)
        cfg = P.load_pipeline("demo")

        assert torn["n"] == 1                       # торн-рид действительно случился
        assert cfg.roles["hand"].effort == "high"   # отдана дописанная версия, не обрывок
        assert P.load_pipeline("demo") is cfg       # в кеше лежит она же

    def test_broken_manifest_after_edit_fails_loud(self, pipelines_root):
        """Обратная сторона инвалидации: битый файл больше не прячется за кешем."""
        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
        P.load_pipeline("demo")
        (d / "pipeline.yaml").write_text("garbage: [")
        with pytest.raises(Exception):
            P.load_pipeline("demo")


# ── Валидация схемы (extra=forbid, kind, model, can_spawn-граф) ─────────────

class TestSchemaValidation:
    def test_extra_field_top_level_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: worker, label: R}
            bogus_field: 1
        """)
        with pytest.raises(Exception):  # pydantic.ValidationError (extra=forbid)
            P.load_pipeline("demo")

    def test_extra_field_in_role_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: worker, label: R, mystery: yes}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_invalid_kind_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: wizard, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_invalid_validation_mode_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            validation: maybe
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_invalid_model_in_defaults_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults: {model: gpt-9000}
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception, match="model"):
            P.load_pipeline("demo")

    def test_invalid_model_in_role_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: worker, label: R, model: turbo-9}
        """)
        with pytest.raises(Exception, match="model"):
            P.load_pipeline("demo")

    def test_full_model_id_accepted(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults: {model: claude-opus-5}
            roles:
              r: {kind: worker, label: R, model: "claude-sonnet-5[1m]"}
        """)
        cfg = P.load_pipeline("demo")
        assert cfg.defaults.model == "claude-opus-5"
        assert cfg.roles["r"].model == "claude-sonnet-5[1m]"

    def test_can_spawn_unknown_role_rejected(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              a: {kind: orchestrator, label: A, can_spawn: [ghost]}
              b: {kind: worker, label: B}
        """)
        with pytest.raises(Exception, match="ghost"):
            P.load_pipeline("demo")

    def test_can_spawn_wildcard_allowed(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              a: {kind: orchestrator, label: A, can_spawn: ["*"]}
              b: {kind: worker, label: B}
        """)
        cfg = P.load_pipeline("demo")
        assert cfg.roles["a"].can_spawn == ["*"]

    # ── B2: hardening путей манифеста (fail-closed на abs/'..') ──────────────

    def test_is_safe_rel_unit(self):
        """Юнит хелпера: относительные ОК, abs и '..' — нет, {role}/{feature} ОК."""
        assert P._is_safe_rel("roles/{role}.md")
        assert P._is_safe_rel("{feature}/_pm")
        assert P._is_safe_rel("base.md")
        assert not P._is_safe_rel("/etc/passwd")
        assert not P._is_safe_rel("../../../app/db.py")
        assert not P._is_safe_rel("a/../b")
        assert not P._is_safe_rel("")

    def test_prompt_layers_traversal_rejected(self, pipelines_root):
        """B2: prompt_layers с '..' → ValidationError на загрузке (fail-closed)."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              prompt_layers:
                orchestrator: ["../../../app/db.py"]
                worker: ["base.md"]
            roles:
              r: {kind: orchestrator, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_prompt_layers_absolute_rejected(self, pipelines_root):
        """B2: абсолютный путь в prompt_layers → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              prompt_layers:
                orchestrator: ["base.md"]
                worker: ["/etc/shadow"]
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    @pytest.mark.parametrize("skill", ["../secret", "/etc/passwd", "nested/name"])
    def test_unsafe_default_skill_name_rejected(self, pipelines_root, skill):
        _write_pipeline(pipelines_root, "demo", f"""\
            name: demo
            defaults:
              skills: ["{skill}"]
            roles:
              r: {{kind: worker, label: R}}
        """)
        with pytest.raises(Exception, match="unsafe skill"):
            P.load_pipeline("demo")

    @pytest.mark.parametrize("skill", ["../secret", "/etc/passwd", "nested/name"])
    def test_unsafe_role_skill_name_rejected(self, pipelines_root, skill):
        _write_pipeline(pipelines_root, "demo", f"""\
            name: demo
            roles:
              r:
                kind: worker
                label: R
                skills: ["{skill}"]
        """)
        with pytest.raises(Exception, match="unsafe skill"):
            P.load_pipeline("demo")

    def test_unsafe_pipeline_lookup_name_rejected(self, pipelines_root):
        with pytest.raises(ValueError, match="unsafe pipeline"):
            P.load_pipeline("../outside")

    def test_docs_dir_absolute_path_rejected(self, pipelines_root):
        """B2: docs_dir.path абсолютный → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: orchestrator, label: R, docs_dir: {path: "/etc/x"}}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_docs_dir_traversal_template_rejected(self, pipelines_root):
        """B2: docs_dir.template с '..' → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            roles:
              r: {kind: orchestrator, label: R, docs_dir: {path: _x, template: "../t.md"}}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_safe_manifest_paths_accepted(self, pipelines_root):
        """B2: валидные относительные пути (+ {role}/{feature}) грузятся без ошибок."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              prompt_layers:
                orchestrator: ["base.md", "roles/{role}.md", "_pipeline.md"]
                worker: ["base.md", "roles/{role}.md"]
            roles:
              r: {kind: orchestrator, label: R, docs_dir: {path: "{feature}/_pm", template: pm.md, requires: feature}}
        """)
        cfg = P.load_pipeline("demo")
        assert cfg.roles["r"].docs_dir.path == "{feature}/_pm"

    def test_skills_all_and_list_both_valid(self, pipelines_root):
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults: {skills: all, mcp_servers: [github, slack]}
            roles:
              r: {kind: worker, label: R, skills: [html], mcp_servers: all}
        """)
        cfg = P.load_pipeline("demo")
        assert cfg.defaults.skills == "all"
        assert cfg.defaults.mcp_servers == ["github", "slack"]
        assert cfg.roles["r"].skills == ["html"]
        assert cfg.roles["r"].mcp_servers == "all"

    # ── B2: hardening путей Symlink (fail-closed на abs/'..') ────────────────

    def test_symlink_source_traversal_rejected(self, pipelines_root):
        """Symlink.source с '..' → отвергнут на загрузке (fail-closed)."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                symlinks: [{source: "../../etc", target: docs_work}]
            roles:
              r: {kind: orchestrator, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_symlink_source_absolute_rejected(self, pipelines_root):
        """Symlink.source абсолютный → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                symlinks: [{source: "/etc/passwd", target: docs_work}]
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_symlink_target_traversal_rejected(self, pipelines_root):
        """Symlink.target с '..' (вырывается из worktree) → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                symlinks: [{source: docs_work, target: "../../escape"}]
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_symlink_safe_paths_accepted(self, pipelines_root):
        """Безопасный Symlink(source=docs_work, target=docs_work) грузится без ошибок."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                symlinks: [{source: docs_work, target: docs_work}]
                copies: [CLAUDE.md]
            roles:
              r: {kind: orchestrator, label: R}
        """)
        cfg = P.load_pipeline("demo")
        assert cfg.defaults.worktree.symlinks[0].source == "docs_work"
        assert cfg.defaults.worktree.symlinks[0].target == "docs_work"

    def test_copies_traversal_rejected(self, pipelines_root):
        """copies с '..' → отвергнут на загрузке (симметрично symlinks)."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                copies: ["../../escape"]
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")

    def test_copies_absolute_rejected(self, pipelines_root):
        """copies с абсолютным путём → отвергнут."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                copies: ["/etc/passwd"]
            roles:
              r: {kind: worker, label: R}
        """)
        with pytest.raises(Exception):
            P.load_pipeline("demo")


# ── get_worktree_config ─────────────────────────────────────────────────────

class TestGetWorktreeConfig:
    def test_returns_worktree_with_copies(self, pipelines_root):
        """get_worktree_config возвращает defaults.worktree с нужными copies/symlinks."""
        _write_pipeline(pipelines_root, "demo", """\
            name: demo
            defaults:
              worktree:
                symlinks: [{source: docs_work, target: docs_work}]
                copies: [CLAUDE.md, .env]
            roles:
              r: {kind: orchestrator, label: R}
        """)
        wt = P.get_worktree_config("demo")
        assert isinstance(wt, P.Worktree)
        assert wt.copies == ["CLAUDE.md", ".env"]
        assert wt.symlinks[0].source == "docs_work"

    def test_missing_pipeline_raises_filenotfound(self, pipelines_root):
        """Нет манифеста → FileNotFoundError пробрасывается (не глотается)."""
        with pytest.raises(FileNotFoundError):
            P.get_worktree_config("nonexistent")


# ── resolve_role: наследование defaults→roles ──────────────────────────────

# Манифест с defaults и ролями, переопределяющими разные поля.
_INHERIT = """\
    name: inh
    validation: fail-closed
    defaults:
      model: opus
      skills: all
      mcp_servers: [github, slack]
      inherit_claude_md: true
      base_branch_strategy: parent
      docs_scaffold: true
      prompt_layers:
        orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
        worker: [base.md, "roles/{role}.md"]
    roles:
      lead:
        kind: orchestrator
        label: Lead
        order: 0
        base_branch_strategy: main
        can_spawn: [coder, secretary]
        mcp_servers: [jira]
      coder:
        kind: orchestrator
        label: Coder
        order: 4
        model: sonnet
        skills: [html]
        can_spawn: [secretary]
        docs_dir: {path: "{feature}/_impl", template: impl.md, requires: feature}
        tg: {emoji: "🛠", topic: "{feature} · код"}
      secretary:
        kind: worker
        label: Secretary
        can_spawn: []
"""


class TestResolveRole:
    def _cfg(self, root):
        _write_pipeline(root, "inh", _INHERIT)
        return P.load_pipeline("inh")

    def test_scalar_inherited_when_role_omits(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        rr = P.resolve_role(cfg, "secretary")
        # secretary НЕ задал model → наследует defaults.model=opus (НЕ sonnet)
        assert rr.model == "opus"
        assert rr.inherit_claude_md is True
        assert rr.docs_scaffold is True
        assert rr.base_branch_strategy == "parent"

    def test_scalar_overridden_by_role(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        rr = P.resolve_role(cfg, "coder")
        assert rr.model == "sonnet"  # роль переопределила
        rr_lead = P.resolve_role(cfg, "lead")
        assert rr_lead.base_branch_strategy == "main"  # роль переопределила parent→main

    def test_list_union(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        # lead.mcp_servers=[jira] ∪ defaults=[github,slack] → отсортированный union
        rr = P.resolve_role(cfg, "lead")
        assert rr.mcp_servers == ["github", "jira", "slack"]

    def test_list_all_absorbs(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        # defaults.skills='all'; coder.skills=[html] → 'all' поглощает
        rr = P.resolve_role(cfg, "coder")
        assert rr.skills == "all"

    def test_list_inherited_when_role_omits(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        # secretary не задал skills/mcp → наследует defaults как есть
        rr = P.resolve_role(cfg, "secretary")
        assert rr.skills == "all"
        assert rr.mcp_servers == ["github", "slack"]

    def test_prompt_layers_orchestrator_with_role_substituted(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        rr = P.resolve_role(cfg, "coder")  # orchestrator → 3 слоя, {role}→coder
        assert rr.prompt_layers == ["base.md", "roles/coder.md", "_pipeline.md"]

    def test_prompt_layers_worker_no_pipeline_layer(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        rr = P.resolve_role(cfg, "secretary")  # worker → 2 слоя
        assert rr.prompt_layers == ["base.md", "roles/secretary.md"]

    def test_role_specific_fields_passthrough(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        rr = P.resolve_role(cfg, "coder")
        assert rr.docs_dir is not None
        assert rr.docs_dir.path == "{feature}/_impl"
        assert rr.docs_dir.requires == "feature"
        assert rr.tg is not None and rr.tg.emoji == "🛠"
        assert rr.name == "coder" and rr.pipeline == "inh"

    def test_is_orchestrator_property(self, pipelines_root):
        cfg = self._cfg(pipelines_root)
        assert P.resolve_role(cfg, "coder").is_orchestrator is True
        assert P.resolve_role(cfg, "secretary").is_orchestrator is False

    def test_all_union_all_stays_all(self, pipelines_root):
        # оба 'all' → 'all'
        _write_pipeline(pipelines_root, "aa", """\
            name: aa
            defaults: {skills: all}
            roles:
              r: {kind: worker, label: R, skills: all}
        """)
        cfg = P.load_pipeline("aa")
        assert P.resolve_role(cfg, "r").skills == "all"


# ── effort: скаляр или карта модель→ступень (#214) ─────────────────────────

class TestEffortByModel:
    def _role(self, root, effort_yaml: str):
        _write_pipeline(root, "eff", f"""\
            name: eff
            roles:
              hand: {{kind: worker, label: Hand, effort: {effort_yaml}}}
        """)
        return P.resolve_role(P.load_pipeline("eff"), "hand").effort

    def test_scalar_applies_to_every_model(self, pipelines_root):
        eff = self._role(pipelines_root, "medium")
        assert eff == "medium"
        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "medium"
        assert P.resolve_effort(eff, "gpt-5.6-sol", "codex") == "medium"

    def test_map_resolves_by_exact_model_id(self, pipelines_root):
        eff = self._role(
            pipelines_root,
            '{"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: low}')
        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "high"
        assert P.resolve_effort(eff, "gpt-5.6-sol", "codex") == "xhigh"
        # Sol и Luna — один рантайм codex, но ступени разные: ключ именно модель
        assert P.resolve_effort(eff, "gpt-5.6-luna", "codex") == "low"

    def test_unknown_model_falls_back_to_default(self, pipelines_root):
        eff = self._role(pipelines_root, "{gpt-5.6-sol: xhigh, default: medium}")
        assert P.resolve_effort(eff, "claude-haiku-4-5", "claude") == "medium"

    def test_no_default_and_no_match_gives_none(self, pipelines_root):
        eff = self._role(pipelines_root, "{gpt-5.6-sol: xhigh}")
        assert P.resolve_effort(eff, "claude-haiku-4-5", "claude") is None

    def test_runtime_key_covers_whole_runtime(self, pipelines_root):
        eff = self._role(pipelines_root, "{codex: max, default: low}")
        assert P.resolve_effort(eff, "gpt-5.6-luna", "codex") == "max"
        assert P.resolve_effort(eff, "gpt-5.4-mini", "codex") == "max"
        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "low"

    def test_exact_model_beats_runtime_and_default(self, pipelines_root):
        eff = self._role(pipelines_root, "{gpt-5.6-sol: xhigh, codex: low, default: medium}")
        assert P.resolve_effort(eff, "gpt-5.6-sol", "codex") == "xhigh"
        assert P.resolve_effort(eff, "gpt-5.6-luna", "codex") == "low"

    def test_alias_key_normalized_to_model_id(self, pipelines_root):
        eff = self._role(pipelines_root, "{opus: low}")
        assert eff == {"claude-opus-5[1m]": "low"}
        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "low"

    def test_unknown_key_kept_but_never_matches(self, pipelines_root, caplog):
        """Незнакомый ключ переживает валидацию, но ни с чем не совпадает.

        Выбрасывать нельзя: реестр моделей досоздаётся на старте
        (`models.fetch_models_from_proxy`), и манифест мог быть разобран раньше —
        выброс терял бы валидную строку навсегда из-за порядка инициализации.
        """
        with caplog.at_level("WARNING"):
            eff = self._role(pipelines_root, "{gpt-9-nope: high, default: medium}")
        assert eff == {"gpt-9-nope": "high", "default": "medium"}
        assert "gpt-9-nope" in caplog.text
        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "medium"

    def test_key_matches_once_model_appears_in_registry(self, pipelines_root, monkeypatch):
        """Тот же ключ начинает работать, как только модель появилась в реестре."""
        from app.models import MODELS
        eff = self._role(pipelines_root, "{gpt-9-nope: high, default: medium}")
        monkeypatch.setitem(MODELS, "gpt-9-nope", "GPT-9 Nope")
        assert P.resolve_effort(eff, "gpt-9-nope", "codex") == "high"

    def test_grok_key_is_a_runtime_key_not_a_model(self, pipelines_root):
        """`grok` — и id рантайма, и alias модели `grok-4.5`; рантайм выигрывает.

        Следствие, которое надо знать при правке манифеста: выбрать ключом `grok`
        конкретную модель нельзя — для этого есть полный id `grok-4.5`.
        """
        eff = self._role(pipelines_root, "{grok: high, grok-4.5: low, default: medium}")
        assert eff == {"grok": "high", "grok-4.5": "low", "default": "medium"}
        # точный id модели сильнее рантайма
        assert P.resolve_effort(eff, "grok-4.5", "grok") == "low"
        eff2 = self._role(pipelines_root, "{grok: high, default: medium}")
        assert P.resolve_effort(eff2, "grok-4.5", "grok") == "high"

    def test_unknown_level_rejects_the_manifest(self, pipelines_root):
        """Опечатка в СТУПЕНИ роняет манифест, а не «пропускается».

        Пропуск не сохранял бы статус-кво: `{gpt-5.6-sol: hgih, default: high}` тихо
        перевёл бы Sol с `xhigh` на `high` — то есть сменил маршрут, а не оставил как
        было. Список ступеней замкнут и известен при загрузке, гонки с досозданием
        реестра здесь нет (в отличие от ключей-моделей), поэтому опечатка однозначна.
        """
        with pytest.raises(Exception) as e:
            self._role(pipelines_root, "{gpt-5.6-sol: hgih, default: medium}")
        assert "hgih" in str(e.value)

    def test_unknown_level_rejects_even_when_default_would_cover_it(self, pipelines_root):
        """Именно этот случай и опасен: `default` рядом маскирует опечатку молчанием."""
        with pytest.raises(Exception):
            self._role(pipelines_root, "{gpt-5.6-sol: xhihg, default: high}")

    def test_absent_effort_stays_none(self, pipelines_root):
        _write_pipeline(pipelines_root, "noeff", """\
            name: noeff
            roles:
              hand: {kind: worker, label: Hand}
        """)
        rr = P.resolve_role(P.load_pipeline("noeff"), "hand")
        assert rr.effort is None
        assert P.resolve_effort(rr.effort, "claude-opus-5[1m]", "claude") is None


# ── build_system_prompt: композиция слоёв + ИЗОЛЯЦИЯ ───────────────────────

class TestBuildSystemPrompt:
    def test_orchestrator_concatenates_three_layers(self, pipelines_root):
        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
            "base.md": "BASE",
            "roles/lead.md": "LEAD-ROLE",
            "_pipeline.md": "PIPE",
        })
        out = P.build_system_prompt("p", "lead")
        assert out == "BASE\n\nLEAD-ROLE\n\nPIPE"

    def test_worker_two_layers_no_pipeline(self, pipelines_root):
        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
            "base.md": "BASE",
            "roles/hand.md": "HAND-ROLE",
            "_pipeline.md": "SHOULD-NOT-APPEAR",  # воркер не берёт _pipeline.md
        })
        out = P.build_system_prompt("p", "hand")
        assert out == "BASE\n\nHAND-ROLE"
        assert "SHOULD-NOT-APPEAR" not in out

    def test_missing_layer_skipped(self, pipelines_root):
        # есть base.md, нет roles/lead.md и _pipeline.md → только base
        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
            "base.md": "ONLY-BASE",
        })
        out = P.build_system_prompt("p", "lead")
        assert out == "ONLY-BASE"

    def test_all_layers_missing_returns_empty(self, pipelines_root):
        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"))  # без prompts
        assert P.build_system_prompt("p", "lead") == ""

    def test_isolation_does_not_read_app_prompts(self, pipelines_root, monkeypatch, tmp_path):
        """ИЗОЛЯЦИЯ: даже если app/prompts/ переименован/недоступен — сборка работает,
        и наоборот: слой из app/prompts/ в итог НЕ попадает (читаем только pipelines/)."""
        # 1) Делаем app/prompts/ недоступным через подмену _PROMPTS_DIR в manager —
        #    но build_system_prompt вообще не должен туда смотреть.
        #    Проверяем структурно: prompt_path всегда внутри PIPELINES_DIR.
        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
            "base.md": "ISO-BASE",
            "roles/lead.md": "ISO-LEAD",
            "_pipeline.md": "ISO-PIPE",
        })
        # Кладём "ловушку" в гипотетический app/prompts/base.md — её НЕ должно быть в выводе
        trap = tmp_path / "app_prompts"
        trap.mkdir()
        (trap / "base.md").write_text("TRAP-FROM-APP-PROMPTS")
        out = P.build_system_prompt("p", "lead")
        assert out == "ISO-BASE\n\nISO-LEAD\n\nISO-PIPE"
        assert "TRAP" not in out

    def test_prompt_path_always_inside_pipelines_dir(self, pipelines_root):
        p = P.prompt_path("p", "roles/lead.md")
        assert str(p).startswith(str(pipelines_root))
        assert p == pipelines_root / "p" / "prompts" / "roles" / "lead.md"

    def test_template_path_inside_pipelines_dir(self, pipelines_root):
        t = P.template_path("p", "impl.md")
        assert t == pipelines_root / "p" / "templates" / "impl.md"

    def test_build_raises_filenotfound_for_missing_pipeline(self, pipelines_root):
        # манифеста нет → FileNotFoundError (на Этапе 3 manager ловит и идёт в fallback)
        with pytest.raises(FileNotFoundError):
            P.build_system_prompt("ghost", "lead")


# ── list_pipelines: скан + устойчивость к битым манифестам ─────────────────

class TestListPipelines:
    def test_lists_valid_pipelines(self, pipelines_root):
        _write_pipeline(pipelines_root, "alpha", _MINIMAL.format(name="alpha"))
        _write_pipeline(pipelines_root, "beta", _MINIMAL.format(name="beta"))
        out = P.list_pipelines()
        names = {p["name"] for p in out}
        assert names == {"alpha", "beta"}
        assert all(p["valid"] for p in out)
        alpha = next(p for p in out if p["name"] == "alpha")
        assert alpha["description"] == "Test pipeline"

    def test_empty_root_returns_empty_list(self, pipelines_root):
        assert P.list_pipelines() == []

    def test_missing_root_returns_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(P, "PIPELINES_DIR", tmp_path / "no_such_dir")
        P.load_pipeline.cache_clear()
        assert P.list_pipelines() == []

    def test_broken_manifest_marked_invalid_not_raised(self, pipelines_root):
        _write_pipeline(pipelines_root, "good", _MINIMAL.format(name="good"))
        # битый: неверный kind → ValidationError на load, но list НЕ падает
        _write_pipeline(pipelines_root, "bad", """\
            name: bad
            roles:
              r: {kind: dragon, label: R}
        """)
        out = P.list_pipelines()
        by_name = {p["name"]: p for p in out}
        assert by_name["good"]["valid"] is True
        assert by_name["bad"]["valid"] is False

    def test_dir_without_yaml_skipped(self, pipelines_root):
        (pipelines_root / "not_a_pipeline").mkdir()  # папка без pipeline.yaml
        _write_pipeline(pipelines_root, "real", _MINIMAL.format(name="real"))
        out = P.list_pipelines()
        assert {p["name"] for p in out} == {"real"}


# ── validate_spawn: fail-closed/open, whitelist, unrouted, корень ──────────

# fail-closed манифест: lead→[coder, secretary]; coder→[]; secretary→[]
_SPAWN_CLOSED = """\
    name: closed
    validation: fail-closed
    roles:
      lead: {kind: orchestrator, label: Lead, can_spawn: [coder, secretary], allow_unrouted_workers: false}
      coder: {kind: orchestrator, label: Coder, can_spawn: [secretary], allow_unrouted_workers: true}
      secretary: {kind: worker, label: Secretary, can_spawn: []}
"""

_SPAWN_OPEN = """\
    name: opened
    validation: fail-open
    roles:
      lead: {kind: orchestrator, label: Lead, can_spawn: [coder], allow_unrouted_workers: false}
      coder: {kind: orchestrator, label: Coder, can_spawn: [], allow_unrouted_workers: false}
"""


class TestValidateSpawn:
    def _closed(self, root):
        _write_pipeline(root, "closed", _SPAWN_CLOSED)

    def _open(self, root):
        _write_pipeline(root, "opened", _SPAWN_OPEN)

    def test_allowed_child_passes(self, pipelines_root):
        self._closed(pipelines_root)
        assert P.validate_spawn("closed", "lead", "coder") is None  # в whitelist

    def test_forbidden_child_raises_fail_closed(self, pipelines_root):
        self._closed(pipelines_root)
        # coder.can_spawn=[secretary]; coder→coder запрещён
        with pytest.raises(ValueError, match="cannot spawn"):
            P.validate_spawn("closed", "coder", "coder")

    def test_terminal_role_cannot_spawn(self, pipelines_root):
        self._closed(pipelines_root)
        with pytest.raises(ValueError):
            P.validate_spawn("closed", "secretary", "coder")

    def test_root_empty_parent_allowed(self, pipelines_root):
        self._closed(pipelines_root)
        # корневой спавн (нет родителя) — от юзера/UI, пропускаем
        assert P.validate_spawn("closed", "", "lead") is None
        assert P.validate_spawn("closed", None, "lead") is None

    def test_unrouted_worker_blocked_when_not_allowed(self, pipelines_root):
        self._closed(pipelines_root)
        # lead.allow_unrouted_workers=false; пустой child → ошибка
        with pytest.raises(ValueError, match="child role"):
            P.validate_spawn("closed", "lead", "")

    def test_unrouted_worker_allowed_when_flag_set(self, pipelines_root):
        self._closed(pipelines_root)
        # coder.allow_unrouted_workers=true; пустой child → OK
        assert P.validate_spawn("closed", "coder", "") is None

    def test_unknown_child_fail_closed_raises(self, pipelines_root):
        self._closed(pipelines_root)
        with pytest.raises(ValueError, match="unknown role"):
            P.validate_spawn("closed", "lead", "ghost")

    def test_unknown_parent_fail_closed_raises(self, pipelines_root):
        self._closed(pipelines_root)
        with pytest.raises(ValueError, match="unknown parent"):
            P.validate_spawn("closed", "phantom", "coder")

    # fail-open: нестрого
    def test_fail_open_forbidden_child_still_raises(self, pipelines_root):
        # ВАЖНО: fail-open смягчает ТОЛЬКО неизвестные роли; явный whitelist при
        # известных ролях всё равно действует (coder.can_spawn=[] → terminal)
        self._open(pipelines_root)
        with pytest.raises(ValueError, match="cannot spawn"):
            P.validate_spawn("opened", "coder", "lead")

    def test_fail_open_unknown_parent_passes(self, pipelines_root):
        self._open(pipelines_root)
        assert P.validate_spawn("opened", "phantom", "coder") is None

    def test_fail_open_unknown_child_passes(self, pipelines_root):
        self._open(pipelines_root)
        assert P.validate_spawn("opened", "lead", "mystery") is None

    def test_wildcard_can_spawn_allows_any(self, pipelines_root):
        _write_pipeline(pipelines_root, "wild", """\
            name: wild
            validation: fail-closed
            roles:
              boss: {kind: orchestrator, label: Boss, can_spawn: ["*"]}
              w: {kind: worker, label: W}
        """)
        assert P.validate_spawn("wild", "boss", "w") is None


# ── get_active_pipeline: наследование от родителя / дефолт ─────────────────

class TestGetActivePipeline:
    def test_inherits_parent_pipeline(self):
        assert P.get_active_pipeline(parent_pipeline="tasks-pm") == "tasks-pm"

    def test_default_when_no_parent(self):
        assert P.get_active_pipeline() == P.DEFAULT_PIPELINE
        assert P.get_active_pipeline(scope="/some/proj") == P.DEFAULT_PIPELINE

    def test_parent_wins_over_scope(self):
        assert P.get_active_pipeline(scope="/x", parent_pipeline="custom") == "custom"


# ── Канонический tasks-pm: эталонный манифест из спеки грузится и резолвится ─

# Дословно из DESIGN.md §15 (поля-эталон). Проверяет, что схема поддерживает ВСЁ.
_TASKS_PM = """\
    name: tasks-pm
    description: Многоуровневый PM-пайплайн
    validation: fail-closed
    defaults:
      model: opus
      skills: all
      mcp_servers: all
      inherit_claude_md: true
      prompt_layers:
        orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
        worker:       [base.md, "roles/{role}.md"]
      worktree:
        symlinks: [{source: docs_work, target: docs_work}]
        copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
      base_branch_strategy: parent
      docs_scaffold: true
    roles:
      base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
      pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
      pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [analyst, coder, tester, secretary], allow_unrouted_workers: false, docs_dir: {path: "{feature}/_pm", template: pm.md, requires: feature}, tg: {emoji: "📋", topic: "{feature}"}}
      analyst: {kind: orchestrator, label: Аналитик, order: 3, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_analysis", template: analysis.md, requires: feature}, tg: {emoji: "🔬", topic: "{feature} · анализ"}}
      coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_impl", template: impl.md, requires: feature}, tg: {emoji: "🛠", topic: "{feature} · код"}}
      tester: {kind: orchestrator, label: Тестировщик, order: 5, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_testing", template: testing.md, requires: feature}, tg: {emoji: "🧪", topic: "{feature} · тест"}}
      secretary: {kind: worker, label: Секретарь, can_spawn: [], allow_unrouted_workers: false}
      worker: {kind: worker, label: Воркер, can_spawn: [], allow_unrouted_workers: false}
"""


class TestCanonicalTasksPm:
    def test_loads_clean(self, pipelines_root):
        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
        cfg = P.load_pipeline("tasks-pm")
        assert cfg.name == "tasks-pm"
        assert len(cfg.roles) == 8
        assert cfg.validation == "fail-closed"
        assert cfg.defaults.worktree.symlinks[0].source == "docs_work"

    def test_secretary_inherits_opus_not_sonnet(self, pipelines_root):
        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
        cfg = P.load_pipeline("tasks-pm")
        rr = P.resolve_role(cfg, "secretary")
        assert rr.model == "opus"  # ключевое решение DESIGN §2.1
        assert rr.skills == "all"
        assert rr.mcp_servers == "all"

    def test_pm_glava_branch_strategy_main(self, pipelines_root):
        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
        cfg = P.load_pipeline("tasks-pm")
        assert P.resolve_role(cfg, "pm-glava").base_branch_strategy == "main"
        assert P.resolve_role(cfg, "coder").base_branch_strategy == "parent"  # из defaults

    def test_orchestrators_get_pipeline_layer(self, pipelines_root):
        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
        cfg = P.load_pipeline("tasks-pm")
        # 6 оркестраторов → _pipeline.md; secretary/worker (kind:worker) → нет
        assert "_pipeline.md" in P.resolve_role(cfg, "pm-fichi").prompt_layers
        assert "_pipeline.md" not in P.resolve_role(cfg, "secretary").prompt_layers

    def test_spawn_graph_enforced(self, pipelines_root):
        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
        # pm-glava → pm-fichi OK; pm-glava → coder запрещён (не в can_spawn)
        assert P.validate_spawn("tasks-pm", "pm-glava", "pm-fichi") is None
        with pytest.raises(ValueError):
            P.validate_spawn("tasks-pm", "pm-glava", "coder")


def test_shipped_pipelines_reference_existing_skills():
    """Every skill named in a real pipeline.yaml must exist as a file.

    grill-me sat in default/pipeline.yaml for a month with no .md behind it: the
    orchestrator's send only reached the required-skill check once empty-pipeline
    sessions started resolving to `default`, and then every send 500'd.
    """
    import app.pipeline as real
    for pipeline_dir in sorted(real.PIPELINES_DIR.iterdir()):
        if not (pipeline_dir / "pipeline.yaml").is_file():
            continue
        cfg = real.load_pipeline(pipeline_dir.name)
        skills_dir = pipeline_dir / "prompts" / "skills"
        named = set()
        for holder in (cfg.defaults, *cfg.roles.values()):
            skills = getattr(holder, "skills", None)
            if isinstance(skills, list):
                named.update(skills)
        missing = sorted(s for s in named if not (skills_dir / f"{s}.md").is_file())
        assert not missing, f"{pipeline_dir.name}: skills without files: {missing}"
