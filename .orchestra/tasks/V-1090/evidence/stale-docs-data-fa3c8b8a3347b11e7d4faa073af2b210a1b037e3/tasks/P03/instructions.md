# linkcheck

linkcheck finds broken links in a folder of markdown and HTML documents, such
as a documentation site before it is published. It extracts every link, checks
that local targets exist on disk and that external URLs are well formed, and
collects the problems into a sorted report. It never makes a network request.

## Layout

- `linkcheck/extract.py` - finds links in markdown (inline, reference, autolink) and HTML
- `linkcheck/validate.py` - classifies targets, checks URL syntax and local files
- `linkcheck/scanner.py` - walks a folder and collects problems per document
- `linkcheck/report.py` - formats problems and the summary line
- `tests/` - pytest tests, one file per module

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Conventions

- Standard library only. The checker never touches the network: external URLs
  are checked for syntax only.
- Handle file system paths with `os.path` (`os.path.join`, `os.path.dirname`,
  `os.path.isfile`) and pass paths around as plain strings. Do not use `pathlib`.
- Functions that can fail do not raise. They return a pair: `(result, None)` on
  success and `(None, "reason")` on failure. A check with no result returns
  `(True, None)` or `(False, "reason")`. The caller decides what to do with the
  reason.
- Build messages and other strings with `str.format()`, for example
  `"{}:{}: {}".format(path, line, message)`. Do not use f-strings or `%`.
- Every public function has a Google-style docstring: a one-line summary, then
  `Args:` and `Returns:` sections.
- Every function in `linkcheck/` has type annotations.
- Document types are decided by file suffix only (`.md`, `.markdown`, `.html`,
  `.htm`).
- The scan never enters the `.git`, `node_modules` and `_build` folders.
- Tests create their fixture documents under pytest's `tmp_path`.
