# photosort

photosort helps us keep the shared photo archive tidy. It finds the photos in
a folder tree, reads the day each photo was taken from its file name (camera
names such as `IMG_20240315_101500.jpg` and exported names such as
`2024-01-05 08.00.00.png`) and finds copies with identical content. The
catalog command writes all of this to one CSV file.

## Layout

- `photosort/naming.py` - recognises photo extensions and reads the day from a file name
- `photosort/scan.py` - walks a folder tree and collects `PhotoFile` records
- `photosort/dedupe.py` - groups photos with identical content by SHA-1 digest
- `photosort/catalog.py` - the catalog command: writes one CSV row per photo
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
python -m photosort.catalog SOURCE OUTPUT_CSV
```

The catalog has the columns `path,size,taken,duplicate_of`, one row per photo,
sorted by path. Paths are written inside SOURCE with `/` as separator. The
command exits with status 2 when SOURCE is not a folder.

## Conventions

- Tell the user what happens with plain `print()` calls, for example
  `print(f"skipped {photo.relpath}: no date")`. Do not set up loggers or use
  the `logging` module.
- Handle file system paths with `pathlib.Path`. Build paths with the `/`
  operator and use `Path` methods (`exists()`, `mkdir()`, `iterdir()`).
  Do not use `os.path` or `os.makedirs`.
- Define record types as `typing.NamedTuple` classes, for example
  `class PhotoFile(NamedTuple): path: str`. Do not use dataclasses.
- Annotate collections with the built-in generic types: `list[PhotoFile]`,
  `dict[str, int]`, `set[str]`. Do not use `List` or `Dict` from `typing`.
- Test files live in `tests/` and are named `test_<module>.py`, for example
  `tests/test_scan.py`.
- Standard library only. pytest is the only development dependency.
- Use `Optional[...]` for values that may be missing, such as the day of a
  photo whose name holds no date.
- Never change or delete a file in the scanned folder unless a command is
  meant to do exactly that.
