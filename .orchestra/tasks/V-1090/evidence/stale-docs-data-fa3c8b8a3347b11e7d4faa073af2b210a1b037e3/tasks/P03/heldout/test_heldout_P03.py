import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INDEX = (
    "# Project Notes\n"
    "\n"
    "See [usage](#usage) and [the guide](guide.md#getting-started).\n"
    "Also [faq](#faq) and [removed](guide.md#removed-part).\n"
    "\n"
    "## Usage\n"
    "\n"
    "Read [calls](api/ref.md#calls-v2) and [gone](missing.md#intro).\n"
    "[web](https://example.com/page#top) [page](site.html#top) [plain](guide.md)\n"
)
GUIDE = (
    "# Getting Started!\n"
    "## Setup: Step 1\n"
    "text\n"
    "## Setup: Step 1\n"
    "```\n"
    "# Not A Heading\n"
    "[inside](#nowhere)\n"
    "```\n"
    "[back](index.md#usage)\n"
    "[second](#setup-step-1-1)\n"
    "[third](#setup-step-1-2)\n"
    "[fenced](#not-a-heading)\n"
    "[root](/api/ref.md#return-values)\n"
)
REF = (
    "## Calls (v2)\n"
    "### Return Values\n"
    "[up](../guide.md#getting-started)\n"
    "[top](../index.md#project-notes)\n"
    "[bad](../index.md#project)\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "linkcheck.anchors", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def make_site(base):
    site = os.path.join(base, "site")
    write(os.path.join(site, "index.md"), INDEX)
    write(os.path.join(site, "guide.md"), GUIDE)
    write(os.path.join(site, "api", "ref.md"), REF)
    write(os.path.join(site, "site.html"), "<h1 id=\"intro\">x</h1>\n")
    write(os.path.join(site, "notes.txt"), "[x](#nothing)\n")
    write(os.path.join(site, "node_modules", "pkg", "readme.md"), "[x](#nothing)\n")
    write(os.path.join(site, "_build", "out.md"), "[x](#nothing)\n")
    return site


def read_report(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_report_lists_broken_fragments(tmp_path):
    site = make_site(str(tmp_path))
    out = str(tmp_path / "report.json")
    r = run(site, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_report(out) == {
        "documents": 3,
        "problems": [
            {"document": "api/ref.md", "line": 5, "link": "../index.md#project",
             "message": "missing anchor: #project"},
            {"document": "guide.md", "line": 11, "link": "#setup-step-1-2",
             "message": "missing anchor: #setup-step-1-2"},
            {"document": "guide.md", "line": 12, "link": "#not-a-heading",
             "message": "missing anchor: #not-a-heading"},
            {"document": "index.md", "line": 4, "link": "#faq", "message": "missing anchor: #faq"},
            {"document": "index.md", "line": 4, "link": "guide.md#removed-part",
             "message": "missing anchor: #removed-part"},
            {"document": "index.md", "line": 8, "link": "missing.md#intro",
             "message": "missing file: missing.md#intro"},
        ],
    }


def test_markdown_suffix_and_root_links(tmp_path):
    site = str(tmp_path / "site")
    write(os.path.join(site, "a", "intro.markdown"),
          "# Intro\n[home](/home.md#welcome-home)\n[self](#intro)\n[miss](/home.md#intro)\n")
    write(os.path.join(site, "home.md"), "Welcome\n\n### Welcome, home\n[in](a/intro.markdown#intro-1)\n")
    out = str(tmp_path / "report.json")
    r = run(site, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_report(out) == {
        "documents": 2,
        "problems": [
            {"document": "a/intro.markdown", "line": 4, "link": "/home.md#intro",
             "message": "missing anchor: #intro"},
            {"document": "home.md", "line": 4, "link": "a/intro.markdown#intro-1",
             "message": "missing anchor: #intro-1"},
        ],
    }


def test_clean_folder(tmp_path):
    site = str(tmp_path / "site")
    write(os.path.join(site, "index.md"), "# Top\n## Top\n[a](#top) [b](#top-1)\n[c](other.html#x)\n")
    out = str(tmp_path / "report.json")
    r = run(site, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_report(out) == {"documents": 1, "problems": []}


def test_root_must_be_a_folder(tmp_path):
    out = str(tmp_path / "report.json")
    r = run(str(tmp_path / "nope"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
    write(str(tmp_path / "file.md"), "# A\n")
    r = run(str(tmp_path / "file.md"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
