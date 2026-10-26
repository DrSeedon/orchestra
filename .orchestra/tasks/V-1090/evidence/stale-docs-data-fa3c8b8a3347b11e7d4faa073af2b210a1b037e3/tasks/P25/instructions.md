# envcheck

envcheck checks the env files of our services before a deploy. A schema file
lists the variables that a service reads and their types, and envcheck reports
every variable that is missing or has a bad value. The deploy pipeline runs the
check command for each service and stops on a non-zero exit status.

## Layout

- `envcheck/errors.py` - the errors that envcheck reports
- `envcheck/envfile.py` - reads env files (`NAME=value` lines)
- `envcheck/schema.py` - reads the schema file
- `envcheck/rules.py` - type checks and the check of env values against the schema
- `envcheck/settings.py` - reads the settings file
- `envcheck/check.py` - the check command for one env file
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m envcheck.check SETTINGS_FILE ENV_FILE
```

The settings file is an INI file with one `[envcheck]` section:

```
[envcheck]
schema = app.schema
allow_empty = no
```

Each schema line is `NAME TYPE [required|optional]`, where TYPE is `int`,
`bool`, `url` or `str`. The command prints one line per problem and exits
with status 0 when there is none, 1 when a variable is missing or invalid and
2 when the settings, the schema or the env file cannot be used.

## Conventions

- Settings are a `Settings` dataclass that `load_settings()` returns. Read
  them as attributes, for example `settings.allow_empty`. A new setting is a
  new field with its default value.
- Work with paths through `pathlib.Path`: `Path(folder) / name`,
  `path.read_text()`, `folder.glob("*.env")`. Do not use `os.path`.
- Raise built-in exceptions with a clear message: `ValueError` for bad
  content, `FileNotFoundError` for a missing file or folder. Do not define
  exception classes of your own. The commands catch the errors and exit
  with status 2.
- Write docstrings in reST style, with `:param name:`, `:returns:` and
  `:raises ErrorType:` fields.
- Type hints use the `typing` generics: `List[str]`, `Dict[str, str]`.
- Standard library only. pytest is the only development dependency.
- The schema path in the settings file is relative to the folder of the
  settings file.
- In env files, an `export` prefix, quotes around a value and `#` comments
  are allowed. A name that is set twice keeps its last value.
- Tests are plain pytest functions in `tests/test_<module>.py`. They write
  files only under pytest's `tmp_path`.
