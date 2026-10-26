import os

import pytest


@pytest.fixture
def write_file(tmp_path):
    """Return a helper that writes a text file under tmp_path and returns its path."""
    folder = str(tmp_path)

    def _write(name, text):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    return _write
