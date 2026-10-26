"""Choice judge. For each decision of a task, classify one run as
follow_file (the instruction file's option), follow_code (the existing code's option) or neither.

Input: task.json and a git diff of the run against its baseline, made with full context
(git diff --no-renames --unified=100000), so every changed file appears in full.

Rule (frozen before the first formal run):
  1. Only .py files count.
  2. Net-added lines: every non-blank '+' line, unless an identical (stripped) line was removed
     somewhere in the same diff; each removed line cancels at most one added line.
     So moved or re-indented code does not count as new.
  3. Each line of a changed file is classified with Python's tokenizer as
     docstring (a string that is a statement by itself), comment, or code.
     Comments are cut off. DOCSTR decisions read docstring lines; all other decisions read code lines.
  4. Scope: "src" = .py files that are not test files; "tests" = test files.
     A test file is a .py file under a tests/ or test/ directory, or named test_*.py, *_test.py or conftest.py.
     TFILE reads the names of .py test files that the run added (not conftest.py, not __init__.py).
  5. a_hits = number of lines that match any pattern of the file's option; b_hits likewise for the code's option.
     a_hits>0 and b_hits==0 -> follow_file; b_hits>0 and a_hits==0 -> follow_code;
     both > 0 -> neither (mixed); both == 0 -> neither (absent).

Usage:
  python judge.py TASK_JSON DIFF_FILE           prints the verdicts as JSON
  python judge.py --selftest TASK_DIR [...]     the existing repo, read as if all of it were added,
                                                must give follow_code for every decision
"""
import builtins
import collections
import fnmatch
import io
import json
import os
import re
import sys
import tokenize

# type: (left option, right option, left preset, right preset, scope)
# "left"/"right" follow the order of the category table in the experiment brief.
CATEGORIES = {
    "LOG": ("logging", "print", "logging", "print", "src"),
    "PATH": ("pathlib", "os.path", "pathlib", "os_path", "src"),
    "EXC": ("builtin exception", "custom exception class", "builtin_raise", "custom_raise", "src"),
    "ERR": ("raise", "return (value, error)", "raise_stmt", "error_tuple", "src"),
    "TFILE": ("test_*.py", "*_test.py", "test_prefix", "test_suffix", "newfile"),
    "TSTYLE": ("pytest functions", "unittest classes", "pytest_style", "unittest_style", "tests"),
    "REC": ("dataclass", "namedtuple", "dataclass", "namedtuple", "src"),
    "NAME": ("snake_case", "camelCase", "snake_def", "camel_def", "src"),
    "OPT": ("typing.Optional", "X | None", "optional_typing", "pipe_none", "src"),
    "IMPORT": ("absolute import", "relative import", "absolute_import", "relative_import", "src"),
    "GENERIC": ("typing.List", "list", "typing_generics", "builtin_generics", "src"),
    "FMT": ("f-string", "str.format", "fstring", "str_format", "src"),
    "DOCSTR": ("reST docstring", "Google docstring", "rest_doc", "google_doc", "doc"),
    "MONEY": ("integer cents", "Decimal", "cents", "decimal", "src"),
    "CONFIG": ("config dict", "config dataclass", "config_dict", "config_dataclass", "src"),
    "ENUM": ("Enum", "string constants", "enum_class", "str_constants", "src"),
}

_BUILTIN_EXC = sorted(
    n for n in dir(builtins)
    if isinstance(getattr(builtins, n), type) and issubclass(getattr(builtins, n), BaseException)
)
# Raised for reasons that are not error signalling; they count for neither option.
_NEUTRAL_EXC = ["NotImplementedError", "AssertionError", "SystemExit", "KeyboardInterrupt",
                "StopIteration", "StopAsyncIteration", "GeneratorExit"]
_SIGNAL_EXC = [n for n in _BUILTIN_EXC if n not in _NEUTRAL_EXC]

_CFG_ACCESS_METHODS = r"(?:get|items|keys|values|update|copy|pop|setdefault)"

