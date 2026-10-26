import pytest

READINGS = (
    "time,sensor,value\n"
    "2026-10-01T08:10:00,boiler,64.0\n"
    "2026-10-01T08:00:00,boiler,61.5\n"
    "2026-10-01T08:00:00,cellar,11.0\n"
    "2026-10-01T08:20:00,boiler,66.5\n"
    "2026-10-01T09:30:00,boiler,60.0\n"
    "2026-10-01T08:30:00,cellar,12.0\n"
    "2026-10-01T08:00:00,attic,19.0\n"
    "noon,attic,20.0\n"
)


@pytest.fixture
def write_file(tmp_path):
    """Return a helper that writes a text file under tmp_path and returns its path as text."""

    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    return _write


@pytest.fixture
def readings_file(write_file):
    """Write the sample readings file and return its path."""
    return write_file("readings.csv", READINGS)
