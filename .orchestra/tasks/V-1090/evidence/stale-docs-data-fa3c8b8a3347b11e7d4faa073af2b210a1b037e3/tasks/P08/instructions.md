# snapback

snapback makes point-in-time copies ("snapshots") of a directory into a backup
root and restores them. Each snapshot is a timestamped folder that holds the
copied files and a manifest with a SHA-256 hash per file, so a restore can be
verified before anything is written to the target.

## Layout

- `snapback/manifest.py` - building, writing and reading manifests
- `snapback/snapshot.py` - creating snapshots
- `snapback/catalog.py` - finding the snapshots in a backup root
- `snapback/restore.py` - verifying and restoring snapshots
- `tests/` - pytest tests; shared fixtures are in `tests/conftest.py`

A backup root looks like this:

```
<root>/<source name>/<YYYYMMDDTHHMMSS>/manifest.json
<root>/<source name>/<YYYYMMDDTHHMMSS>/files/...
```

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. Tests work only inside pytest's
`tmp_path`.

## Conventions

- Use `pathlib.Path` for all filesystem work (`root / name`, `.iterdir()`,
  `.exists()`, `.is_dir()`). Do not use `os.path`.
- Report progress and warnings to the user with `print()`. Warnings go to
  `sys.stderr`, e.g. `print("warning:", reason, file=sys.stderr)`.
- Signal a failure by raising an exception with a clear message, e.g.
  `raise ValueError("no snapshots for {!r}".format(name))`. A function returns its
  result directly; do not return `(result, message)` pairs.
- Inside the package use absolute imports, e.g.
  `from snapback.manifest import read_manifest`.
- Copy files with `shutil.copy2` so that timestamps are kept.
- Never write or delete anything outside the backup root and the restore target.
- Standard library only.
