# V-1030: Document the hub worker copy

Added three English sentences only to the MultiCode hub — the FIRST route bullet in `.orchestra/pipelines/default/prompts/modules/model-routing.md`.

Verified against the supplied `app/hub_workspace.py`:
- `plan_upload` and `_git_files` select tracked plus untracked, non-ignored files within the owned scope; `_under` also includes repo-level files. This exception is explicit in the addition so an orchestrator does not assume root files are absent.
- `require_scope` refuses empty ownership before upload except for persistent projects. An empty scope then selects the worktree subject to project caps and exclusions.
- Credential checks and `options.max_file_bytes` exclude files; `MAX_FILE_BYTES` defaults to 20 * 1024 * 1024 bytes. Project options may override that limit, so the addition says 20 MB by default.
- `prepare_scope` materializes committed owned paths omitted by sparse checkout, or raises on failure.

Checks performed:
- Read and reviewed the changed bullet and the implementation above, including scoped and persistent behavior, size boundaries (`>`), exclusions, and sparse-checkout recovery.
- Removed the inserted span in memory with Perl and piped the result to `sha256sum`: `d0b9bf31600153e1ba1d77aa424b19951cabe73d69fb1af5f789f7566510346d`, identical to the original file hash. All original bytes outside the addition are preserved.
- Attempted an offline `uv run --frozen python` scope check; unavailable: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`. Used the successful shell/Perl hash check instead. No prompt-wording tests were added.

Limitations: the supplied source contains no turn status-line producer, so the first-status-line sentence follows the explicit task fact and could not be independently verified here. Tests and the instruction-contract script were not supplied. No app import or runtime tests ran; the inspected app directory is `<hub-user>/orchestra-ws/…/app`.

No Git operations were performed: this worker copy has no `.git`, and the platform owns the resulting commit. Requested commit header: `V-1030: Document hub worker upload scope`.
