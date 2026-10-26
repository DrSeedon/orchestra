"""The playlists of a music folder."""
import os
from typing import Dict, List, Tuple

from playlistr.m3u import Playlist, read_playlist
from playlistr.tracks import Track

PLAYLIST_EXTENSION = ".m3u"


def find_playlists(folder: str) -> List[str]:
    """Return the paths of the playlist files directly in ``folder``, sorted by file name."""
    names = sorted(name for name in os.listdir(folder) if name.lower().endswith(PLAYLIST_EXTENSION))
    paths = [os.path.join(folder, name) for name in names]
    return [path for path in paths if os.path.isfile(path)]


def load_playlists(folder: str) -> Tuple[List[Playlist], Dict[str, str]]:
    """Read every playlist file of ``folder``.

    Returns the playlists that could be read, in file name order, and for each
    file that could not be read its file name and the reason.
    """
    playlists = []
    problems = {}
    for path in find_playlists(folder):
        try:
            playlists.append(read_playlist(path))
        except (OSError, UnicodeDecodeError, ValueError) as err:
            problems[os.path.basename(path)] = str(err)
    return playlists, problems


def missing_tracks(playlist: Playlist) -> List[Track]:
    """Return the tracks whose file does not exist.

    A relative location is taken from the folder of the playlist file.
    """
    base = os.path.dirname(playlist.path)
    return [track for track in playlist.tracks
            if not os.path.isfile(os.path.join(base, track.location))]
