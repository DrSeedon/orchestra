"""Offline process-local regression mutations; source files are never changed."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
MODE = sys.argv[1]


class Mutation:
    def pytest_collection_modifyitems(self):
        if MODE == "old-gate":
            from app import quota_gate

            def old_gate(runtime, *, is_orchestrator):
                return not is_orchestrator or runtime == "codex"

            # Existing imports in session.py keep the same function object.
            quota_gate.session_requires_quota.__code__ = old_gate.__code__
        elif MODE == "model-only-queue":
            from app import quota_queue

            quota_queue._is_orchestrator = lambda session: False
        elif MODE == "forced-wake-gate":
            from app import limit_wake
            original = limit_wake.codex_wake_admission

            async def forced(model, *, is_orchestrator=False):
                return await original(model)

            limit_wake.codex_wake_admission = forced
        else:
            raise ValueError(MODE)


selections = {
    "old-gate": ["tests/test_codex_quota_gate_1121.py", "-k",
                 "policy_exemption or codex_turn_admission or all_orchestrator_runtimes or creation_planned"],
    "model-only-queue": ["tests/test_quota_wait_queue.py", "-k",
                         "recovery_exempts_orchestrators_without_sharing_verdict"],
    "forced-wake-gate": ["tests/test_codex_limit_resume_v1081.py", "-k",
                         "actual_weekly_rule_only_blocks_workers or wake_exemption_does_not_fabricate"],
}
code = pytest.main([*selections[MODE], "-q", "--tb=short",
                    "--basetemp=.orchestra/tasks/V-1128/tmp/mutation"], plugins=[Mutation()])
print(f"Mutation {MODE}: pytest exit={int(code)}; TESTS_FAILED is expected")
raise SystemExit(0 if code == pytest.ExitCode.TESTS_FAILED else 1)
