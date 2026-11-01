# playlistr

playlistr manages the M3U playlists of a music folder. It reads extended M3U
files, lists the playlists with their length and finds tracks whose music
file is missing.

## Layout

- `playlistr/tracks.py` - the track record and helpers to show tracks and lengths
- `playlistr/m3u.py` - reads and writes extended M3U text and playlist files
- `playlistr/library.py` - finds and loads the playlists of a folder
- `playlistr/cli.py` - the command line (list, check)
- `tests/` - pytest tests, one file per module

A playlist file ends in `.m3u` (any case) and is UTF-8 text. Its first line is
`#EXTM3U`. Each track is a location line, usually after a line like
`#EXTINF:215,Nina Simone - Feeling Good`. The number is the length in seconds;
-1 means the length is unknown. A file without the `#EXTM3U` line, or with a
length that is not a number, cannot be read and is skipped.

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

## Usage

```
python -m playlistr.cli list FOLDER
python -m playlistr.cli check FOLDER
```

`check` exits with status 1 when a track file is missing. Both commands exit
with status 2 when FOLDER is not a folder.

## Conventions

- Standard library only. pytest is the only development dependency.
- Records are dataclasses, for example
  `@dataclass(frozen=True)` on `class Track` with typed fields.
- Function and method names are camelCase, for example
  `def loadPlaylists(folder: str)` and `def formatDuration(seconds: int)`.
- Work with file system paths through `pathlib.Path`, for example
  `Path(folder).iterdir()` and `Path(out).parent.mkdir(parents=True, exist_ok=True)`.
- Write container types with the builtin generics, for example
  `def findPlaylists(folder: str) -> list[str]` and `dict[str, str]`.
- Messages for the user go through `logging`. Each module has
  `logger = logging.getLogger(__name__)` and calls `logger.info(...)` or
  `logger.warning(...)`; the command line sets up `logging.basicConfig`.
- Track locations stay as written in the playlist. A relative location is
  taken from the folder of the playlist file.
- Lengths are whole seconds in an `int`.
- Tests that need files create them under pytest's `tmp_path`.
