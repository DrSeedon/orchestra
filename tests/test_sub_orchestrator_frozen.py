"""#V-598 — роль sub-orchestrator заморожена: её нельзя заспавнить ни одной ролью."""
import pytest
from app.pipeline import validate_spawn, load_pipeline


def test_nobody_can_spawn_a_sub_orchestrator():
    for parent in ("orchestrator", "sub-orchestrator", "full-cycle", "worker", "reducer"):
        with pytest.raises(ValueError):
            validate_spawn("default", parent, "sub-orchestrator")


def test_ordinary_roles_are_still_spawnable():
    for child in ("worker", "full-cycle", "reducer"):
        validate_spawn("default", "orchestrator", child)
        validate_spawn("default", "full-cycle", child)


def test_role_stays_in_the_manifest_for_the_living_agent():
    """Удалить роль нельзя: живой bench-master без неё не соберёт системный промпт."""
    assert "sub-orchestrator" in load_pipeline("default").roles
