"""Тесты generic-скаффолда doc-папок (app.manager._scaffold_role_docs).

Изолированный модуль: фикстура строит синтетический pipelines/<uniq>/ на tmp_path
и патчит app.pipeline.PIPELINES_DIR. На приватный sapto-pm НЕ опираемся — тест
проходит без приватных файлов.
"""
from __future__ import annotations

import textwrap

import pytest

import app.pipeline as P
from app.manager import _scaffold_role_docs

PIPELINE = "scafftest"

# Синтетический манифест: 3 роли.
#   orch-plain — orchestrator с docs_dir БЕЗ requires (скаффолдится всегда)
#   orch-feat  — orchestrator с docs_dir requires:feature
#   orch-off   — orchestrator с docs_dir, но docs_scaffold:false (пропуск)
#   plain-wk   — worker без docs_dir (ничего)
_YAML = """
name: scafftest
defaults:
  docs_scaffold: true
roles:
  orch-plain: {kind: orchestrator, label: Plain, docs_dir: {path: _plain, template: plain.md}}
  orch-feat:  {kind: orchestrator, label: Feat, docs_dir: {path: "{feature}/_feat", template: feat.md, requires: feature}}
  orch-off:   {kind: orchestrator, label: "Off", docs_scaffold: false, docs_dir: {path: _off, template: plain.md}}
  plain-wk:   {kind: worker, label: Worker}
"""


@pytest.fixture
def pipelines_root(tmp_path, monkeypatch):
    """Подменяет корень пайплайнов на tmp + строит синтетический пайплайн.

    Возвращает кортеж (root, cwd): root — pipelines/, cwd — рабочая папка сессии.
    """
    root = tmp_path / "pipelines"
    d = root / PIPELINE / "templates"
    d.mkdir(parents=True)
    (root / PIPELINE / "pipeline.yaml").write_text(textwrap.dedent(_YAML))
    (d / "plain.md").write_text("# Plain dashboard\nстатичный контент\n")
    (d / "feat.md").write_text("# Feat dashboard — {feature}\nфича: {feature}\n")
    monkeypatch.setattr(P, "PIPELINES_DIR", root)
    P.load_pipeline.cache_clear()
    cwd = tmp_path / "work"
    cwd.mkdir()
    yield root, cwd
    P.load_pipeline.cache_clear()


def test_docs_dir_no_requires_creates_dashboard(pipelines_root):
    """(a) роль с docs_dir без requires → папка + dashboard.md с контентом шаблона."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
    dash = cwd / "docs_work" / "_plain" / "dashboard.md"
    assert dash.is_file()
    assert "Plain dashboard" in dash.read_text()


def test_requires_feature_with_feature(pipelines_root):
    """(b) requires:feature С feature → создаётся <feature>/..., {feature} подставлен."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat", feature="login")
    dash = cwd / "docs_work" / "login" / "_feat" / "dashboard.md"
    assert dash.is_file()
    content = dash.read_text()
    assert "login" in content
    assert "{feature}" not in content


def test_requires_feature_without_feature_skips(pipelines_root):
    """(c) requires:feature БЕЗ feature → ничего не создаётся."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat")
    assert not (cwd / "docs_work").exists()


def test_no_docs_dir_skips(pipelines_root):
    """(d) роль без docs_dir → ничего не создаётся."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "plain-wk")
    assert not (cwd / "docs_work").exists()


def test_idempotent_no_overwrite(pipelines_root):
    """(e) повторный вызов не перезатирает существующий dashboard.md."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
    dash = cwd / "docs_work" / "_plain" / "dashboard.md"
    dash.write_text("РУЧНАЯ ПРАВКА")
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
    assert dash.read_text() == "РУЧНАЯ ПРАВКА"


def test_docs_scaffold_false_skips(pipelines_root):
    """(f) docs_scaffold:false на роли → пропуск."""
    _root, cwd = pipelines_root
    _scaffold_role_docs(PIPELINE, str(cwd), "orch-off")
    assert not (cwd / "docs_work" / "_off").exists()


def test_missing_pipeline_skips(tmp_path, monkeypatch):
    """Манифеста нет (FileNotFoundError) → тихий пропуск, без исключения."""
    monkeypatch.setattr(P, "PIPELINES_DIR", tmp_path / "no_such")
    P.load_pipeline.cache_clear()
    cwd = tmp_path / "work"
    cwd.mkdir()
    _scaffold_role_docs("nonexistent", str(cwd), "orch-plain")
    assert not (cwd / "docs_work").exists()
    P.load_pipeline.cache_clear()
