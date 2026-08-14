"""#36: неизвестная роль не обходит can_spawn, даже при validation: fail-open."""
from __future__ import annotations

import textwrap

import pytest

import app.pipeline as P


@pytest.fixture
def pipelines_root(tmp_path, monkeypatch):
    root = tmp_path / "pipelines"
    root.mkdir()
    monkeypatch.setattr(P, "PIPELINES_DIR", root)
    P.load_pipeline.cache_clear()
    yield root
    P.load_pipeline.cache_clear()


def _write(root, name: str, yaml_text: str) -> None:
    d = root / name
    (d / "prompts").mkdir(parents=True, exist_ok=True)
    (d / "pipeline.yaml").write_text(textwrap.dedent(yaml_text))


_OPEN = """\
    name: opened
    validation: fail-open
    roles:
      lead: {kind: orchestrator, label: Lead, can_spawn: [coder], allow_unrouted_workers: false}
      coder: {kind: orchestrator, label: Coder, can_spawn: [], allow_unrouted_workers: false}
      boss: {kind: orchestrator, label: Boss, can_spawn: ["*"], allow_unrouted_workers: true}
"""


class TestFailOpenUnknownRoleIsDenied:
    def test_unknown_parent_raises(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        with pytest.raises(ValueError, match="unknown parent role 'phantom'"):
            P.validate_spawn("opened", "phantom", "coder")

    def test_unknown_child_raises_despite_explicit_whitelist(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        with pytest.raises(ValueError, match="unknown role 'mystery'"):
            P.validate_spawn("opened", "lead", "mystery")

    def test_unknown_child_raises_despite_wildcard(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        with pytest.raises(ValueError, match="unknown role 'ghost'"):
            P.validate_spawn("opened", "boss", "ghost")

    def test_terminal_cannot_spawn_unknown_child(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        with pytest.raises(ValueError, match="unknown role 'ghost'"):
            P.validate_spawn("opened", "coder", "ghost")

    def test_known_whitelist_still_allows(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        assert P.validate_spawn("opened", "lead", "coder") is None

    def test_known_wildcard_still_allows(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        assert P.validate_spawn("opened", "boss", "coder") is None

    def test_root_spawn_still_allowed(self, pipelines_root):
        _write(pipelines_root, "opened", _OPEN)
        assert P.validate_spawn("opened", "", "lead") is None
        assert P.validate_spawn("opened", None, "mystery") is None


class TestDefaultPipelineUnknownRoleIsDenied:
    def test_unknown_child_raises(self):
        P.load_pipeline.cache_clear()
        with pytest.raises(ValueError, match="unknown role 'nonexistent-role'"):
            P.validate_spawn("default", "orchestrator", "nonexistent-role")
        P.load_pipeline.cache_clear()

    def test_unknown_parent_raises(self):
        P.load_pipeline.cache_clear()
        with pytest.raises(ValueError, match="unknown parent role 'phantom'"):
            P.validate_spawn("default", "phantom", "worker")
        P.load_pipeline.cache_clear()

    def test_terminal_worker_cannot_spawn_unknown(self):
        P.load_pipeline.cache_clear()
        with pytest.raises(ValueError, match="unknown role 'ghost'"):
            P.validate_spawn("default", "worker", "ghost")
        P.load_pipeline.cache_clear()