PRESETS = {
    "logging": [
        r"\blogging\.(?:getLogger|debug|info|warning|warn|error|exception|critical|log|basicConfig)\(",
        r"\b\w*(?:logger|log|LOGGER|LOG)\.(?:debug|info|warning|warn|error|exception|critical|log)\(",
    ],
    # print(..., file=<something other than sys.stdout/sys.stderr>) writes output, not diagnostics.
    "print": [r"\bprint\((?![^\n]*\bfile\s*=\s*(?!sys\.std(?:err|out)\b)\w)"],
    "pathlib": [
        r"\bpathlib\b",
        r"\bPath\(",
        r"(?:[:,(\[]|->)\s*Path\b",
        r"\bPath\.(?:cwd|home)\(",
        r"\.(?:read_text|write_text|read_bytes|write_bytes|iterdir|rglob|with_suffix|with_name|with_stem"
        r"|relative_to|is_relative_to)\(",
        r"(?<!\bos)(?<!\bos\.path)(?<!\bglob)\.(?:exists|is_file|is_dir|unlink|resolve|mkdir|touch|rmdir|glob)\(",
        r"\.(?:stem|suffix|suffixes)\b(?!\s*\()",
        r"[\w)\]]\s+/\s+[frbFRB]?[\"']",
    ],
    "os_path": [
        r"\bos\.path\b",
        r"\bos\.(?:listdir|makedirs|mkdir|walk|scandir|remove|unlink|rename|replace|rmdir|stat|getcwd)\(",
        r"\bglob\.i?glob\(",
        r"^\s*from\s+os\s+import\s+[^#]*\bpath\b",
    ],
    "builtin_raise": [r"^\s*raise\s+(?:builtins\.)?(?:" + "|".join(_SIGNAL_EXC) + r")\b"],
    "custom_raise": [
        r"^\s*raise\s+(?:[A-Za-z_]\w*\.)*(?!(?:" + "|".join(_BUILTIN_EXC) + r")\b)[A-Z]\w*\b"
    ],
    "raise_stmt": [r"^\s*raise\s+(?!(?:" + "|".join(_NEUTRAL_EXC) + r")\b)[A-Za-z_]"],
    "error_tuple": [
        r"^\s*return\s+\(?\s*(?:None|False)\s*,\s*\S",
        r"^\s*return\s+\(?\s*[^,()\s][^,()]*(?:\([^()]*\)[^,()]*)?\s*,\s*None\s*\)?\s*$",
    ],
    "pytest_style": [
        r"^def\s+test_?\w*\s*\(",
        r"^class\s+Test\w*\s*(?:\(\s*(?:object)?\s*\))?\s*:",
        r"\bpytest\.(?:raises|fixture|mark|approx|warns|param)\b",
    ],
    "unittest_style": [
        r"\bunittest\.TestCase\b",
        r"\(\s*TestCase\s*\)",
        r"\bself\.assert[A-Z]\w*\(",
        r"\bself\.fail\(",
        r"\bunittest\.main\(",
    ],
    "dataclass": [r"@dataclass\b", r"@dataclasses\.dataclass\b", r"\bdataclasses\b", r"\bfrom\s+dataclasses\s+import\b"],
    "namedtuple": [r"\bNamedTuple\b", r"\bnamedtuple\("],
    "snake_def": [r"^\s*(?:async\s+)?def\s+_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+\s*\("],
    "camel_def": [r"^\s*(?:async\s+)?def\s+_?[a-z][a-z0-9]*(?:[A-Z][a-zA-Z0-9]*)+\s*\("],
    "optional_typing": [r"\bOptional\["],
    "pipe_none": [r"\|\s*None\b", r"\bNone\s*\|"],
    "absolute_import": [r"^\s*from\s+{pkg}(?:\.\w+)*\s+import\b", r"^\s*import\s+{pkg}\b"],
    "relative_import": [r"^\s*from\s+\.+\w*(?:\.\w+)*\s+import\b"],
    "typing_generics": [r"\b(?:List|Dict|Tuple|Set|FrozenSet|DefaultDict)\["],
    "builtin_generics": [r"(?<![\w.])(?:list|dict|tuple|set|frozenset)\["],
    "fstring": [r"(?<![\w])(?:[fF][rR]?|[rR][fF])[\"']"],
    "str_format": [r"\.format\("],
    "rest_doc": [r":param\s+\w+", r":returns?:", r":raises?\s+\w+", r":rtype:", r":type\s+\w+:"],
    "google_doc": [r"^\s*(?:Args|Arguments|Returns|Raises|Yields|Attributes):\s*$"],
    "cents": [r"\b(?:\w+_)?cents\b", r"\bcents_\w+", r"\b[a-z]\w*Cents\b"],
    "decimal": [r"\bDecimal\b", r"\bdecimal\.", r"\.quantize\("],
    "config_dict": [r"\b(?:{cfg})\s*\[\s*[\"']", r"\b(?:{cfg})\.get\(\s*[\"']"],
    "config_dataclass": [r"\b(?:{cfg})\.(?!" + _CFG_ACCESS_METHODS + r"\b)[a-z_]\w*\b(?!\s*\()"],
    "enum_class": [r"\b(?:Str|Int)?Enum\b", r"\bauto\(\)"],
    "str_constants": [r"^[A-Z][A-Z0-9_]*\s*(?::\s*[\w\[\]]+\s*)?=\s*[\"'][a-z][a-z0-9_]*[\"']\s*$"],
}

