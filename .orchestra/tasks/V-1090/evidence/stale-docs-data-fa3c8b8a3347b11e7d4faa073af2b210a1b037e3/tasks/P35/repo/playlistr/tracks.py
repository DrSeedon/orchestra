"""Tracks of a playlist and helpers to describe them."""
from typing import List, NamedTuple


class Track(NamedTuple):
    """One entry of a playlist. ``seconds`` is -1 when the length is unknown."""

    location: str
    artist: str
    title: str
    seconds: int


def display_name(track: Track) -> str:
    """Return ``Artist - Title``, or the title alone when the artist is unknown."""
    if track.artist:
        return f"{track.artist} - {track.title}"
    return track.title


def format_duration(seconds: int) -> str:
    """Write a duration as ``m:ss``, or as ``h:mm:ss`` from one hour on."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def total_seconds(tracks: List[Track]) -> int:
    """Return the length of all tracks; a track of unknown length counts as 0."""
    return sum(track.seconds for track in tracks if track.seconds > 0)
