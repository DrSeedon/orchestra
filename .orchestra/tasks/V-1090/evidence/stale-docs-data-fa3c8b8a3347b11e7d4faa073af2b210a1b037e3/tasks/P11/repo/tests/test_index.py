from notegrep.index import build_index, index_path, load_index, save_index


def test_build_index(notes_dir):
    index = build_index(notes_dir)
    assert index["tomato"] == ["garden", "kitchen"]
    assert index["compost"] == ["bins", "garden"]
    assert "gone" not in index


def test_save_writes_into_notes_folder(notes_dir):
    target = save_index(build_index(notes_dir), notes_dir)
    assert target == index_path(notes_dir)
    assert target.parent == notes_dir


def test_save_and_load_round_trip(notes_dir):
    index = build_index(notes_dir)
    save_index(index, notes_dir)
    assert load_index(notes_dir) == index


def test_load_missing_index_warns(tmp_path, capsys):
    assert load_index(tmp_path) == {}
    assert "no index" in capsys.readouterr().err


def test_load_damaged_index_warns(tmp_path, capsys):
    index_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_index(tmp_path) == {}
    assert "damaged" in capsys.readouterr().err
