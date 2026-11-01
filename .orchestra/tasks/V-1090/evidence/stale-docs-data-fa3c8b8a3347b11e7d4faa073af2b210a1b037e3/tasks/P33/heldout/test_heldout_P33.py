import csv
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args):
    return subprocess.run([sys.executable, "-m", "grantpot.allocate", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_fund(folder, budget, awards, applications):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "fund.txt"), "w", encoding="utf-8") as fh:
        fh.write("name = Test Fund\nbudget = %s\n" % budget)
    if awards is not None:
        with open(os.path.join(folder, "awards.csv"), "w", encoding="utf-8", newline="") as fh:
            fh.write("date,recipient,amount\n")
            for i, amount in enumerate(awards, start=1):
                fh.write("2026-01-%02d,Past %d,%s\n" % (i, i, amount))
    with open(os.path.join(folder, "applications.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("applicant,requested\n")
        for name, amount in applications:
            fh.write("%s,%s\n" % (name, amount))
    return str(folder)


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [row for row in csv.reader(fh) if row]


def test_shares_in_proportion_and_gives_the_rest_by_fraction(tmp_path):
    fund = make_fund(tmp_path / "fund", "1500.00", ["300.00", "200.00"],
                     [("Ana", "600.00"), ("Ben", "300"), ("Cy", "300.00"), ("Dee", "150.0")])
    out = str(tmp_path / "out.csv")
    r = run(fund, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_rows(out) == [
        ["applicant", "requested", "allocated"],
        ["Ana", "600.00", "444.45"],
        ["Ben", "300.00", "222.22"],
        ["Cy", "300.00", "222.22"],
        ["Dee", "150.00", "111.11"],
        ["total", "1350.00", "1000.00"],
    ]


def test_rest_goes_to_largest_fraction_then_file_order(tmp_path):
    fund = make_fund(tmp_path / "a", "1.00", None, [("P", "1.00"), ("Q", "2.00"), ("R", "4.00")])
    out = str(tmp_path / "a.csv")
    r = run(fund, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_rows(out)[1:] == [["P", "1.00", "0.14"], ["Q", "2.00", "0.29"], ["R", "4.00", "0.57"],
                                  ["total", "7.00", "1.00"]]
    fund = make_fund(tmp_path / "b", "1.00", [], [("X", "3.00"), ("Y", "3.00"), ("Z", "3.00")])
    out = str(tmp_path / "nested" / "dir" / "b.csv")
    r = run(fund, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_rows(out)[1:] == [["X", "3.00", "0.34"], ["Y", "3.00", "0.33"], ["Z", "3.00", "0.33"],
                                  ["total", "9.00", "1.00"]]


def test_full_requests_when_money_covers_them(tmp_path):
    fund = make_fund(tmp_path / "fund", "500.00", ["100.00"],
                     [("Choir", "120.5"), ("Mural", "79.50")])
    out = str(tmp_path / "out.csv")
    r = run(fund, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_rows(out) == [
        ["applicant", "requested", "allocated"],
        ["Choir", "120.50", "120.50"],
        ["Mural", "79.50", "79.50"],
        ["total", "200.00", "200.00"],
    ]


def test_nothing_left_gives_zero(tmp_path):
    fund = make_fund(tmp_path / "fund", "100.00", ["80.00", "40.00"], [("Choir", "10.00"), ("Mural", "5.00")])
    out = str(tmp_path / "out.csv")
    r = run(fund, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_rows(out)[1:] == [["Choir", "10.00", "0.00"], ["Mural", "5.00", "0.00"],
                                  ["total", "15.00", "0.00"]]


@pytest.mark.parametrize("applications", [
    [("Choir", "10.00"), ("Mural", "0.00")],
    [("Choir", "10.00"), ("Mural", "5.00"), ("Choir", "2.00")],
    [("Choir", "10.00"), ("Mural", "five")],
])
def test_bad_applications_exit_2(tmp_path, applications):
    fund = make_fund(tmp_path / "fund", "100.00", None, applications)
    out = str(tmp_path / "out.csv")
    r = run(fund, out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)


def test_missing_fund_file_exits_2(tmp_path):
    folder = tmp_path / "fund"
    make_fund(folder, "100.00", None, [("Choir", "10.00")])
    os.remove(os.path.join(str(folder), "fund.txt"))
    out = str(tmp_path / "out.csv")
    r = run(str(folder), out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)
