# notegrep

notegrep indexes a folder of markdown notes and answers word searches over it.
It reads every `.md` file below the notes folder, pulls out titles, words and
`[[wiki links]]`, and keeps a small JSON index next to the notes so searches
do not re-read every file. Our desktop note tools use it as a library, and it
has a small command line for quick searches.

## Layout

- `notegrep/notes.py` - finds note files and reads them into `Note` records
- `notegrep/parse.py` - titles, search words and wiki links from markdown text
- `notegrep/index.py` - builds, saves and loads the word index
- `notegrep/search.py` - all-words search and ranked any-word search
- `notegrep/__main__.py` - the `build` and `search` commands
- `tests/` - one test file per source module, plus shared fixtures in `conftest.py`

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. The suite runs in about a second.

## Usage

```
python -m notegrep build NOTES_DIR
python -m notegrep search NOTES_DIR tomato soup
python -m notegrep search NOTES_DIR tomato soup --any
```

`build` writes the index to `NOTES_DIR/.notegrep-index.json`. `search` reads
that index and shows the matching note names; it exits with status 1 when no
note matches. Both commands exit with status 2 if `NOTES_DIR` is not a folder.

## Conventions

- Standard library only. Do not add third-party packages.
- File system paths are plain strings handled with `os.path`
  (`os.path.join`, `os.path.isdir`, `os.path.splitext`, `os.walk`).
  Do not use `pathlib`.
- Diagnostics go through the `logging` module. Each module creates
  `logger = logging.getLogger(__name__)` and reports skipped files and
  problems with `logger.warning(...)`. Do not report them with `print()`.
- Every public function has a Google-style docstring with `Args:` and
  `Returns:` sections, plus `Raises:` when it raises.
- Test files are named after the module they test: `tests/<module>_test.py`
  (for example `tests/parse_test.py`).
- Tests that need files create them under pytest's `tmp_path`; tests never
  touch real notes or the network.
- Note names are file names without `.md`. Files and folders whose name
  starts with a dot are never read.
- Line length is 100 characters.
