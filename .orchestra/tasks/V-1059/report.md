# V-1059 — hub image tool

DONE: CLI and a separate one-tool stdio MCP server are implemented. Live VPS-to-hub
validation and Kesha registration remain with the orchestrator/next team, as assigned.
No deployment, restart, paid provider API, DostupAI call, or manual git operation was made.
The platform commits this copy to `task-V-1059/feat-hub-image` when the worker finishes.

## CLI and registration

From the Orchestra checkout, with the existing MultiCode variables exported:

```sh
uv run --frozen python -m app.hub_image 'A watercolor blue bird' --size 16:9 --count 1 --timeout-seconds 300
uv run --frozen python -m app.hub_image_mcp
```

The CLI writes progress to stderr (thread created, image found, fetched path,
cleanup started/completed), JSON to stdout, and exits 0 only after success and cleanup.
Success is `{"ok":true,"paths":["<absolute-local-png-path>"]}`. Images persist locally
under `data/generated-images/`; CLI `--output-dir <local-directory>` overrides it.
The MCP tool returns the same object as structured content and JSON text, with
`isError: true` on failure. It exposes only `hub_generate_image(prompt, count=1,
size="", timeout_seconds=300)`. Count is 1..4, timeout is 1..1800 seconds.
Size/aspect is a visual prompt hint; actual dimensions are not promised or rescaled.

Example Kesha MCP config (substitute private values locally; do not commit them):

```json
{
  "mcpServers": {
    "orchestra-hub-images": {
      "command": "<absolute-uv-executable>",
      "args": ["run", "--directory", "<orchestra-checkout>", "--frozen", "python", "-m", "app.hub_image_mcp"],
      "env": {
        "MULTICODE_MCP_BASE": "https://<hub-host>/<existing-mcp-base>",
        "MULTICODE_MCP_TOKEN_FILE": "<existing-private-token-file>",
        "MULTICODE_HUB_SSH": "<hub-user>@<hub-host>",
        "MULTICODE_HUB_SSH_KEY": "<existing-private-ssh-key-file>"
      }
    }
  }
}
```

Reuse the deployment's existing MCP base and SSH settings verbatim; the client appends
`/mcp` to its base. The token file and SSH key must be readable by the MCP process.
The CLI/server expects exported environment and does not implicitly load `.env`.
The existing optional `MULTICODE_HUB_WORKSPACE_ROOT` and provider-log directory work
through `HubSsh`. Kesha must be able to read the returned local files. Set its MCP
request timeout to at least `timeout_seconds + 70` (370 seconds for the default),
since cleanup has its own 60-second deadline. Registering/running `tools/list` makes
no generation request and requires no hub credentials. See `tools-list.json` for the
actual saved stdio protocol result.

## Implementation and recovery

Reuses `MultiCodeClient`, `HubSsh`, `WorkspaceState`, `release_workspace`, the Sol
mapping in `backend_hub.HUB_MODELS`, and its provider-limit classification. No second
hub client. Uploads only the visual prompt and execution instructions, never repository
files or credentials. Each request has its own empty workspace/project and Codex Sol
thread. The idle thread ID is persisted before generation starts, so a lost send
response cannot leave an unknown producer. A lost project-create response is resolved
by the exact workspace path, without replaying creation or generation.

Before generation, the hub agent records `CODEX_THREAD_ID` and its generated root.
It awaits each built-in image call and moves its actual output into numbered PNGs.
The broker reads only those regular tar members, validates their PNG data and size,
and writes unique local names without overwriting existing images. Archive links,
duplicates and unrelated paths cannot become local files.

Cleanup interrupts and waits for the producer, deletes only its validated native
Codex session directory, then uses the existing project/workspace removal and
verification. This removes generated originals as well as fetched workspace copies.
The generated root must match the SSH account's canonical
`${CODEX_HOME:-$HOME/.codex}/generated_images`; a mismatch is refused. The exact
location/naming, result fields and deletion of the real probe are in `hub-facts.txt`.
Its returned hint is verbatim except for replacement of the forbidden private home
prefix by `<CODEX_HOME>`.

