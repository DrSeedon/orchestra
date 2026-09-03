# fix-voice-upload memory

- After a process successfully reads media but `httpx.AsyncClient` raises a bare
  `FileNotFoundError`, check the TLS CA lookup before changing media cleanup. Compare the service
  interpreter with the current venv and inspect `/proc/<pid>/maps` for `(deleted)` mappings; a
  replaced live venv can leave `certifi.where()` pointing at a missing CA bundle.
