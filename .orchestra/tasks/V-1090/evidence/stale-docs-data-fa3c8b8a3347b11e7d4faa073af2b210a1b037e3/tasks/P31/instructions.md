# hostsfile

hostsfile reads, edits and writes hosts files of the `/etc/hosts` kind. It
parses every line into a record, so comments and blank lines survive an edit.
The parser accepts files with mistakes, so a broken file can still be read and
fixed. A small command line shows, adds and removes host names.

## Layout

- `hostsfile/model.py` - the `HostLine` record, line kinds, address families and `HostsFileError`
- `hostsfile/address.py` - checks IP addresses and host names
- `hostsfile/parser.py` - parses hosts file text into `HostLine` records
- `hostsfile/writer.py` - renders records back to text and writes the file with a backup
- `hostsfile/editor.py` - looks up, adds and removes host names
- `hostsfile/cli.py` - the command line (show, add, remove)
- `tests/` - pytest tests, one file per module

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m hostsfile.cli show HOSTS_FILE NAME
python -m hostsfile.cli add HOSTS_FILE ADDRESS NAME [NAME ...] [--comment TEXT]
python -m hostsfile.cli remove HOSTS_FILE NAME
```

The command exits with status 2 when the request fails. Edits copy the file
to `HOSTS_FILE.bak` before they write it.

## Conventions

- Standard library only. pytest is the only development dependency.
- Handle file system paths as plain strings with `os.path`, for example
  `os.path.join(folder, "hosts")` and `os.path.isfile(path)`. Do not use
  `pathlib`.
- Functions that check input report a failure to their caller as a pair
  `(value, error)`: `return result, None` on success and
  `return None, "line 4: no host name"` on failure. Do not raise for bad input.
- Fixed sets of names are module-level string constants, for example
  `ENTRY = "entry"`, and code compares against those names. Do not use `enum`.
- Use absolute imports inside the package, for example
  `from hostsfile.parser import parse_text`. Do not use relative imports.
- Docstrings use reST fields for parameters and results:
  `:param path: the hosts file` and `:returns: the parsed lines`.
- Host names are compared without regard to case; use `name_key()` from
  `hostsfile/address.py`.
- Records are dataclasses in `hostsfile/model.py`.