Errors include `not_configured`, `hub_unavailable`, `provider_limit`, `timeout`,
`no_image`, `invalid_output`, `generation_failed`, and `cleanup_failed`. Provider
account details and transport paths are not exposed. A cleanup failure returns
`ok:false`, retains any already downloaded paths and leaves local recovery records
in ignored `data/hub-workspaces/` and `data/hub-images/`. Retry the printed command:

```sh
uv run --frozen python -m app.hub_image --cleanup <workspace-id>
```

This retry accepts only image-job records, not ordinary workers. It handles an
already-deleted thread and an already-removed generated directory. A still-running
producer prevents deletion. `HubSsh.run` now kills/reaps its own SSH subprocess on
cancellation as well as its existing timeout; this is needed for the outer deadline.

Hard process death, a hub outage, or an image tool that outlives interruption still
requires a recovery pass. The live VPS run must confirm that a fresh Sol thread obeys
the preflight/move protocol and that project deletion waits for image work. The tool
response does not independently attest the backend model name: gpt-image-2 is the
requested built-in route. No fallback is implemented.

## Verification

Runner: provisioned uv 0.11.28, default `.venv`, frozen `uv.lock`. No lock changes.
The real built-in image probe succeeded once: PNG, RGB, 1254x1254, 993640 bytes,
then both file and its empty generated session directory were deleted. No live
VPS end-to-end call was attempted because this worker has no hub credentials.

Final targeted command, with the broker's uv on PATH:

```sh
uv run --frozen python -m pytest tests/test_hub_image.py tests/test_multicode_client.py tests/test_hub_workspace.py::test_release_removes_hub_project_directory_and_state tests/test_hub_workspace.py::test_failed_cleanup_keeps_the_record_for_a_retry tests/test_hub_workspace.py::test_release_proves_project_thread_and_directory_are_gone tests/test_hub_workspace.py::test_release_keeps_the_record_when_the_hub_still_shows_the_project tests/test_hub_workspace.py::test_ssh_failures_always_say_what_failed -q
```

Result: **63 passed**, including file discovery, malformed output/links, cleanup,
cleanup retry, lost responses, wall-clock timeout, cleanup timeout, provider limits,
configuration errors, CLI JSON exit status, schema/error flags and a real stdio
initialize/tools-list subprocess. `pytest.txt` contains the final output.

An earlier broader command included all of `tests/test_hub_workspace.py` and returned
**178 passed, 2 failed**. Both failures are existing prompt tests depending on the
missing copied source `.orchestra/pipelines/default/prompts/hub/worker.md`:
`test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools` and
`test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it`. `hub_preamble`
therefore takes its fallback branch. No acceptance test or unrelated prompt code
was changed. The sanitized output is in `pytest-broader.txt`. The complete suite
was not run; those two checks need the missing source on the full checkout.

Imported `app` was verified at the absolute path `<workspace>/app/__init__.py` in
this private copy; the actual prefix was observed in the runner output and is
deliberately excluded from tracked artifacts by the task's private-path rule.
Raw test output is sanitized before inclusion; changed files are checked against
the existing credential-shape patterns without opening credential stores.

## File list

- `app/hub_image.py` — CLI, transport orchestration, download, cleanup/recovery.
- `app/hub_image_mcp.py` — one-tool stdio server.
- `app/hub_workspace.py` — cancellation reaps the exact SSH child.
- `tests/test_hub_image.py` — offline behavior, schema and protocol tests.
- `CHANGELOG.md` — Unreleased entry.
- `.orchestra/tasks/V-1059/hub-facts.txt` — verified built-in output facts.
- `.orchestra/tasks/V-1059/tools-list.json` — actual stdio tools/list response.
- `.orchestra/tasks/V-1059/pytest.txt` — final targeted test result.
- `.orchestra/tasks/V-1059/pytest-broader.txt` — sanitized broader-run evidence.
- `.orchestra/tasks/V-1059/report.md` — this report and registration instructions.
