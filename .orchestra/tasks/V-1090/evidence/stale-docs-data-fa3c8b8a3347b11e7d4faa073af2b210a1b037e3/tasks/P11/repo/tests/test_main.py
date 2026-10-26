from notegrep.__main__ import main
from notegrep.index import index_path


def test_build_writes_index(notes_dir, capsys):
    assert main(["build", str(notes_dir)]) == 0
    assert index_path(notes_dir).exists()
    assert "indexed" in capsys.readouterr().out


def test_search_all_words(notes_dir, capsys):
    main(["build", str(notes_dir)])
    capsys.readouterr()
    assert main(["search", str(notes_dir), "tomato", "soup"]) == 0
    assert capsys.readouterr().out.split() == ["kitchen"]


def test_search_any_word(notes_dir, capsys):
    main(["build", str(notes_dir)])
    capsys.readouterr()
    assert main(["search", str(notes_dir), "compost", "recipe", "--any"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["bins\t1", "garden\t1", "kitchen\t1"]


def test_search_without_match(notes_dir, capsys):
    main(["build", str(notes_dir)])
    assert main(["search", str(notes_dir), "pepper"]) == 1


def test_missing_folder(tmp_path, capsys):
    assert main(["build", str(tmp_path / "missing")]) == 2
    assert "not a folder" in capsys.readouterr().err
