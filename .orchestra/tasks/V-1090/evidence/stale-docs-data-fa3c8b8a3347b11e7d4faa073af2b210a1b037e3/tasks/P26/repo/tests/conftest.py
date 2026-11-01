import pytest


@pytest.fixture
def write_file(tmp_path):
    """Return a helper that writes a text file under tmp_path and returns its path."""

    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
