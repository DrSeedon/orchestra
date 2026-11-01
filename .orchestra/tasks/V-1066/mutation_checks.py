"""In-memory mutations; each selected regression must fail. Never edit app sources."""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pytest
from app import backend_hub as hub, hub_workspace as hw
from app.multicode_client import MultiCodeError

mode = sys.argv[1]
original = hub.HubBackend._wire_message


async def inline(self, mc, state, prompt):
    return prompt


async def codepoints(self, mc, state, prompt):
    return prompt if len(prompt) <= 120_000 else await original(self, mc, state, prompt)


calls = 0


async def raw_retry(self, mc, state, prompt):
    global calls
    calls += 1
    return await original(self, mc, state, prompt) if calls == 1 else prompt


original_prompt = hub.HubBackend._prompt


def consume_early(self, message, *, first):
    prompt = original_prompt(self, message, first=first)
    self._early_steer.clear()
    return prompt


original_error = MultiCodeError.__init__


def forget_invalid(self, message, *, retryable=False, invalid_params=False):
    original_error(self, message, retryable=retryable, invalid_params=False)


cases = {
    "inline": (patch.object(hub.HubBackend, "_wire_message", inline),
               "test_native_attachment_survives_full_composition[resume]"),
    "params": (patch.object(MultiCodeError, "__init__", forget_invalid),
               "test_invalid_parameters_or_uncertain_send_never_replace_thread[rpc-send]"),
    "utf16": (patch.object(hub.HubBackend, "_wire_message", codepoints),
              "test_wire_boundary_uses_utf16_not_utf8_bytes_or_codepoints[astral-over]"),
    "steers": (patch.object(hub.HubBackend, "_prompt", consume_early),
               "test_early_steers_survive_start_failure_and_new_arrival"),
    "retry": (patch.object(hub.HubBackend, "_wire_message", raw_retry),
              "test_large_no_work_retry_uses_same_file_and_thread"),
    "exclusion": (patch.object(hw, "BLOCKED_DIRS", hw.BLOCKED_DIRS - {hw.PROMPT_DIR}),
                  "test_transport_files_never_import_or_upload_as_source"),
}
mutation, node = cases[mode]
with mutation:
    result = pytest.main(["tests/test_hub_message_v1066.py::" + node, "-q", "--tb=short",
                          "--basetemp=.orchestra/tasks/V-1066/tmp/mutation-" + mode])
print(f"MUTATION {mode}: pytest_exit={int(result)}; killed={result == pytest.ExitCode.TESTS_FAILED}")
raise SystemExit(0 if result == pytest.ExitCode.TESTS_FAILED else 1)