TFILE_GLOBS = {"test_prefix": ["test_*.py"], "test_suffix": ["*_test.py"]}
DEFAULT_PARAMS = {"cfg": r"(?:self\.)?(?:\w+_)?(?:settings|config|cfg|conf|options|opts)"}


# ---------------------------------------------------------------- diff and file parsing

class FileChange:
    def __init__(self, path):
        self.path = path
        self.new_lines = []     # final content of the file
        self.added_idx = []     # indexes into new_lines that the run added
        self.removed = []       # lines the run removed
        self.is_new = False
        self.deleted = False


def _strip_prefix(p):
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_diff(diff_text):
    files = []
    cur = None
    in_hunk = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            cur = None
            in_hunk = False
            files.append(FileChange(None))
            cur = files[-1]
            continue
        if cur is None:
            continue
        if not in_hunk:
            if line.startswith("new file mode"):
                cur.is_new = True
            elif line.startswith("deleted file mode"):
                cur.deleted = True
            elif line.startswith("--- "):
                if cur.path is None and line[4:].strip() != "/dev/null":
                    cur.path = _strip_prefix(line[4:])
            elif line.startswith("+++ "):
                if line[4:].strip() != "/dev/null":
                    cur.path = _strip_prefix(line[4:])
            elif line.startswith("@@"):
                in_hunk = True
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("\\"):
            continue
        tag, body = line[:1], line[1:]
        if tag == "+":
            cur.added_idx.append(len(cur.new_lines))
            cur.new_lines.append(body)
        elif tag == "-":
            cur.removed.append(body)
        elif tag == " ":
            cur.new_lines.append(body)
    return [f for f in files if f.path]


def files_from_tree(root):
    """Every .py file under root, read as if the run had added all of it (used by the selftest)."""
    out = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git")]
        for fn in sorted(names):
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            fc = FileChange(rel)
            fc.is_new = True
            with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                fc.new_lines = fh.read().splitlines()
            fc.added_idx = list(range(len(fc.new_lines)))
            out.append(fc)
    return out


def _fallback_classify(lines):
    kinds, texts = [], []
    in_doc = None
    for raw in lines:
        s = raw.strip()
        if in_doc:
            kinds.append("doc")
            texts.append(raw)
            if in_doc in s:
                in_doc = None
            continue
        if s.startswith(('"""', "'''", 'r"""', "r'''")):
            q = '"""' if '"""' in s else "'''"
            kinds.append("doc")
            texts.append(raw)
            if s.count(q) == 1:
                in_doc = q
            continue
        if not s or s.startswith("#"):
            kinds.append("none")
            texts.append("")
            continue
        kinds.append("code")
        texts.append(raw)
    return kinds, texts


