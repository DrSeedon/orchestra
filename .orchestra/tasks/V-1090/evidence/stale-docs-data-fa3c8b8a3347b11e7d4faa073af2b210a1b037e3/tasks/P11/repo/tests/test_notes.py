import pytest

from notegrep.notes import find_notes, load_notes, note_name, read_note


def test_find_notes_skips_hidden_and_other_files(notes_dir):
    names = [p.name for p in find_notes(notes_dir)]
    assert names == ["bins.md", "garden.md", "kitchen.md"]


def test_find_notes_needs_a_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        find_notes(tmp_path / "missing")


def test_note_name_drops_suffix(tmp_path):
    assert note_name(tmp_path / "archive" / "bins.md") == "bins"


def test_read_note_bad_encoding_is_skipped(tmp_path, capsys):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00broken")
    assert read_note(bad) is None
    assert "skipping" in capsys.readouterr().err


def test_note_title_falls_back_to_name(notes_dir):
    notes = {n.name: n for n in load_notes(notes_dir)}
    assert notes["garden"].title == "Garden"
    assert notes["bins"].title == "bins"
