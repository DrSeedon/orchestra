"""Without delivery, an agent would fall back to the obsolete personal access recipe."""
import subprocess

import pytest

from app import pipeline, prompting


@pytest.mark.parametrize("role", ["orchestrator", "sub-orchestrator", "worker", "full-cycle"])
def test_operational_roles_discover_laptop_skill(role):
    assert "laptop-access" in pipeline.get_role("default", role).skills


def test_report_collector_does_not_receive_laptop_skill():
    assert "laptop-access" not in pipeline.get_role("default", "reducer").skills


@pytest.mark.parametrize("home_dir", [".claude", ".codex"])
def test_native_delivery_preserves_canonical_skill(tmp_path, home_dir):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = prompting.inject_skills_to_worktree_report(["laptop-access"], str(tmp_path), home_dir)
    canonical = pipeline.prompt_path("default", "skills/laptop-access.md")
    delivered = tmp_path / home_dir / "skills/laptop-access/SKILL.md"
    assert result.written == 1
    assert delivered.read_bytes() == canonical.read_bytes()