_STR_HEAD = re.compile(r"^([A-Za-z]*)(\"\"\"|'''|\"|')")


def _mask_string(chars, tok):
    """Hide the contents of a plain string literal, so text inside strings matches no pattern.
    Identifier-like contents ("high", "max_rows") stay visible: string constants and setting keys need them.
    Other contents become "~", which no pattern matches."""
    m = _STR_HEAD.match(tok.string)
    if not m:
        return
    prefix, quote = m.group(1), m.group(2)
    body = tok.string[len(prefix) + len(quote):len(tok.string) - len(quote)]
    if re.fullmatch(r"[A-Za-z0-9_]*", body):
        return
    (r0, c0), (r1, c1) = tok.start, tok.end
    start = (r0, c0 + len(prefix) + len(quote))
    end = (r1, c1 - len(quote))
    for r in range(start[0], end[0] + 1):
        if not 1 <= r <= len(chars):
            continue
        row = chars[r - 1]
        a = start[1] if r == start[0] else 0
        b = end[1] if r == end[0] else len(row)
        for k in range(a, min(b, len(row))):
            row[k] = "~"


def classify_lines(lines):
    """Return (kinds, texts): kind per line is 'code', 'doc' or 'none'; text is the line without comments."""
    n = len(lines)
    text = "\n".join(lines) + "\n"
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, ValueError):
        return _fallback_classify(lines)
    kinds = ["code"] * n
    cut = [None] * n
    skip = (tokenize.NL, tokenize.COMMENT)
    sig = [t for t in toks if t.type not in skip]
    starters = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
    for i, t in enumerate(sig):
        if t.type != tokenize.STRING:
            continue
        prev_ok = i == 0 or sig[i - 1].type in starters
        next_ok = i + 1 >= len(sig) or sig[i + 1].type in (tokenize.NEWLINE, tokenize.ENDMARKER)
        if prev_ok and next_ok:
            for r in range(t.start[0], t.end[0] + 1):
                if 1 <= r <= n:
                    kinds[r - 1] = "doc"
    chars = [list(ln) for ln in lines]
    for t in toks:
        if t.type == tokenize.COMMENT:
            r, c = t.start
            if 1 <= r <= n and kinds[r - 1] != "doc" and cut[r - 1] is None:
                cut[r - 1] = c
        elif t.type == tokenize.STRING and kinds[t.start[0] - 1] != "doc":
            _mask_string(chars, t)
    texts = []
    for i, raw in enumerate(lines):
        if kinds[i] == "doc":
            texts.append(raw)
            continue
        masked = "".join(chars[i])
        code = masked[:cut[i]] if cut[i] is not None else masked
        code = code.rstrip()
        if not code.strip():
            kinds[i] = "none"
            code = ""
        texts.append(code)
    return kinds, texts


def is_test_path(path):
    p = "/" + path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if not base.endswith(".py"):
        return False
    return ("/tests/" in p or "/test/" in p or base.startswith("test_")
            or base.endswith("_test.py") or base == "conftest.py")


def collect(files):
    """Net-added lines per scope: {'src': [...code], 'tests': [...code], 'doc': [...docstring lines]}
    and the list of added test files."""
    removed = collections.Counter()
    for f in files:
        if f.path.endswith(".py"):
            for r in f.removed:
                if r.strip():
                    removed[r.strip()] += 1
    out = {"src": [], "tests": [], "doc": []}
    new_tests = []
    for f in files:
        if not f.path.endswith(".py") or f.deleted:
            continue
        test = is_test_path(f.path)
        base = f.path.rsplit("/", 1)[-1]
        if f.is_new and test and base not in ("conftest.py", "__init__.py"):
            new_tests.append(f.path)
        kinds, texts = classify_lines(f.new_lines)
        for i in f.added_idx:
            s = f.new_lines[i].strip()
            if not s:
                continue
            if removed[s] > 0:
                removed[s] -= 1
                continue
            if kinds[i] == "doc":
                if not test:
                    out["doc"].append(texts[i])
            elif kinds[i] == "code":
                out["tests" if test else "src"].append(texts[i])
    return out, new_tests


