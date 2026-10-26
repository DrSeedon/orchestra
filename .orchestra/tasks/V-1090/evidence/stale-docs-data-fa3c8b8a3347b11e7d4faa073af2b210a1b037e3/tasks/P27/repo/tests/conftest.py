import pytest

TENANTS = (
    "unit,name,rent,since\n"
    "2A,Cora Diaz,1100.00,2025-01-01\n"
    "1A,Ana Ruiz,1250.50,2024-03-01\n"
    "1B,Ben Cole,980,2023-09-15\n"
)

LEDGER = (
    "date,unit,kind,amount\n"
    "2026-09-01,1A,charge,1250.50\n"
    "2026-09-03,1A,payment,1250.50\n"
    "2026-09-01,1B,charge,980.00\n"
    "2026-09-12,1B,payment,500\n"
    "2026-09-01,2A,charge,1100.00\n"
    "2026-09-02,2A,payment,1100.00\n"
    "2026-09-20,2A,credit,40.00\n"
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
def sample_files(write_file):
    """Write the sample tenants and ledger files and return their paths."""
    return write_file("tenants.csv", TENANTS), write_file("ledger.csv", LEDGER)
