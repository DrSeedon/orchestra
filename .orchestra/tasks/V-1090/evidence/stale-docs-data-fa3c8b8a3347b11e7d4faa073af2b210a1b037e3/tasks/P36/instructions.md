# kanbanlite

kanbanlite is the small kanban board our team runs from the terminal. The
board lives in one JSON file; every card sits in one of four columns (backlog,
doing, review, done) and has a priority and an optional owner. Settings come
from built-in defaults that a JSON settings file can override.

## Layout

- `kanbanlite/model.py` - columns, priorities and the `Card` record, conversion to and from board file entries
- `kanbanlite/settings.py` - loads the settings file and fills in defaults
- `kanbanlite/board.py` - reads and writes the board file, adds, finds and moves cards
- `kanbanlite/cli.py` - the command line (`add`, `move`, `show`)
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. Nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run it from the repository root. Tests create files only in temporary folders.

## Usage

```
python -m kanbanlite.cli --settings kanban.json add "Write release notes" --owner ana
python -m kanbanlite.cli --settings kanban.json move K-3 review
python -m kanbanlite.cli --settings kanban.json show
```

The settings file is a JSON object. Keys it leaves out keep their defaults:
`board_file` (`board.json`), `default_priority` (`normal`) and
`max_title_length` (80). A key that is not a known setting is an error.
Commands exit with status 2 when something is wrong.

## Conventions

- Standard library only. pytest is the only development dependency.
- A fixed set of named values is a group of module-level string constants
  with a shared prefix, plus a tuple of all of them, for example
  `PRIORITY_HIGH = "high"` and `PRIORITIES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH)`.
  Compare and store the plain strings. Do not use `enum`.
- Settings are a frozen `Settings` dataclass with one typed field per
  setting. Read a setting as an attribute, for example `settings.board_file`,
  never by string key. A new setting is a new field with its default.
- Signal errors with the package's own exception classes. They all derive
  from one base class, `KanbanError`; for example `BoardError` is for a board
  file that cannot be read and `SettingsError` for a bad setting. Do not
  raise built-in exceptions such as `ValueError` or `KeyError`.
- Tests are `unittest.TestCase` classes that use the `self.assert*` methods
  (`assertEqual`, `assertRaises`, `assertFalse`). Create files in a
  `tempfile.TemporaryDirectory()` made in `setUp`.
- Card ids are `K-` followed by a number; `next_card_id()` hands them out.
- The board file is written with `json.dump(..., indent=2)`.
