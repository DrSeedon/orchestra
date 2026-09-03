# fix-pidfd-import

- The project `uv run` interpreter may lack `os.pidfd_open` even when the system `python` has it; check capability with the exact interpreter used by tests and production subprocesses.
