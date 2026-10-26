import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args):
    return subprocess.run([sys.executable, "-m", "playlistr.merge", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_json(path):
    with open(str(path), encoding="utf-8") as fh:
        return json.load(fh)


def test_merges_playlists_in_file_name_order(tmp_path):
    folder = tmp_path / "lists"
    write(folder / "road.m3u", "#EXTM3U\n#EXTINF:201,LOW - words\nother/words.flac\n"
          "#EXTINF:180,Nina Simone - Feeling Good\nnina.mp3\n"
          "#EXTINF:180,Nina Simone - Feeling Good\nnina.mp3\n")
    write(folder / "chill.m3u", "#EXTM3U\n#EXTINF:200,Low - Words\nmusic/words.mp3\n"
          "#EXTINF:-1,Eno - Thursday Afternoon\nmusic/thursday.mp3\n"
          "music/misc/Untitled.flac\n")
    write(folder / "broken.m3u", "music/words.mp3\n")
    write(folder / "notes.txt", "not a playlist\n")
    out = tmp_path / "merged.json"
    r = run(str(folder), str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "tracks": [
            {"artist": "Low", "title": "Words", "seconds": 200, "file": "music/words.mp3",
             "playlists": ["chill", "road"]},
            {"artist": "Eno", "title": "Thursday Afternoon", "seconds": None,
             "file": "music/thursday.mp3", "playlists": ["chill"]},
            {"artist": "", "title": "Untitled", "seconds": None, "file": "music/misc/Untitled.flac",
             "playlists": ["chill"]},
            {"artist": "Nina Simone", "title": "Feeling Good", "seconds": 180, "file": "nina.mp3",
             "playlists": ["road"]},
        ],
        "playlists": ["chill", "road"],
        "skipped": ["broken.m3u"],
        "dropped": 2,
        "seconds": 380,
    }


def test_creates_output_folder_and_keeps_empty_playlists(tmp_path):
    folder = tmp_path / "lists"
    write(folder / "a.m3u", "#EXTM3U\n#EXTINF:100,Air - La Femme d'Argent\nair/femme.mp3\n"
          "#EXTINF:300,Air - Talisman\nair/talisman.mp3\n")
    write(folder / "b.m3u", "#EXTM3U\n")
    write(folder / "c.m3u", "#EXTM3U\n#EXTINF:301,air - TALISMAN\ntalisman.ogg\n"
          "#EXTINF:100,Air - La Femme d'Argent\nair/femme.mp3\n#EXTINF:50,Air - Venus\nvenus.mp3\n")
    out = tmp_path / "out" / "deep" / "merged.json"
    r = run(str(folder), str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    data = read_json(out)
    assert data["playlists"] == ["a", "b", "c"]
    assert data["skipped"] == []
    assert data["dropped"] == 2
    assert data["seconds"] == 450
    assert [(t["title"], t["seconds"], t["file"], t["playlists"]) for t in data["tracks"]] == [
        ("La Femme d'Argent", 100, "air/femme.mp3", ["a", "c"]),
        ("Talisman", 300, "air/talisman.mp3", ["a", "c"]),
        ("Venus", 50, "venus.mp3", ["c"]),
    ]


def test_missing_folder_exits_2(tmp_path):
    out = tmp_path / "merged.json"
    r = run(str(tmp_path / "nope"), str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_no_readable_playlist_exits_2(tmp_path):
    folder = tmp_path / "lists"
    write(folder / "broken.m3u", "song.mp3\n")
    write(folder / "bad.m3u", "#EXTM3U\n#EXTINF:x,Low - Words\nwords.mp3\n")
    write(folder / "notes.txt", "#EXTM3U\nsong.mp3\n")
    out = tmp_path / "merged.json"
    r = run(str(folder), str(out))
    assert r.returncode == 2
    assert not out.exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run(str(empty), str(out))
    assert r.returncode == 2
    assert not out.exists()
