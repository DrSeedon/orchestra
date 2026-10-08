from pathlib import Path

import pytest

from app.kb_index import kb_topic_index


def make(tmp_path, readme, topics=("a", "b", "c")):
    kb = tmp_path / ".orchestra" / "kb"
    kb.mkdir(parents=True)
    for t in topics:
        (kb / f"{t}.md").write_text(f"# {t}\n")
    (kb / "README.md").write_text(readme)
    return tmp_path


def test_deprecated_skipped(tmp_path):
    root = make(tmp_path, "- [a](a.md) — Active topic\n- [b](b.md) — DEPRECATED old stuff\n")
    assert kb_topic_index(root) == {"a.md": "Active topic"}


def test_case_sensitive_and_prefix_only(tmp_path):
    root = make(tmp_path, "- [a](a.md) — deprecated lower\n- [b](b.md) — Not DEPRECATED here\n- [c](c.md) — DEPRECATEDX tail\n")
    got = kb_topic_index(root)
    assert set(got) == {"a.md", "b.md"}


def test_duplicate_with_deprecated_still_raises(tmp_path):
    root = make(tmp_path, "- [a](a.md) — DEPRECATED first\n- [a](a.md) — Active again\n")
    with pytest.raises(ValueError):
        kb_topic_index(root)


def test_deprecated_pointing_outside_inventory_raises(tmp_path):
    root = make(tmp_path, "- [x](missing.md) — DEPRECATED gone\n")
    with pytest.raises(ValueError):
        kb_topic_index(root)


def test_active_empty_description_raises(tmp_path):
    root = make(tmp_path, "- [a](a.md) —  \n- [b](b.md) — ok\n")
    # a line with a blank description either does not match or raises; it must not be silently kept
    got = None
    try:
        got = kb_topic_index(root)
    except ValueError:
        return
    assert "a.md" not in got


def test_order_preserved(tmp_path):
    root = make(tmp_path, "- [c](c.md) — C\n- [a](a.md) — A\n- [b](b.md) — DEPRECATED B\n")
    assert list(kb_topic_index(root)) == ["c.md", "a.md"]
