"""#522: the platform injects the project's KB topic index into the system prompt.

Before this, the index lived inside the committed root rules and reached an agent only
after someone ran `--sync` and committed; foreign projects got no index at all.
"""
from pathlib import Path

import pytest

from app.kb_index import kb_index_block, kb_topic_index
from app.manager import ROLE_SYSTEM_PROMPT
from app.pipeline import DEFAULT_PIPELINE, known_roles

REPO = Path(__file__).parents[1]


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db
    init_db()
    from app.manager import SessionManager
    return SessionManager()


@pytest.fixture
def project(tmp_path):
    """A project scope with its own two-topic knowledge base."""
    kb = tmp_path / ".orchestra" / "kb"
    kb.mkdir(parents=True)
    (tmp_path / ".orchestra" / "layout.json").write_text("{}")
    (kb / "runtime.md").write_text("# Runtime\nDetails stay on demand.\n")
    (kb / "quotas.md").write_text("# Quotas\n")
    (kb / "README.md").write_text(
        "# База знаний\n\n"
        "- [Правила записи](../guides/knowledge-authoring.md) — не тема\n\n"
        "- [runtime](runtime.md) — Runtime: запуск и ошибки\n"
        "- [quotas](quotas.md) — Квоты: пулы и лимиты\n"
    )
    return tmp_path


# ── 1. Every role, including the one with no modules ────────────────────────

@pytest.mark.parametrize("role", known_roles(DEFAULT_PIPELINE))
def test_every_role_of_the_default_pipeline_receives_the_index(role, project):
    prompt = ROLE_SYSTEM_PROMPT(DEFAULT_PIPELINE, role, str(project))
    assert "## Project knowledge base" in prompt
    assert "- [Runtime: запуск и ошибки](.orchestra/kb/runtime.md)" in prompt


def test_reducer_gets_the_index_without_owning_a_module_that_carries_it(project):
    """#490 lost blocks exactly at the reducer: it has the thinnest module set.

    The index must not depend on any role's `modules:` list, or the next role added
    with a short list silently loses it again.
    """
    from app.prompting import _MODULES_DIR

    assert not any(
        "## Project knowledge base" in path.read_text()
        for path in _MODULES_DIR.glob("*.md")
    ), "the index must come from the platform, not from a prompt module"
    assert "## Project knowledge base" in ROLE_SYSTEM_PROMPT(
        DEFAULT_PIPELINE, "reducer", str(project)
    )


# ── 2. Source is the agent's own project, and a project without a KB gets nothing ──

def test_index_comes_from_the_agent_scope_not_from_orchestra(project):
    prompt = ROLE_SYSTEM_PROMPT(DEFAULT_PIPELINE, "worker", str(project))
    assert "Квоты: пулы и лимиты" in prompt
    # Orchestra's own topics must not leak into another project's prompt.
    assert "prompt-delivery.md" not in prompt


@pytest.mark.parametrize("state", ["no_scope", "no_kb_dir", "no_readme", "empty_index"])
def test_project_without_topics_gets_no_block_and_no_empty_heading(tmp_path, state):
    if state == "no_scope":
        scope = ""
    else:
        scope = str(tmp_path)
        if state != "no_kb_dir":
            kb = tmp_path / ".orchestra" / "kb"
            kb.mkdir(parents=True)
            if state != "no_readme":
                (kb / "README.md").write_text("# База знаний\n\nПока тем нет.\n")
    assert kb_index_block(scope) == ""
    assert "## Project knowledge base" not in ROLE_SYSTEM_PROMPT(
        DEFAULT_PIPELINE, "worker", scope
    )


def test_dangling_topic_link_is_refused(project):
    index = project / ".orchestra" / "kb" / "README.md"
    index.write_text(index.read_text().replace("(runtime.md)", "(missing.md)"))
    with pytest.raises(ValueError, match="outside its topic inventory"):
        kb_index_block(str(project))


def test_topic_resolving_outside_the_kb_directory_is_refused(project):
    kb = project / ".orchestra" / "kb"
    (kb / "escape.md").symlink_to(project / "AGENTS.md")
    (project / "AGENTS.md").write_text("# Rules\n")
    index = kb / "README.md"
    index.write_text(index.read_text() + "- [escape](escape.md) — Побег из kb/\n")
    with pytest.raises(ValueError, match="outside its topic inventory"):
        kb_index_block(str(project))


def test_non_topic_link_outside_kb_is_skipped_not_indexed(project):
    """`../guides/knowledge-authoring.md` is a real README line — a pointer, not a topic."""
    block = kb_index_block(str(project))
    assert "Правила записи" not in block
    assert "guides" not in block


def test_duplicate_and_empty_description_are_refused(project):
    kb = project / ".orchestra" / "kb"
    index = kb / "README.md"
    original = index.read_text()
    index.write_text(original + "- [runtime](runtime.md) — Ещё раз\n")
    with pytest.raises(ValueError, match="indexed more than once"):
        kb_topic_index(project)
    index.write_text(original.replace("— Квоты: пулы и лимиты", "—    "))
    with pytest.raises(ValueError, match="needs a description"):
        kb_topic_index(project)


# ── 3. A topic added to README reaches a LIVE agent on its next turn ─────────

@pytest.mark.asyncio
async def test_new_topic_reaches_the_next_turn_without_a_restart(project, mgr):
    """Measured on the exact function session.py calls when it re-injects the prompt."""
    spawned = ROLE_SYSTEM_PROMPT(DEFAULT_PIPELINE, "worker", str(project))
    assert "Сеть: диагностика" not in spawned

    kb = project / ".orchestra" / "kb"
    (kb / "network.md").write_text("# Network\n")
    index = kb / "README.md"
    index.write_text(index.read_text() + "- [network](network.md) — Сеть: диагностика\n")

    next_turn, overlay = mgr.assemble_prompt(
        pipeline=DEFAULT_PIPELINE, role="worker", scope=str(project), is_orch=False,
        name="w1", owned_dirs=[], branch="task-522/w1", stored_overlay="",
        old_prompt=spawned, repository_path=str(project),
    )
    assert "- [Сеть: диагностика](.orchestra/kb/network.md)" in next_turn
    assert overlay == ""
    # The two older topics are still there — the block is rebuilt, not appended to.
    assert next_turn.count("## Project knowledge base") == 1
    assert "Квоты: пулы и лимиты" in next_turn


# ── 5. Every path in the block opens from the repository root, no guessing ───

def test_every_indexed_path_resolves_from_the_repository_root():
    block = kb_index_block(str(REPO))
    paths = [
        line.split("](", 1)[1].rstrip(")")
        for line in block.splitlines() if line.startswith("- [")
    ]
    assert len(paths) == len(kb_topic_index(REPO))
    missing = [p for p in paths if not (REPO / p).is_file()]
    assert not missing, f"agent would have to guess where these went: {missing}"
