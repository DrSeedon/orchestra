"""Read and write extended M3U playlists.

A playlist starts with ``#EXTM3U``. Each track is a location line, usually after
an ``#EXTINF:<seconds>,<artist> - <title>`` line. Other ``#`` lines are ignored.
"""
import os
from typing import List, NamedTuple, Optional, Tuple

from playlistr.tracks import Track, display_name

HEADER = "#EXTM3U"
INFO_PREFIX = "#EXTINF:"


class Playlist(NamedTuple):
    """A playlist file: its name (the file name without extension), path and tracks."""

    name: str
    path: str
    tracks: List[Track]


def parse_info(line: str) -> Tuple[int, str, str]:
    """Read an ``#EXTINF`` line into seconds, artist and title."""
    length_text, _, label = line[len(INFO_PREFIX):].partition(",")
    try:
        seconds = int(length_text.strip())
    except ValueError:
        raise ValueError(f"bad length in {line!r}") from None
    artist, sep, title = label.partition(" - ")
    if not sep:
        return seconds, "", label.strip()
    return seconds, artist.strip(), title.strip()


def title_from_location(location: str) -> str:
    """Return the file name of a location without its extension."""
    return os.path.splitext(os.path.basename(location))[0]


def parse_m3u(text: str) -> List[Track]:
    """Read the tracks of an extended M3U text, in order."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != HEADER:
        raise ValueError(f"the first line must be {HEADER}")
    tracks = []
    info: Optional[Tuple[int, str, str]] = None
    for line in lines[1:]:
        if line.startswith(INFO_PREFIX):
            info = parse_info(line)
        elif line.startswith("#"):
            continue
        elif info is None:
            tracks.append(Track(line, "", title_from_location(line), -1))
        else:
            seconds, artist, title = info
            tracks.append(Track(line, artist, title, seconds))
            info = None
    return tracks


def playlist_name(path: str) -> str:
    """Return the name of a playlist file: its file name without extension."""
    return os.path.splitext(os.path.basename(path))[0]


def read_playlist(path: str) -> Playlist:
    """Read one playlist file."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return Playlist(playlist_name(path), path, parse_m3u(text))


def format_m3u(tracks: List[Track]) -> str:
    """Write tracks as extended M3U text."""
    lines = [HEADER]
    for track in tracks:
        lines.append(f"{INFO_PREFIX}{track.seconds},{display_name(track)}")
        lines.append(track.location)
    return "\n".join(lines) + "\n"


def write_playlist(path: str, tracks: List[Track]) -> None:
    """Write tracks to a playlist file."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(format_m3u(tracks))
