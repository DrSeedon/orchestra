"""Restore the two original gaps in memory; the regression suite must turn RED.

No source files or fixtures are rewritten. This is a surgical defect mutation,
not a claim to have checked out a complete historical revision in this Gitless copy.
Run from the repository root with the provisioned uv and the repository TMPDIR.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest


class OldGap:
    def pytest_configure(self, config):
        from app import limit_wake
        from app.session import AgentSession

        handle_event = AgentSession._handle_event
        readiness = limit_wake.provider_readiness

        def old_handle_event(session, event):
            if event.type != "error" or not event.metadata.get("codex_quota_exhausted"):
                return handle_event(session, event)
            log = session._log

            def old_log(kind, *args, **kwargs):
                if kind != "provider_limit":
                    return log(kind, *args, **kwargs)

            session._log = old_log
            try:
                return handle_event(session, event)
            finally:
                session._log = log

        def old_readiness(envelope, provider, **kwargs):
            # Originally Codex shared this exact generic non-Anthropic branch.
            return readiness(envelope, "grok" if provider in {"codex", "codex_spark"} else provider,
                             **kwargs)

        AgentSession._handle_event = old_handle_event
        limit_wake.provider_readiness = old_readiness


raise SystemExit(pytest.main([
    "tests/test_codex_limit_resume_v1081.py", "-q", "-k",
    "native_refusal or backend_through_scheduler or capacity_needs_actual or ordinary_user_turn",
], plugins=[OldGap()]))
