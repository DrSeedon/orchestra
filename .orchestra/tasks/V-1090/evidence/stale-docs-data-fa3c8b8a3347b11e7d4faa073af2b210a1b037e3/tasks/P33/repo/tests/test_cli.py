import pytest

from grantpot.cli import main


@pytest.fixture
def fund_dir(tmp_path):
    (tmp_path / "fund.txt").write_text("name = Arts 2026\nbudget = 500.00\n", encoding="utf-8")
    (tmp_path / "awards.csv").write_text("date,recipient,amount\n2026-01-05,Choir,120.00\n",
                                         encoding="utf-8")
    return tmp_path


def test_status(fund_dir, capsys):
    assert main(["status", str(fund_dir)]) == 0
    out = capsys.readouterr().out
    assert "awarded: 120.00 in 1 awards" in out
    assert "remaining: 380.00" in out


def test_award_appends_row(fund_dir, capsys):
    assert main(["award", str(fund_dir), "Mural", "80.5", "--date", "2026-02-01"]) == 0
    assert capsys.readouterr().out == "awarded 80.50 to Mural\n"
    rows = (fund_dir / "awards.csv").read_text(encoding="utf-8").splitlines()
    assert rows[-1] == "2026-02-01,Mural,80.50"


def test_award_more_than_left_exits_2(fund_dir, capsys):
    assert main(["award", str(fund_dir), "Mural", "380.01", "--date", "2026-02-01"]) == 2
    assert "more than the 380.00 left" in capsys.readouterr().err


def test_missing_fund_file_exits_2(tmp_path, capsys):
    assert main(["status", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("error:")