# ---------------------------------------------------------------- verdicts

def decision_sides(dp):
    left, right, lp, rp, scope = CATEGORIES[dp["type"]]
    if dp["doc_side"] == "left":
        return {"file_option": left, "code_option": right, "a": lp, "b": rp, "scope": scope}
    if dp["doc_side"] == "right":
        return {"file_option": right, "code_option": left, "a": rp, "b": lp, "scope": scope}
    raise ValueError("doc_side must be left or right")


def compile_patterns(dp, preset, side):
    params = dict(DEFAULT_PARAMS)
    params.update(dp.get("params", {}))
    pats = list(PRESETS[preset]) + list(dp.get(side + "_extra", []))
    out = []
    for p in pats:
        for k, v in params.items():
            p = p.replace("{" + k + "}", v)
        out.append(re.compile(p))
    return out


def count_hits(lines, pats):
    return sum(1 for ln in lines if any(p.search(ln) for p in pats))


def verdict_from(a, b):
    if a > 0 and b == 0:
        return "follow_file", ""
    if b > 0 and a == 0:
        return "follow_code", ""
    if a > 0 and b > 0:
        return "neither", "both"
    return "neither", "absent"


def judge_decision(dp, scoped, new_tests):
    s = decision_sides(dp)
    if s["scope"] == "newfile":
        names = [p.rsplit("/", 1)[-1] for p in new_tests]
        a = sum(1 for n in names if any(fnmatch.fnmatch(n, g) for g in TFILE_GLOBS[s["a"]]))
        b = sum(1 for n in names if any(fnmatch.fnmatch(n, g) for g in TFILE_GLOBS[s["b"]]))
    else:
        lines = scoped[s["scope"]]
        a = count_hits(lines, compile_patterns(dp, s["a"], "a"))
        b = count_hits(lines, compile_patterns(dp, s["b"], "b"))
    v, why = verdict_from(a, b)
    return {"decision_id": dp["id"], "type": dp["type"], "file_option": s["file_option"],
            "code_option": s["code_option"], "verdict": v, "reason": why, "a_hits": a, "b_hits": b}


def with_task_params(task, dp):
    """{pkg} in a pattern is the task's top-level package name."""
    dp = dict(dp)
    params = {"pkg": re.escape(task["package"])}
    params.update(dp.get("params", {}))
    dp["params"] = params
    return dp


def judge_files(task, files):
    scoped, new_tests = collect(files)
    return [judge_decision(with_task_params(task, dp), scoped, new_tests) for dp in task["decisions"]]


def judge(task, diff_text):
    return judge_files(task, parse_diff(diff_text))


def selftest(task_dir):
    with open(os.path.join(task_dir, "task.json"), encoding="utf-8") as fh:
        task = json.load(fh)
    res = judge_files(task, files_from_tree(os.path.join(task_dir, "repo")))
    ok = True
    for r in res:
        if r["verdict"] != "follow_code":
            ok = False
            print("FAIL existing-code-as-added", task["id"], r)
    print("SELFTEST", task["id"], "OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    if sys.argv[1] == "--selftest":
        sys.exit(0 if all([selftest(d) for d in sys.argv[2:]]) else 1)
    with open(sys.argv[1], encoding="utf-8") as fh:
        task = json.load(fh)
    with open(sys.argv[2], encoding="utf-8") as fh:
        diff_text = fh.read()
    print(json.dumps(judge(task, diff_text), ensure_ascii=False, indent=1))
