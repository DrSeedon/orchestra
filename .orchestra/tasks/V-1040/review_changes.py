"""Render a review diff against the supplied source, reconstructed from the small edits."""
import difflib
from pathlib import Path

root = Path(__file__).resolve().parents[3]
client = root / "app/multicode_client.py"
backend = root / "app/backend_hub.py"
fixed_client = client.read_text()
fixed_backend = backend.read_text()

old_client = fixed_client
start = old_client.index('    def __init__(self, message: str, *, retryable: bool = False):')
end = old_client.index('\n\nclass MultiCodeClient:', start)
old_client = old_client[:start] + old_client[end:]
old_client = old_client.replace(
    '    async def _post(self, message: dict[str, Any], *,\n'
    '                    _retry_session: bool = True) -> tuple[dict[str, Any] | None, httpx.Headers]:',
    '    async def _post(self, message: dict[str, Any]) -> tuple[dict[str, Any] | None, httpx.Headers]:')
start = old_client.index('        except httpx.HTTPError as exc:')
end = old_client.index('        self._session_id = response.headers.get', start)
old_client = old_client[:start] + '''        except httpx.HTTPError as exc:
            raise MultiCodeError(f"MultiCode MCP request failed: {type(exc).__name__}") from None
        if response.status_code >= 400:
            raise MultiCodeError(f"MultiCode MCP returned HTTP {response.status_code}")
''' + old_client[end:]
old_client = old_client.replace('        }, _retry_session=False)', '        })')
old_client = old_client.replace(
    '        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},\n'
    '                         _retry_session=False)',
    '        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})')

old_backend = fixed_backend.replace(
    '    if isinstance(exc, MultiCodeError) and exc.retryable:\n        return False\n', '')
old_backend = old_backend.replace(
    '                if exc.retryable:\n'
    '                    raise  # Delivery may have succeeded; do not queue the same steer again.\n', '')
start = old_backend.index('            except MultiCodeError as exc:\n                # Delivery is uncertain')
end = old_backend.index('        launched = await mc.tool_call', start)
old_backend = old_backend[:start] + '''                return sent["runId"]
            except (MultiCodeError, KeyError, TypeError) as exc:
                logger.warning("hub thread %s unusable (%s); starting a new one", state.thread_id, exc)
                state.thread_id = ""
                prompt = self._preamble() + prompt
''' + old_backend[end:]
start = old_backend.index('    async def _watch_call(')
end = old_backend.index('    async def _poll(', start)
old_backend = old_backend[:start] + old_backend[end:]
old_backend = old_backend.replace('await self._watch_call(mc, "t3_thread_wait",', 'await mc.tool_call("t3_thread_wait",')
old_backend = old_backend.replace('await self._watch_call(mc, "t3_thread_read",', 'await mc.tool_call("t3_thread_read",')

old_tests = (root / 'tests/test_multicode_client.py').read_text().split(
    '\n\n@pytest.mark.asyncio\n@pytest.mark.parametrize("status,detail", [', 1)[0] + '\n'
parts = []
for name, old, new in [
    ('app/multicode_client.py', old_client, fixed_client),
    ('app/backend_hub.py', old_backend, fixed_backend),
    ('tests/test_multicode_client.py', old_tests, (root / 'tests/test_multicode_client.py').read_text()),
    ('tests/test_backend_hub.py', '', (root / 'tests/test_backend_hub.py').read_text()),
]:
    parts.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                    fromfile='a/' + name, tofile='b/' + name))
    print(f'{name}: {len(new.splitlines()) - len(old.splitlines()):+d} lines')
Path(__file__).with_name('review.diff').write_text(''.join(parts))
