# mailmerge

mailmerge fills a text template with values from a recipients list and writes
the merged messages to an outbox file. Templates use `{{field}}` placeholders,
and every column of the recipients CSV can be used as a field. We use it for
customer notices and event invitations.

## Layout

- `mailmerge/recipients.py` - reads the recipients CSV, checks and de-duplicates addresses
- `mailmerge/template.py` - loads templates, lists their fields, fills placeholders
- `mailmerge/merge.py` - builds one message (to, subject, body) per recipient
- `mailmerge/outbox.py` - writes merged messages to one outbox text file
- `mailmerge/__main__.py` - the command line entry point
- `tests/` - pytest tests, one file per module, shared fixtures in `conftest.py`

## Setup

Python 3.10 or newer. The package uses the standard library only; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m mailmerge TEMPLATE RECIPIENTS OUTBOX [--subject TEXT] [--default FIELD=VALUE ...]
```

`--default` gives a value for a field that is empty or missing for a
recipient. The command exits with status 2 when an input file cannot be read.

## Conventions

- Tell the user what is going on with plain `print()` calls: skipped
  recipients, counts, the files written. Do not set up `logging` loggers.
- Build text from values with `str.format()`, for example
  `"Dear {},".format(name)` or `"{}: skipped".format(email)`. Do not use f-strings.
- Write optional types as `X | None`, for example
  `defaults: dict[str, str] | None = None`. Do not use `typing.Optional`.
- Name functions and methods in camelCase, including private helpers:
  `def buildGreeting(...)`, `def _splitHeader(...)`.
- Inside the package, use absolute imports: `from mailmerge.template import render`.
  Do not use relative imports such as `from .template import render`.
- Placeholders are `{{field}}` with lower-case field names. Column names are
  lower-cased when the recipients file is read.
- Read and write text files as UTF-8.
- Give every public function a short docstring.
