import pytest


@pytest.fixture
def notes_dir(tmp_path):
    """A small notes folder with a sub-folder, a hidden folder and a non-note file."""
    (tmp_path / "garden.md").write_text("# Garden\nTomato beds and compost.", encoding="utf-8")
    (tmp_path / "kitchen.md").write_text("# Kitchen\nTomato soup recipe.", encoding="utf-8")
    sub = tmp_path / "archive"
    sub.mkdir()
    (sub / "bins.md").write_text("Compost bins, 2019.", encoding="utf-8")
    hidden = tmp_path / ".trash"
    hidden.mkdir()
    (hidden / "gone.md").write_text("Tomato", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("not a note", encoding="utf-8")
    return tmp_path
