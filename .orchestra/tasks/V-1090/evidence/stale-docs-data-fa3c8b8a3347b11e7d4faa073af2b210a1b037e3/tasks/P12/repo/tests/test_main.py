from decimal import Decimal

import pytest

from payrun.__main__ import main, parseHours

REGISTRY = "# id,name,rate,pension\nE01,Ana Silva,20.00,0.05\nE07,Ben Okafor,22.00,0.00\n"


def writeInputs(folder, hours):
    (folder / "staff.txt").write_text(REGISTRY, encoding="utf-8")
    (folder / "hours.txt").write_text(hours, encoding="utf-8")
    return [str(folder / "staff.txt"), str(folder / "hours.txt"), str(folder / "slips.txt")]


def test_parse_hours():
    assert parseHours(" E01 , 42.5 ") == ("E01", Decimal("42.5"))


@pytest.mark.parametrize("line", ["E01", "E01,forty", ",40"])
def test_parse_hours_rejects(line):
    with pytest.raises(ValueError):
        parseHours(line)


def test_main_writes_payslips(tmp_path):
    args = writeInputs(tmp_path, "E07,10\n# late entry\nE01,42\n")
    assert main(args) == 0
    text = (tmp_path / "slips.txt").read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    assert [b.splitlines()[0] for b in blocks] == ["Ben Okafor (E07)", "Ana Silva (E01)"]
    assert "net          695.00" in blocks[1]


def test_main_unknown_employee(tmp_path):
    args = writeInputs(tmp_path, "E01,40\nE99,12\n")
    assert main(args) == 2
    assert not (tmp_path / "slips.txt").exists()


def test_main_missing_hours_file(tmp_path):
    args = writeInputs(tmp_path, "")
    (tmp_path / "hours.txt").unlink()
    assert main(args) == 2
