import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GEO = """\
[geo-1]
question = What is the capital of France?
choices = Berlin; Paris; Rome
answer = B

[geo-2]
question = Which river is the longest?
choices = Nile; Amazon; Danube; Rhine
answer = A
points = 2
"""

HIST = """\
[hist-1]
question = When did the Berlin Wall fall?
choices = 1979; 1989; 1999
answer = b
points = 3
"""

SHEETS = {
    "ann.txt": "geo-1: B\ngeo-2: a\nhist-1: C\n",
    "ben.txt": "# Week 3\ngeo-1:\n  geo-2 :  D \nmath-9: A\nhist-1: B\nnonsense line\n\n",
    "cara.txt": "hist-1: b\nhist-1: A\n",
    "notes.md": "geo-1: B\n",
}


def write_files(folder, files):
    os.makedirs(folder, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as handle:
            handle.write(text)


def make_banks(root):
    banks = os.path.join(root, "banks")
    write_files(banks, {"geo.ini": GEO, "hist.ini": HIST})
    return banks


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "quizgen.grade", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def test_grades_every_sheet(tmp_path):
    root = str(tmp_path)
    banks = make_banks(root)
    sheets = os.path.join(root, "sheets")
    write_files(sheets, SHEETS)
    output = os.path.join(root, "results", "week3", "grades.csv")
    result = run(banks, sheets, output)
    assert result.returncode == 0, result.stderr
    with open(output, encoding="utf-8", newline="") as handle:
        lines = [line.rstrip("\r\n") for line in handle]
    assert lines == [
        "student,score,possible,correct,wrong,blank,unknown",
        "ann,3,6,2,1,0,0",
        "ben,3,6,1,1,1,2",
        "cara,3,3,1,0,0,1",
    ]


def test_missing_sheets_folder_exits_2(tmp_path):
    root = str(tmp_path)
    banks = make_banks(root)
    output = os.path.join(root, "out", "grades.csv")
    result = run(banks, os.path.join(root, "missing"), output)
    assert result.returncode == 2
    assert not os.path.exists(os.path.join(root, "out"))


def test_sheets_folder_without_sheets_exits_2(tmp_path):
    root = str(tmp_path)
    banks = make_banks(root)
    sheets = os.path.join(root, "sheets")
    write_files(sheets, {"notes.md": "geo-1: B\n"})
    output = os.path.join(root, "grades.csv")
    result = run(banks, sheets, output)
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_missing_banks_folder_exits_2(tmp_path):
    root = str(tmp_path)
    sheets = os.path.join(root, "sheets")
    write_files(sheets, {"ann.txt": SHEETS["ann.txt"]})
    output = os.path.join(root, "grades.csv")
    result = run(os.path.join(root, "banks"), sheets, output)
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_invalid_bank_exits_2(tmp_path):
    root = str(tmp_path)
    banks = os.path.join(root, "banks")
    write_files(banks, {"geo.ini": GEO.replace("answer = B", "answer = F")})
    sheets = os.path.join(root, "sheets")
    write_files(sheets, {"ann.txt": SHEETS["ann.txt"]})
    output = os.path.join(root, "grades.csv")
    result = run(banks, sheets, output)
    assert result.returncode == 2
    assert not os.path.exists(output)
