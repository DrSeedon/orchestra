import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHART = """size,chest_min,chest_max,waist_min,waist_max,hip_min,hip_max
S,86,94,71,79,88,96
M,94,102,79,87,96,104
L,102,110,87,95,104,112
XL,110,118,95,103,112,120
"""

PEOPLE = """name,chest,waist,hip,unit
Ana,98,83,100,cm
Ben,41,33,40,in
Cleo,90,85,98,cm
Dev,106,76,108,cm
Eve,102,79,96,cm
Finn,92,77,99,cm
"""


def run(*args):
    return subprocess.run([sys.executable, "-m", "sizechart.fit", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, people=PEOPLE):
    chart = tmp_path / "chart.csv"
    chart.write_text(CHART, encoding="utf-8")
    people_file = tmp_path / "people.csv"
    people_file.write_text(people, encoding="utf-8")
    return str(chart), str(people_file)


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_fit_report_for_size_m(tmp_path):
    chart, people = make_inputs(tmp_path)
    out = tmp_path / "fit.csv"
    result = run(chart, people, "M", str(out))
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == [
        "name,chest,waist,hip,fit",
        "Ana,regular,regular,regular,regular",
        "Ben,tight,regular,regular,tight",
        "Cleo,loose,regular,regular,loose",
        "Dev,tight,loose,tight,tight",
        "Eve,regular,regular,regular,regular",
        "Finn,loose,loose,regular,loose",
    ]


def test_fit_report_for_size_l(tmp_path):
    people = ("name,chest,waist,hip,unit\nGus,105,90,108,cm\nHana,40,36,44,in\n"
              "Ivo,112,96,110,cm\nJo,104,94,100,cm\nKai,111,88,103,cm\n")
    chart, people_file = make_inputs(tmp_path, people)
    out = tmp_path / "fit.csv"
    result = run(chart, people_file, "L", str(out))
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == [
        "name,chest,waist,hip,fit",
        "Gus,regular,regular,regular,regular",
        "Hana,loose,regular,regular,loose",
        "Ivo,tight,tight,regular,tight",
        "Jo,regular,regular,loose,loose",
        "Kai,tight,regular,loose,tight",
    ]


def test_no_people_gives_header_only(tmp_path):
    chart, people = make_inputs(tmp_path, "name,chest,waist,hip,unit\n")
    out = tmp_path / "fit.csv"
    result = run(chart, people, "XL", str(out))
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == ["name,chest,waist,hip,fit"]


def test_unknown_size(tmp_path):
    chart, people = make_inputs(tmp_path)
    out = tmp_path / "fit.csv"
    result = run(chart, people, "XXL", str(out))
    assert result.returncode == 2
    assert not out.exists()


def test_bad_people_file(tmp_path):
    chart, people = make_inputs(tmp_path, PEOPLE.replace("Cleo,90,85,98,cm", "Cleo,90,85,98,ft"))
    out = tmp_path / "fit.csv"
    result = run(chart, people, "M", str(out))
    assert result.returncode == 2
    assert not out.exists()
