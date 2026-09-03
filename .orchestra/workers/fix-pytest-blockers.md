# fix-pytest-blockers

- Python capabilities used by process guards can be absent independently (`os.pidfd_open` and `signal.pidfd_send_signal`); resolve them at call time and fail with typed errors instead of binding defaults at import.
