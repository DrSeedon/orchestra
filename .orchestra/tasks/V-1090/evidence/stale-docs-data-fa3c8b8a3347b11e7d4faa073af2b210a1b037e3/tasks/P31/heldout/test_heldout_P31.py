import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOSTS = (
    "# lab hosts\n"
    "127.0.0.1   localhost\n"
    "::1         localhost ip6-localhost\n"
    "\n"
    "10.0.0.5    build build.lan   # build box\n"
    "10.0.0.300  printer\n"
    "10.0.0.6    Build web_server -bad\n"
    "192.168.1.9 web web\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "hostsfile.lint", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_report_lists_issues_in_line_order(tmp_path):
    hosts = str(tmp_path / "hosts")
    out = str(tmp_path / "report.json")
    write(hosts, HOSTS)
    r = run(hosts, out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert read_json(out) == {
        "file": "hosts",
        "entries": 6,
        "issues": [
            {"line": 6, "kind": "bad_address", "value": "10.0.0.300"},
            {"line": 7, "kind": "duplicate", "value": "Build"},
            {"line": 7, "kind": "bad_name", "value": "web_server"},
            {"line": 7, "kind": "bad_name", "value": "-bad"},
            {"line": 8, "kind": "duplicate", "value": "web"},
        ],
        "counts": {"bad_address": 1, "bad_name": 2, "duplicate": 2},
    }


def test_clean_file_exits_0_and_creates_folder(tmp_path):
    hosts = str(tmp_path / "in" / "lab.hosts")
    out = str(tmp_path / "out" / "sub" / "report.json")
    write(hosts, "127.0.0.1 localhost\n::1 localhost\n# end\n10.0.0.5 build\n")
    r = run(hosts, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "file": "lab.hosts",
        "entries": 3,
        "issues": [],
        "counts": {"bad_address": 0, "bad_name": 0, "duplicate": 0},
    }


def test_bad_lines_do_not_count_as_duplicates(tmp_path):
    hosts = str(tmp_path / "hosts")
    out = str(tmp_path / "report.json")
    write(hosts, "10.0.0.999 db\n10.0.0.7 db\n10.0.0.8 a_b\n10.0.0.9 A_B\nfd00::7 DB\n")
    r = run(hosts, out)
    assert r.returncode == 1, r.stdout + r.stderr
    report = read_json(out)
    assert report["issues"] == [
        {"line": 1, "kind": "bad_address", "value": "10.0.0.999"},
        {"line": 3, "kind": "bad_name", "value": "a_b"},
        {"line": 4, "kind": "bad_name", "value": "A_B"},
    ]
    assert report["counts"] == {"bad_address": 1, "bad_name": 2, "duplicate": 0}
    assert report["entries"] == 5


def test_entry_without_name_exits_2(tmp_path):
    hosts = str(tmp_path / "hosts")
    out = str(tmp_path / "report.json")
    write(hosts, "127.0.0.1 localhost\n10.0.0.300 printer\n10.0.0.7\n")
    r = run(hosts, out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)


def test_missing_hosts_file_exits_2(tmp_path):
    out = str(tmp_path / "out" / "report.json")
    r = run(str(tmp_path / "nope"), out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)
