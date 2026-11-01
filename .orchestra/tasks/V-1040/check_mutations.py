"""Temporarily revert individual fixes, require failing regression tests, always restore."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
notes = Path(__file__).resolve().parent
client = root / "app/multicode_client.py"
backend = root / "app/backend_hub.py"
originals = {path: path.read_text() for path in (client, backend)}
uv = notes / "runtime/bin/uv"


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


mutations = [
    ("session-recovery", client,
     lambda text: replace_once(text, "if _retry_session:", "if False:"),
     "long_lived_client or second_session_failure or failed_reinitialize"),
    ("http-body", client,
     lambda text: replace_once(text,
         'f"MultiCode MCP returned HTTP {response.status_code}: {detail}",',
         'f"MultiCode MCP returned HTTP {response.status_code}",'),
     "plain_http_400 or second_session_failure or session_400_without or failed_reinitialize"),
    ("http-redaction", client,
     lambda text: replace_once(text, 'detail = self._redact(body)[:300]', 'detail = body[:300]'),
     "plain_http_400 or second_session_failure or bounds_retries"),
    ("redact-before-truncation", client,
     lambda text: replace_once(text, 'detail = self._redact(body)[:300]', 'detail = self._redact(body[:300])'),
     "plain_http_400"),
    ("single-session-retry", client,
     lambda text: replace_once(text,
         'return await self._post(message, _retry_session=False)',
         'return await self._post(message, _retry_session=True)'),
     "second_session_failure"),
    ("watch-backoff", backend,
     lambda text: replace_once(text,
         'waited = await self._watch_call(mc, "t3_thread_wait", {',
         'waited = await mc.tool_call("t3_thread_wait", {'),
     "watch_survives or bounds_retries or retries_exhausted"),
    ("watch-read-backoff", backend,
     lambda text: text.replace('await self._watch_call(mc, "t3_thread_read",',
                              'await mc.tool_call("t3_thread_read",'),
     "watch_reads_survive"),
    ("watch-attempt-bound", backend,
     lambda text: replace_once(text, 'for attempt in range(5):', 'for attempt in range(6):').replace(
         'attempt == 4', 'attempt == 5'),
     "bounds_retries"),
    ("watch-time-bound", backend,
     lambda text: replace_once(text, 'async with asyncio.timeout(60):', 'async with asyncio.timeout(120):'),
     "retry_budget_includes"),
    ("non-transient-watch-guard", backend,
     lambda text: replace_once(text, 'if not exc.retryable or attempt == 4 or self._abort:',
                              'if attempt == 4 or self._abort:'),
     "does_not_retry_non_transient"),
    ("uncertain-send-guard", backend,
     lambda text: replace_once(text,
         '                if exc.retryable:\n                    raise\n                logger.warning("hub thread',
         '                logger.warning("hub thread'),
     "start_never_relaunches and not missing_run_id"),
    ("uncertain-steer-guard", backend,
     lambda text: replace_once(text,
         '                if exc.retryable:\n                    raise  # Delivery may have succeeded; do not queue the same steer again.\n', ''),
     "uncertain_steer"),
    ("explicit-refusal-fallback", backend,
     lambda text: replace_once(text,
         '                if exc.retryable:\n                    raise\n                logger.warning("hub thread',
         '                if not _workspace_lost(exc):\n                    raise\n                logger.warning("hub thread'),
     "explicit_thread_refusal"),
    ("session-vs-workspace", backend,
     lambda text: replace_once(text,
         '    if isinstance(exc, MultiCodeError) and exc.retryable:\n        return False\n', ''),
     "is_not_workspace_loss"),
]

summary = []
try:
    for name, path, mutate, selection in mutations:
        for source, content in originals.items():
            source.write_text(content)
        mutated = mutate(originals[path])
        assert mutated != originals[path]
        path.write_text(mutated)
        command = [str(uv), "run", "--offline", "--frozen", "--no-sync", "python",
                   str(notes / "run_sparse_tests.py"), "tests/test_multicode_client.py",
                   "tests/test_backend_hub.py", "-q", "--tb=no", "-p", "no:cacheprovider",
                   "-k", selection]
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=30)
        (notes / f"mutation-{name}.log").write_text(result.stdout + result.stderr)
        summary.append(f"{name}: exit={result.returncode}; " + result.stdout.strip().splitlines()[-1])
        print(summary[-1], flush=True)
        assert result.returncode == 1, name
finally:
    for source, content in originals.items():
        source.write_text(content)
    (notes / "mutations.log").write_text("\n".join(summary) + "\n")
