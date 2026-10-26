import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OLD = """sku,name,price
A-100,Desk lamp,20.00
A-200,Office chair,149.00
B-310,Paper ream,4.80
B-320,Stapler,8.25
C-900,Monitor arm,60.00
D-100,Notebook,2.50
F-210,Mouse pad,3.00
"""

NEW = """sku,name,price
C-900,Monitor arm,52.49
B-320,Stapler,8.80
F-210,Mouse pad,3.00
A-100,Desk lamp LED,23.10
E-500,Whiteboard,35.00
A-200,Office chair,139.00
B-310,Paper ream,5.95
"""

HEADER = "sku,name,old,new,change,percent"


def run(*args):
    return subprocess.run([sys.executable, "-m", "pricewatch.compare", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, old=OLD, new=NEW):
    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    old_path.write_text(old, encoding="utf-8")
    new_path.write_text(new, encoding="utf-8")
    return str(old_path), str(new_path), tmp_path / "changes.csv"


def read_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read().splitlines()


def test_default_threshold(tmp_path):
    old, new, out = make_inputs(tmp_path)
    result = run(old, new, str(out))
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == [
        HEADER,
        "A-100,Desk lamp LED,20.00,23.10,+3.10,+15.5",
        "B-310,Paper ream,4.80,5.95,+1.15,+24.0",
        "C-900,Monitor arm,60.00,52.49,-7.51,-12.5",
    ]


def test_threshold_flag(tmp_path):
    old, new, out = make_inputs(tmp_path)
    result = run(old, new, str(out), "--threshold", "6.5")
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == [
        HEADER,
        "A-100,Desk lamp LED,20.00,23.10,+3.10,+15.5",
        "A-200,Office chair,149.00,139.00,-10.00,-6.7",
        "B-310,Paper ream,4.80,5.95,+1.15,+24.0",
        "B-320,Stapler,8.25,8.80,+0.55,+6.7",
        "C-900,Monitor arm,60.00,52.49,-7.51,-12.5",
    ]


def test_nothing_to_report_writes_header_only(tmp_path):
    old, new, out = make_inputs(tmp_path)
    result = run(old, new, str(out), "--threshold", "30")
    assert result.returncode == 0, result.stderr
    assert read_lines(out) == [HEADER]


def test_bad_threshold(tmp_path):
    old, new, out = make_inputs(tmp_path)
    for value in ("abc", "0", "-5"):
        result = run(old, new, str(out), "--threshold=" + value)
        assert result.returncode == 2, value
        assert not out.exists()


def test_bad_price_list(tmp_path):
    old, new, out = make_inputs(tmp_path, new=NEW.replace("5.95", "5.9x"))
    result = run(old, new, str(out))
    assert result.returncode == 2
    assert not out.exists()
    result = run(old, str(tmp_path / "missing.csv"), str(out))
    assert result.returncode == 2
    assert not out.exists()
