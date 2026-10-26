import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """\
# shop service
DATABASE_URL url required
PORT int required
DEBUG bool optional
APP_NAME str
"""

ENV_FILES = {
    "prod.env": "DATABASE_URL=postgres://db.internal/shop\nPORT=80a\nAPP_NAME=shop\nEXTRA_FLAG=1\n",
    "staging.env": 'export DATABASE_URL="postgres://staging/app"\nPORT=8080\nDEBUG=maybe\n',
    "good.env": "# local\nDATABASE_URL=postgres://localhost/shop\nPORT=8000\nAPP_NAME=shop\nDEBUG=yes\n",
    "broken.env": "DATABASE_URL=postgres://localhost/shop\nthis line has no equals sign\n",
    "notes.txt": "PORT=abc\n",
}


def write_files(folder, files):
    os.makedirs(folder, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as handle:
            handle.write(text)


def make_settings(root, extra=""):
    write_files(root, {
        "app.schema": SCHEMA,
        "envcheck.ini": "[envcheck]\nschema = app.schema\n" + extra,
    })
    return os.path.join(root, "envcheck.ini")


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "envcheck.scan", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_strict_scan_reports_every_file(tmp_path):
    root = str(tmp_path)
    settings = make_settings(root, "strict = yes\n")
    envs = os.path.join(root, "envs")
    write_files(envs, ENV_FILES)
    output = os.path.join(root, "report.json")
    result = run(settings, envs, output)
    assert result.returncode == 1, result.stderr
    assert read_json(output) == {
        "files": {
            "good.env": {"missing": [], "invalid": [], "unknown": []},
            "prod.env": {"missing": [], "invalid": ["PORT"], "unknown": ["EXTRA_FLAG"]},
            "staging.env": {"missing": ["APP_NAME"], "invalid": ["DEBUG"], "unknown": []},
        },
        "unreadable": ["broken.env"],
        "ok": False,
    }


def test_scan_without_strict_ignores_extra_names(tmp_path):
    root = str(tmp_path)
    settings = make_settings(root)
    envs = os.path.join(root, "envs")
    extra = ENV_FILES["good.env"] + "EXTRA_FLAG=1\n"
    write_files(envs, {"good.env": ENV_FILES["good.env"], "extra.env": extra, "notes.txt": "x"})
    output = os.path.join(root, "report.json")
    result = run(settings, envs, output)
    assert result.returncode == 0, result.stderr
    data = read_json(output)
    assert data["ok"] is True
    assert data["unreadable"] == []
    assert sorted(data["files"]) == ["extra.env", "good.env"]
    assert data["files"]["extra.env"] == {"missing": [], "invalid": [], "unknown": []}


def test_missing_env_folder_exits_2(tmp_path):
    root = str(tmp_path)
    settings = make_settings(root, "strict = no\n")
    output = os.path.join(root, "report.json")
    result = run(settings, os.path.join(root, "envs"), output)
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_folder_without_env_files_exits_2(tmp_path):
    root = str(tmp_path)
    settings = make_settings(root)
    envs = os.path.join(root, "envs")
    write_files(envs, {"notes.txt": "PORT=1\n"})
    output = os.path.join(root, "report.json")
    result = run(settings, envs, output)
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_bad_strict_value_exits_2(tmp_path):
    root = str(tmp_path)
    settings = make_settings(root, "strict = sometimes\n")
    envs = os.path.join(root, "envs")
    write_files(envs, {"good.env": ENV_FILES["good.env"]})
    output = os.path.join(root, "report.json")
    result = run(settings, envs, output)
    assert result.returncode == 2
    assert not os.path.exists(output)
