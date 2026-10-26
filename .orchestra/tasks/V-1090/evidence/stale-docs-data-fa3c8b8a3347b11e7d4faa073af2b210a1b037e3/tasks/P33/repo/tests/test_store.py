from datetime import date

import pytest

from grantpot.models import Application, Award, Fund
from grantpot.store import append_award, load_applications, load_awards, load_fund


def write(folder, name, text):
    (folder / name).write_text(text, encoding="utf-8")


def test_load_fund(tmp_path):
    write(tmp_path, "fund.txt", "# arts fund\nname = Arts 2026\n\nbudget = 5000.00\n")
    assert load_fund(str(tmp_path)) == Fund("Arts 2026", 500000)


def test_load_fund_needs_budget(tmp_path):
    write(tmp_path, "fund.txt", "name = Arts 2026\n")
    with pytest.raises(ValueError, match="no budget"):
        load_fund(str(tmp_path))


def test_load_fund_rejects_line_without_equals(tmp_path):
    write(tmp_path, "fund.txt", "name = Arts\nbudget 10.00\n")
    with pytest.raises(ValueError, match="line 2"):
        load_fund(str(tmp_path))


def test_load_awards_missing_file_means_none(tmp_path):
    assert load_awards(str(tmp_path)) == []


def test_load_awards(tmp_path):
    write(tmp_path, "awards.csv", "date,recipient,amount\n2026-02-01,Choir,250.00\n2026-03-15,Mural, 99.5\n")
    assert load_awards(str(tmp_path)) == [Award(date(2026, 2, 1), "Choir", 25000),
                                          Award(date(2026, 3, 15), "Mural", 9950)]


def test_load_awards_reports_line(tmp_path):
    write(tmp_path, "awards.csv", "date,recipient,amount\n2026-02-01,Choir,250.00\n2026-13-01,Mural,5\n")
    with pytest.raises(ValueError, match="awards.csv line 3"):
        load_awards(str(tmp_path))


def test_load_applications(tmp_path):
    write(tmp_path, "applications.csv", "applicant,requested\nYouth Band ,1200\nZine Club,80.25\n")
    assert load_applications(str(tmp_path)) == [Application("Youth Band", 120000),
                                                Application("Zine Club", 8025)]


def test_load_applications_reports_line(tmp_path):
    write(tmp_path, "applications.csv", "applicant,requested\nZine Club,lots\n")
    with pytest.raises(ValueError, match="applications.csv line 2"):
        load_applications(str(tmp_path))


def test_append_award_creates_file_with_header(tmp_path):
    append_award(str(tmp_path), Award(date(2026, 4, 1), "Choir", 12345))
    append_award(str(tmp_path), Award(date(2026, 4, 2), "Mural", 500))
    text = (tmp_path / "awards.csv").read_text(encoding="utf-8")
    assert text.splitlines() == ["date,recipient,amount", "2026-04-01,Choir,123.45", "2026-04-02,Mural,5.00"]
    assert len(load_awards(str(tmp_path))) == 2
