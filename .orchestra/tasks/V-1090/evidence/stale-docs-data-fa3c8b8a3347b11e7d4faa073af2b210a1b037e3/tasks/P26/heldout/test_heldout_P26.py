import csv
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATE = "Your order {{order}} ships to {{city}}.\nThank you.\n\n"

RECIPIENTS = (
    "email,name,order,city\n"
    "ann@example.com,Ann Lee,A-1,Oslo\n"
    "bad-address,Bob,A-2,Rome\n"
    "noname@example.com,,A-3,Paris\n"
    "cy@example.com,Cy,A-4,\n"
    "ANN@example.com,Ann Again,A-5,Bergen\n"
    "dee@example.com, Dee ,A-6,Lima\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "mailmerge.letters", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_index(folder):
    with open(os.path.join(folder, "index.csv"), encoding="utf-8", newline="") as fh:
        return [row for row in csv.reader(fh) if row]


def make_input(tmp_path, recipients=RECIPIENTS):
    template = str(tmp_path / "letter.txt")
    people = str(tmp_path / "people.csv")
    write(template, TEMPLATE)
    write(people, recipients)
    return template, people


def test_letters_with_fallback_greeting(tmp_path):
    template, people = make_input(tmp_path)
    out = str(tmp_path / "out")
    r = run(template, people, out, "--greeting", "Dear customer,")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_index(out) == [
        ["file", "email"],
        ["letter-001.txt", "ann@example.com"],
        ["letter-002.txt", "noname@example.com"],
        ["letter-003.txt", "dee@example.com"],
    ]
    assert read(os.path.join(out, "letter-001.txt")) == (
        "Dear Ann Lee,\n\nYour order A-1 ships to Oslo.\nThank you.\n")
    assert read(os.path.join(out, "letter-002.txt")) == (
        "Dear customer,\n\nYour order A-3 ships to Paris.\nThank you.\n")
    assert read(os.path.join(out, "letter-003.txt")) == (
        "Dear Dee,\n\nYour order A-6 ships to Lima.\nThank you.\n")
    assert sorted(os.listdir(out)) == ["index.csv", "letter-001.txt", "letter-002.txt",
                                       "letter-003.txt"]


def test_letters_without_fallback_skip_unnamed(tmp_path):
    template, people = make_input(tmp_path)
    out = str(tmp_path / "new" / "out")
    r = run(template, people, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_index(out) == [
        ["file", "email"],
        ["letter-001.txt", "ann@example.com"],
        ["letter-002.txt", "dee@example.com"],
    ]
    assert read(os.path.join(out, "letter-002.txt")) == (
        "Dear Dee,\n\nYour order A-6 ships to Lima.\nThank you.\n")
    assert not os.path.exists(os.path.join(out, "letter-003.txt"))


def test_no_name_column_uses_fallback(tmp_path):
    template, people = make_input(tmp_path, "email,order,city\nzed@example.com,Z-9,Rome\n")
    out = str(tmp_path / "out")
    r = run(template, people, out, "--greeting", "Hello,")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read(os.path.join(out, "letter-001.txt")) == (
        "Hello,\n\nYour order Z-9 ships to Rome.\nThank you.\n")


def test_index_written_when_no_letters(tmp_path):
    template, people = make_input(tmp_path, "email,name,order,city\nzed@example.com,,Z-9,Rome\n")
    out = str(tmp_path / "out")
    r = run(template, people, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_index(out) == [["file", "email"]]
    assert os.listdir(out) == ["index.csv"]


def test_missing_template(tmp_path):
    _, people = make_input(tmp_path)
    out = str(tmp_path / "out")
    r = run(str(tmp_path / "nope.txt"), people, out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_missing_recipients(tmp_path):
    template, _ = make_input(tmp_path)
    out = str(tmp_path / "out")
    r = run(template, str(tmp_path / "nope.csv"), out, "--greeting", "Hi,")
    assert r.returncode == 2
    assert not os.path.exists(out)
