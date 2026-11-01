import pytest

from playlistr.m3u import format_m3u, parse_m3u, playlist_name, read_playlist, write_playlist
from playlistr.tracks import Track, display_name, format_duration, total_seconds

SAMPLE = """#EXTM3U
#EXTINF:215,Nina Simone - Feeling Good
music/nina/feeling_good.mp3

#EXTINF:-1,Radio Intro
music/intro.mp3
#PLAYLIST:ignored
music/misc/Untitled Track.flac
"""


def test_parse_reads_info_and_locations():
    tracks = parse_m3u(SAMPLE)
    assert tracks == [
        Track("music/nina/feeling_good.mp3", "Nina Simone", "Feeling Good", 215),
        Track("music/intro.mp3", "", "Radio Intro", -1),
        Track("music/misc/Untitled Track.flac", "", "Untitled Track", -1),
    ]


def test_parse_strips_spaces_around_artist_and_title():
    tracks = parse_m3u("#EXTM3U\n#EXTINF: 90 ,  Low  -  Words \na.mp3\n")
    assert tracks == [Track("a.mp3", "Low", "Words", 90)]


def test_parse_needs_header():
    with pytest.raises(ValueError):
        parse_m3u("song.mp3\n")
    with pytest.raises(ValueError):
        parse_m3u("")


def test_parse_rejects_bad_length():
    with pytest.raises(ValueError):
        parse_m3u("#EXTM3U\n#EXTINF:abc,Low - Words\na.mp3\n")


def test_format_and_parse_round_trip():
    tracks = parse_m3u(SAMPLE)
    assert parse_m3u(format_m3u(tracks)) == tracks


def test_read_and_write_playlist(tmp_path):
    path = str(tmp_path / "Road Trip.m3u")
    tracks = [Track("a.mp3", "Low", "Words", 90), Track("b.mp3", "", "b", -1)]
    write_playlist(path, tracks)
    playlist = read_playlist(path)
    assert playlist.name == "Road Trip"
    assert playlist.path == path
    assert playlist.tracks == tracks


def test_playlist_name():
    assert playlist_name("lists/chill.m3u") == "chill"
    assert playlist_name("MIX.M3U") == "MIX"


def test_display_name():
    assert display_name(Track("a.mp3", "Low", "Words", 90)) == "Low - Words"
    assert display_name(Track("a.mp3", "", "Words", 90)) == "Words"


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(215) == "3:35"
    assert format_duration(3725) == "1:02:05"


def test_total_seconds_skips_unknown_lengths():
    tracks = [Track("a", "", "a", 100), Track("b", "", "b", -1), Track("c", "", "c", 20)]
    assert total_seconds(tracks) == 120
    assert total_seconds([]) == 0
