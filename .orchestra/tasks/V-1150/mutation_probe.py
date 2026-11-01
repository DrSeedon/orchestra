"""Run task regressions against focused defects, restoring each source verbatim."""
from pathlib import Path
import argparse
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
notes = root / ".orchestra/tasks/V-1150"
uv = shutil.which("uv")
assert uv and "0.11.28" in uv, "use the provisioned uv PATH"
test = "tests/test_codex_compact_delivery_1150.py::"
mutations = [
    ("timeout", "app/backend_codex.py", "CODEX_COMPACT_TIMEOUT_SECONDS = 600",
     "CODEX_COMPACT_TIMEOUT_SECONDS = 120  # mutation",
     test + "test_observed_227_second_compact_publishes_before_bounded_deadline"),
    ("late_publication", "app/backend_codex.py", "on_reconciled=observer,",
     "on_reconciled=None,", test + "test_late_success_publishes_session_without_rewriting_caller"),
    ("last_call", "app/backend_codex.py",
     "            op.context_tokens = self._optional_nonnegative_int(tokens)",
     "            op.context_tokens = self._optional_nonnegative_int(tokens)\n"
     "            self._last_call_usage = self._usage_breakdown(usage.get('last') or {})",
     test + "test_old_compact_usage_cannot_become_user_last_call"),
    ("queue_recovery", "app/session.py",
     "                        self._spawn_bg(self._flush_pending())\n                    elif self.status",
     "                        pass\n                    elif self.status",
     test + "test_late_terminal_retries_refused_queue_but_respects_manual_stop[False]"),
    ("browser_timeout", "app/static/js/app.js", "timeoutMs: 660000,",
     "timeoutMs: 5000,", "tests/test_codex_compact_ui_1150.py"),
    ("immediate_freshness", "app/session.py",
     "                        raise error\n\n                def reconciled",
     "                        return\n\n                def reconciled",
     "tests/test_codex_compact_immediate_1150.py::test_awaited_compact_cannot_publish_after_supported_lifecycle_change"),
]
parser = argparse.ArgumentParser()
parser.add_argument("--only", choices=[entry[0] for entry in mutations])
selection = parser.parse_args().only
for name, relative, before, after, target in mutations:
    if selection is not None and name != selection:
        continue
    path = root / relative
    original = path.read_bytes()
    source = original.decode()
    assert source.count(before) == 1, (name, "mutation location drifted")
    try:
        path.write_text(source.replace(before, after))
        with (notes / "private" / f"mutation-{name}.txt").open("wb") as log:
            result = subprocess.run([
                uv, "run", "--frozen", "python", "-m", "pytest", target, "-q",
                f"--basetemp=.orchestra/tasks/V-1150/pytest-tmp-mutation-{name}",
            ], cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        evidence = (notes / "private" / f"mutation-{name}.txt").read_text()
        assert result.returncode == 1 and "FAILED " in evidence, (name, result.returncode)
        print(f"PASS: {name} defect rejected by behavioral regression", flush=True)
    finally:
        path.write_bytes(original)
        assert path.read_bytes() == original
