import os

from playlistr.library import find_playlists, load_playlists, missing_tracks


def write(path, text):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text)


def test_find_playlists_sorted_and_filtered(tmp_path):
    write(tmp_path / "road.m3u", "#EXTM3U\n")
    write(tmp_path / "Chill.M3U", "#EXTM3U\n")
    write(tmp_path / "notes.txt", "hello\n")
    os.mkdir(str(tmp_path / "old.m3u"))
    names = [os.path.basename(path) for path in find_playlists(str(tmp_path))]
    assert names == ["Chill.M3U", "road.m3u"]


def test_load_playlists_reports_broken_files(tmp_path):
    write(tmp_path / "a.m3u", "#EXTM3U\n#EXTINF:10,Low - Words\nwords.mp3\n")
    write(tmp_path / "b.m3u", "words.mp3\n")
    write(tmp_path / "c.m3u", "#EXTM3U\n#EXTINF:x,Low - Words\nwords.mp3\n")
    playlists, problems = load_playlists(str(tmp_path))
    assert [playlist.name for playlist in playlists] == ["a"]
    assert sorted(problems) == ["b.m3u", "c.m3u"]
    assert "#EXTM3U" in problems["b.m3u"]


def test_load_playlists_empty_folder(tmp_path):
    assert load_playlists(str(tmp_path)) == ([], {})


def test_missing_tracks_uses_playlist_folder(tmp_path):
    os.mkdir(str(tmp_path / "music"))
    write(tmp_path / "music" / "here.mp3", "")
    write(tmp_path / "mix.m3u", "#EXTM3U\nmusic/here.mp3\nmusic/gone.mp3\n")
    playlists, _ = load_playlists(str(tmp_path))
    assert [track.location for track in missing_tracks(playlists[0])] == ["music/gone.mp3"]
