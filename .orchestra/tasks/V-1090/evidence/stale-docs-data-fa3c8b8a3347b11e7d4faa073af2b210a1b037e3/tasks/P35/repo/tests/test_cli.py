import os

from playlistr.cli import main


def write(path, text):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text)


def make_folder(tmp_path):
    os.mkdir(str(tmp_path / "music"))
    write(tmp_path / "music" / "words.mp3", "")
    write(tmp_path / "chill.m3u", "#EXTM3U\n#EXTINF:200,Low - Words\nmusic/words.mp3\n"
          "#EXTINF:3600,Eno - Thursday Afternoon\nmusic/thursday.mp3\n")
    write(tmp_path / "broken.m3u", "music/words.mp3\n")
    return str(tmp_path)


def test_list_shows_playlists_and_skips_broken(tmp_path, capsys):
    folder = make_folder(tmp_path)
    assert main(["list", folder]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("skipped broken.m3u:")
    assert out[1] == "chill: 2 tracks, 1:03:20"


def test_check_finds_missing_files(tmp_path, capsys):
    folder = make_folder(tmp_path)
    assert main(["check", folder]) == 1
    out = capsys.readouterr().out
    assert "chill: missing music/thursday.mp3 (Eno - Thursday Afternoon)" in out
    assert "words.mp3 (" not in out


def test_check_passes_when_all_files_exist(tmp_path):
    os.mkdir(str(tmp_path / "music"))
    write(tmp_path / "music" / "words.mp3", "")
    write(tmp_path / "chill.m3u", "#EXTM3U\nmusic/words.mp3\n")
    assert main(["check", str(tmp_path)]) == 0


def test_missing_folder_exits_2(tmp_path, capsys):
    assert main(["list", str(tmp_path / "nope")]) == 2
    assert "not a folder" in capsys.readouterr().err
