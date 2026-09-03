#!/usr/bin/env python3
"""Task-local, read-only structural measurements for #455."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import random
import re
import statistics
import subprocess
import tarfile
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOTS = ("app", "scripts")
PROTOCOL_BASES = {"Protocol", "ABC", "ABCMeta", "TypedDict"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def module_name(path: str) -> str:
    return path[:-3].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def literal_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: set[str] = set()
        for elt in node.elts:
            values = literal_strings(elt)
            if not values:
                return set()
            out.update(values)
        return out
    return set()


def load_snapshot(
    ref: str, roots: tuple[str, ...] = ROOTS, extra_paths: tuple[str, ...] = ()
) -> dict[str, str]:
    existing = []
    for root in roots:
        if subprocess.run(
            ["git", "cat-file", "-e", f"{ref}:{root}"], capture_output=True
        ).returncode == 0:
            existing.append(root)
    raw = git_bytes("archive", "--format=tar", ref, *existing, *extra_paths)
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            fh = tf.extractfile(member)
            if fh is not None:
                files[member.name] = fh.read().decode("utf-8", errors="replace")
    return files


@dataclass(frozen=True)
class Definition:
    key: str
    path: str
    module: str
    qualname: str
    name: str
    lineno: int
    end_lineno: int
    kind: str
    decorated: bool
    dunder: bool
    protocol_member: bool
    overloaded: bool


class DefinitionCollector(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.AST) -> None:
        self.path = path
        self.module = module_name(path)
        self.tree = tree
        self.stack: list[str] = []
        self.protocol_stack: list[bool] = []
        self.defs: list[Definition] = []
        self.nodes: dict[str, ast.AST] = {}

    def _add(self, node: ast.AST, kind: str, name: str, decorated: bool) -> str:
        qualname = ".".join([*self.stack, name])
        key = f"{self.module}:{qualname}"
        decorators = getattr(node, "decorator_list", [])
        info = Definition(
            key=key,
            path=self.path,
            module=self.module,
            qualname=qualname,
            name=name,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            kind=kind,
            decorated=decorated,
            dunder=name.startswith("__") and name.endswith("__"),
            protocol_member=any(self.protocol_stack),
            overloaded=any(dotted(x).split(".")[-1] == "overload" for x in decorators),
        )
        self.defs.append(info)
        self.nodes[key] = node
        return key

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {dotted(x).split(".")[-1] for x in node.bases}
        self._add(node, "class", node.name, bool(node.decorator_list))
        self.stack.append(node.name)
        self.protocol_stack.append(bool(base_names & PROTOCOL_BASES) or any(self.protocol_stack))
        self.generic_visit(node)
        self.protocol_stack.pop()
        self.stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._add(node, "function", node.name, bool(node.decorator_list))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


class ConstantsCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.values: dict[str, set[str]] = defaultdict(set)

    def visit_Assign(self, node: ast.Assign) -> None:
        values = literal_strings(node.value)
        if values:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.values[target.id].update(values)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self.values[node.target.id].update(literal_strings(node.value))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if isinstance(node.target, ast.Name):
            self.values[node.target.id].update(literal_strings(node.iter))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


class ImportAliasCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            self.aliases[imported.asname or imported.name] = imported.name

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            self.aliases[imported.asname or imported.name.split(".")[0]] = imported.name.split(".")[-1]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def scope_aliases(body: list[ast.stmt], inherited: dict[str, str]) -> dict[str, str]:
    collector = ImportAliasCollector()
    for statement in body:
        collector.visit(statement)
    return {**inherited, **collector.aliases}


class ReferenceCollector(ast.NodeVisitor):
    def __init__(
        self,
        source: str,
        name_index: dict[str, list[str]],
        constants: dict[str, set[str]],
        aliases: dict[str, str],
        path: str,
    ) -> None:
        self.source = source
        self.name_index = name_index
        self.constants = constants
        self.aliases = aliases
        self.path = path
        self.edges: set[tuple[str, str]] = set()
        self.unresolved_getattrs: list[dict] = []

    def _link(self, name: str) -> None:
        for target in self.name_index.get(name, []):
            if target != self.source:
                self.edges.add((self.source, target))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._link(node.id)
            if node.id in self.aliases:
                self._link(self.aliases[node.id])

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self._link(node.attr)
        self.generic_visit(node.value)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self._link(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        if dotted(node.func).split(".")[-1] == "getattr" and len(node.args) >= 2:
            arg = node.args[1]
            values = literal_strings(arg)
            if not values and isinstance(arg, ast.Name):
                values = self.constants.get(arg.id, set())
            if values:
                for value in values:
                    self._link(value)
            else:
                self.unresolved_getattrs.append(
                    {
                        "path": self.path,
                        "line": node.lineno,
                        "scope": self.source,
                        "receiver": ast.unparse(node.args[0])[:120],
                        "name_expr": ast.unparse(arg)[:120],
                    }
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def scope_constants(body: list[ast.stmt]) -> dict[str, set[str]]:
    collector = ConstantsCollector()
    for stmt in body:
        collector.visit(stmt)
    return collector.values


def references_for_body(
    body: list[ast.stmt], source: str, name_index: dict[str, list[str]], aliases: dict[str, str], path: str
) -> tuple[set[tuple[str, str]], list[dict]]:
    collector = ReferenceCollector(
        source, name_index, scope_constants(body), scope_aliases(body, aliases), path
    )
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Defaults/decorators execute now, bodies get their own scope below.
            for expr in [*getattr(stmt, "decorator_list", []), *getattr(stmt, "bases", [])]:
                collector.visit(expr)
            args = getattr(stmt, "args", None)
            if args:
                for expr in [*args.defaults, *[x for x in args.kw_defaults if x is not None]]:
                    collector.visit(expr)
            continue
        collector.visit(stmt)
    return collector.edges, collector.unresolved_getattrs


def iter_statement_lists(node: ast.AST) -> Iterable[list[ast.stmt]]:
    for _field, value in ast.iter_fields(node):
        if isinstance(value, list):
            if value and all(isinstance(x, ast.stmt) for x in value):
                yield value
            for item in value:
                if isinstance(item, ast.AST):
                    yield from iter_statement_lists(item)
        elif isinstance(value, ast.AST):
            yield from iter_statement_lists(value)


def clone_occurrences(path: str, tree: ast.AST, size: int = 4) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for statements in iter_statement_lists(tree):
        for offset in range(0, len(statements) - size + 1):
            window = statements[offset : offset + size]
            if any(isinstance(x, (ast.Import, ast.ImportFrom)) for x in window):
                continue
            if all(isinstance(x, (ast.Pass, ast.Break, ast.Continue, ast.Raise)) for x in window):
                continue
            payload = "\n".join(ast.dump(x, include_attributes=False) for x in window)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            groups[digest].append(
                {
                    "path": path,
                    "start": window[0].lineno,
                    "end": window[-1].end_lineno or window[-1].lineno,
                    "node_types": [type(x).__name__ for x in window],
                }
            )
    return groups


def analyze_files(files: dict[str, str], *, root_test_functions: bool = False) -> dict:
    trees: dict[str, ast.AST] = {}
    parse_errors: list[dict] = []
    defs: list[Definition] = []
    nodes: dict[str, ast.AST] = {}
    for path, text in sorted(files.items()):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            parse_errors.append({"path": path, "line": exc.lineno, "error": exc.msg})
            continue
        trees[path] = tree
        collector = DefinitionCollector(path, tree)
        collector.visit(tree)
        defs.extend(collector.defs)
        nodes.update(collector.nodes)

    name_index: dict[str, list[str]] = defaultdict(list)
    by_key = {x.key: x for x in defs}
    for info in defs:
        name_index[info.name].append(info.key)
    for values in name_index.values():
        values.sort()

    roots: set[str] = set()
    edges: dict[str, set[str]] = defaultdict(set)
    unresolved: list[dict] = []
    module_aliases: dict[str, dict[str, str]] = {}
    for path, tree in trees.items():
        aliases: dict[str, str] = {}
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom):
                for imported in statement.names:
                    aliases[imported.asname or imported.name] = imported.name
            elif isinstance(statement, ast.Import):
                for imported in statement.names:
                    aliases[imported.asname or imported.name.split(".")[0]] = imported.name.split(".")[-1]
        module_aliases[path] = aliases
    for path, tree in sorted(trees.items()):
        module_root = f"module:{module_name(path)}"
        roots.add(module_root)
        found_edges, found_unresolved = references_for_body(
            tree.body, module_root, name_index, module_aliases[path], path
        )
        for source, target in found_edges:
            edges[source].add(target)
        unresolved.extend(found_unresolved)

    for info in defs:
        if info.kind == "class":
            continue
        node = nodes[info.key]
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        found_edges, found_unresolved = references_for_body(
            node.body, info.key, name_index, module_aliases[info.path], info.path
        )
        for source, target in found_edges:
            edges[source].add(target)
        unresolved.extend(found_unresolved)
        is_test = info.path.startswith("tests/") or "/acceptance/" in info.path
        pytest_root = info.name.startswith("test_") or info.name in {
            "setup_method", "teardown_method", "setup_class", "teardown_class",
            "pytest_generate_tests", "pytest_collection_modifyitems",
        }
        if info.decorated or info.dunder or (root_test_functions and is_test and pytest_root):
            roots.add(info.key)

    reachable = set(roots)
    queue = deque(sorted(roots))
    while queue:
        source = queue.popleft()
        for target in sorted(edges.get(source, ())):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)

    non_python = "\n".join(
        text for path, text in files.items() if not path.endswith(".py")
    )
    candidates: list[dict] = []
    for info in defs:
        if info.kind != "function" or not info.path.startswith("app/") or info.key in reachable:
            continue
        if info.decorated or info.dunder or info.protocol_member or info.overloaded:
            continue
        external_refs = len(re.findall(rf"(?<!\w){re.escape(info.name)}(?!\w)", non_python))
        if external_refs:
            continue
        candidates.append(
            {
                "key": info.key,
                "path": info.path,
                "qualname": info.qualname,
                "name": info.name,
                "start": info.lineno,
                "end": info.end_lineno,
            }
        )

    reverse_edges: dict[str, list[str]] = defaultdict(list)
    for source, targets in edges.items():
        for target in targets:
            reverse_edges[target].append(source)
    candidate_incoming = {
        candidate["key"]: [
            {"source": source, "source_reachable": source in reachable}
            for source in sorted(reverse_edges.get(candidate["key"], []))
        ]
        for candidate in candidates
    }

    clones: dict[str, list[dict]] = defaultdict(list)
    for path, tree in sorted(trees.items()):
        for digest, occurrences in clone_occurrences(path, tree).items():
            clones[digest].extend(occurrences)
    clones = {
        digest: sorted(occurrences, key=lambda x: (x["path"], x["start"], x["end"]))
        for digest, occurrences in clones.items()
        if len({(x["path"], x["start"], x["end"]) for x in occurrences}) >= 2
    }

    return {
        "parse_errors": parse_errors,
        "definition_count": len(defs),
        "definition_keys": sorted(by_key),
        "reachable_definition_keys": sorted(x for x in by_key if x in reachable),
        "root_count": len(roots),
        "candidate_count": len(candidates),
        "candidates": sorted(candidates, key=lambda x: (x["path"], x["start"], x["key"])),
        "candidate_incoming": candidate_incoming,
        "unresolved_getattrs": sorted(
            unresolved, key=lambda x: (x["path"], x["line"], x["scope"])
        ),
        "clone_groups": dict(sorted(clones.items())),
        "line_counts": {path: len(text.splitlines()) for path, text in sorted(files.items())},
    }


def analyze_ref(ref: str, *, include_tests: bool = False) -> dict:
    roots = (*ROOTS, "tests") if include_tests else ROOTS
    extra_paths: tuple[str, ...] = ()
    if include_tests:
        tracked = git("ls-tree", "-r", "--name-only", ref, ".orchestra/tasks").splitlines()
        extra_paths = tuple(
            path for path in tracked if "/acceptance/" in path and path.endswith(".py")
        )
    return analyze_files(
        load_snapshot(ref, roots, extra_paths), root_test_functions=include_tests
    )


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def diff_positions(parent: str, target: str) -> dict:
    text = git("diff", "--unified=0", "--no-renames", parent, target, "--", "app")
    old_path = new_path = None
    added: dict[str, set[int]] = defaultdict(set)
    deleted: dict[str, set[int]] = defaultdict(set)
    for line in text.splitlines():
        if line.startswith("--- "):
            value = line[4:]
            old_path = value[2:] if value.startswith("a/") else None
        elif line.startswith("+++ "):
            value = line[4:]
            new_path = value[2:] if value.startswith("b/") else None
        elif line.startswith("@@"):
            match = HUNK.match(line)
            if not match:
                continue
            old_start, old_count, new_start, new_count = match.groups()
            old_count_i = int(old_count if old_count is not None else 1)
            new_count_i = int(new_count if new_count is not None else 1)
            if old_path and old_path.endswith(".py"):
                deleted[old_path].update(range(int(old_start), int(old_start) + old_count_i))
            if new_path and new_path.endswith(".py"):
                added[new_path].update(range(int(new_start), int(new_start) + new_count_i))
    per_file = {}
    for path in sorted(set(added) | set(deleted)):
        per_file[path] = {"additions": len(added[path]), "deletions": len(deleted[path])}
    return {"added": added, "deleted": deleted, "per_file": per_file}


def intersect_candidate_lines(candidates: list[dict], changed: dict[str, set[int]]) -> tuple[int, list[dict]]:
    matched: dict[str, set[int]] = defaultdict(set)
    details: list[dict] = []
    for candidate in candidates:
        lines = changed.get(candidate["path"], set())
        overlap = sorted(x for x in lines if candidate["start"] <= x <= candidate["end"])
        if overlap:
            matched[candidate["path"]].update(overlap)
            details.append({**candidate, "changed_lines": len(overlap)})
    return sum(map(len, matched.values())), details


def clone_changed_lines(after: dict, before: dict, changed: dict[str, set[int]]) -> tuple[int, list[dict]]:
    matched: dict[str, set[int]] = defaultdict(set)
    details: list[dict] = []
    before_groups = before["clone_groups"]
    for digest, occurrences in after["clone_groups"].items():
        prior_count = len(before_groups.get(digest, []))
        if len(occurrences) <= prior_count:
            continue
        group_lines = 0
        matching_occurrences = []
        for occurrence in occurrences:
            lines = changed.get(occurrence["path"], set())
            overlap = {
                x for x in lines if occurrence["start"] <= x <= occurrence["end"]
            }
            if overlap:
                matched[occurrence["path"]].update(overlap)
                group_lines += len(overlap)
                matching_occurrences.append(occurrence)
        if matching_occurrences:
            details.append(
                {
                    "hash": digest,
                    "before_occurrences": prior_count,
                    "after_occurrences": len(occurrences),
                    "changed_lines_before_union": group_lines,
                    "changed_occurrences": matching_occurrences,
                }
            )
    return sum(map(len, matched.values())), details


def controls() -> dict:
    current_files = load_snapshot("main")
    tm_lines = current_files["app/tm.py"].splitlines()
    real_sites = []
    for i in range(len(tm_lines) - 2):
        if (
            tm_lines[i].strip() == "except Exception:"
            and tm_lines[i + 1].strip() == "conn.rollback()"
            and tm_lines[i + 2].strip() == "raise"
        ):
            real_sites.append(i + 1)

    negative = {
        "control.py": "def a():\n    x = 1\n    y = 2\n    z = 3\n\n"
        "def b():\n    x = 1\n    y = 2\n    z = 3\n"
    }
    positive = {
        "control.py": "def a():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n\n"
        "def b():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n"
    }
    negative_result = analyze_files(negative)
    positive_result = analyze_files(positive)
    hashes = []
    summaries = []
    for _ in range(3):
        result = analyze_files(current_files)
        summary = {
            "parse_errors": result["parse_errors"],
            "definition_count": result["definition_count"],
            "candidate_count": result["candidate_count"],
            "candidates": result["candidates"],
            "unresolved_getattrs": result["unresolved_getattrs"],
            "clone_groups": result["clone_groups"],
        }
        encoded = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
        hashes.append(hashlib.sha256(encoded).hexdigest())
        summaries.append(summary)
    return {
        "negative_control": {
            "actual_real_sites": real_sites,
            "synthetic_three_statement_clone_groups": len(negative_result["clone_groups"]),
            "pass": bool(real_sites) and not negative_result["clone_groups"],
        },
        "positive_control": {
            "synthetic_four_statement_clone_groups": len(positive_result["clone_groups"]),
            "pass": len(positive_result["clone_groups"]) == 1,
        },
        "instrument_noise": {
            "runs": 3,
            "hashes": hashes,
            "unique_hashes": len(set(hashes)),
            "pass": len(set(hashes)) == 1,
            "current_definition_count": summaries[0]["definition_count"],
            "current_candidate_count": summaries[0]["candidate_count"],
            "current_clone_group_count": len(summaries[0]["clone_groups"]),
            "current_unresolved_getattr_count": len(summaries[0]["unresolved_getattrs"]),
            "current_unresolved_getattrs": summaries[0]["unresolved_getattrs"],
        },
    }


def per_merge(cohort_path: str, labels_path: str, frozen_main: str) -> dict:
    cohort = json.loads(Path(cohort_path).read_text())
    labels = json.loads(Path(labels_path).read_text())
    explicit = set(labels["explicit"])
    cache: dict[str, dict] = {}

    def get(ref: str) -> dict:
        if ref not in cache:
            cache[ref] = analyze_ref(ref)
        return cache[ref]

    current = get(frozen_main)
    current_candidates = {x["key"] for x in current["candidates"]}
    current_definitions = set(current["definition_keys"])
    current_reachable = set(current["reachable_definition_keys"])

    rows = []
    for merge in cohort["merges"]:
        if not merge["structural_cohort"]:
            continue
        parent, target = merge["parent"], merge["target"]
        before, after = get(parent), get(target)
        diff = diff_positions(parent, target)
        dead_added, dead_added_details = intersect_candidate_lines(
            after["candidates"], diff["added"]
        )
        dead_removed, dead_removed_details = intersect_candidate_lines(
            before["candidates"], diff["deleted"]
        )
        persistent_details = [x for x in dead_added_details if x["key"] in current_candidates]
        persistent_lines_by_path: dict[str, set[int]] = defaultdict(set)
        for candidate in persistent_details:
            changed_lines = diff["added"].get(candidate["path"], set())
            persistent_lines_by_path[candidate["path"]].update(
                x for x in changed_lines if candidate["start"] <= x <= candidate["end"]
            )
        persistent_dead_added = sum(map(len, persistent_lines_by_path.values()))
        resolved_later = []
        for candidate in dead_added_details:
            if candidate["key"] in current_candidates:
                state = "persistent_candidate"
            elif candidate["key"] in current_reachable:
                state = "reachable_at_frozen_main"
            elif candidate["key"] in current_definitions:
                state = "present_but_excluded_at_frozen_main"
            else:
                state = "absent_or_renamed_at_frozen_main"
            if state != "persistent_candidate":
                resolved_later.append({**candidate, "later_state": state})
        clone_added, clone_added_details = clone_changed_lines(
            after, before, diff["added"]
        )
        clone_removed, clone_removed_details = clone_changed_lines(
            before, after, diff["deleted"]
        )
        main_ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", target, frozen_main], capture_output=True
        ).returncode == 0
        rows.append(
            {
                "target": target,
                "parent": parent,
                "finished_at": merge["finished_at"],
                "task_id": merge["task_id"],
                "task_title": merge["task_title"],
                "worker_name": merge["worker_name"],
                "role": merge["role"],
                "subject": merge["subject"],
                "label": "explicit" if target in explicit else "ambient",
                "main_ancestry_at_freeze": main_ancestry,
                "app_python_additions": sum(len(x) for x in diff["added"].values()),
                "app_python_deletions": sum(len(x) for x in diff["deleted"].values()),
                "per_file": diff["per_file"],
                "dead_added_lines_candidate": dead_added,
                "persistent_dead_added_lines_candidate": persistent_dead_added,
                "dead_removed_lines_candidate": dead_removed,
                "dead_added_candidates": dead_added_details,
                "persistent_dead_added_candidates": persistent_details,
                "dead_added_resolved_later": resolved_later,
                "dead_removed_candidates": dead_removed_details,
                "clone_added_lines_candidate": clone_added,
                "clone_removed_lines_candidate": clone_removed,
                "clone_added_groups": clone_added_details,
                "clone_removed_groups": clone_removed_details,
                "before_parse_errors": before["parse_errors"],
                "after_parse_errors": after["parse_errors"],
                "after_unresolved_getattrs": after["unresolved_getattrs"],
                "before_line_counts": before["line_counts"],
                "after_line_counts": after["line_counts"],
            }
        )
    return {
        "frozen_main": frozen_main,
        "row_count": len(rows),
        "explicit_count": sum(x["label"] == "explicit" for x in rows),
        "ambient_count": sum(x["label"] == "ambient" for x in rows),
        "rows": rows,
    }


def weighted_rate(rows: list[dict], field: str) -> float:
    denominator = sum(x["app_python_additions"] for x in rows)
    return sum(x[field] for x in rows) / denominator if denominator else 0.0


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def noise(metrics_path: str) -> dict:
    metrics = json.loads(Path(metrics_path).read_text())
    ambient = [x for x in metrics["rows"] if x["label"] == "ambient" and x["app_python_additions"]]
    rng = random.Random(455)
    fields = ("persistent_dead_added_lines_candidate", "clone_added_lines_candidate")
    spreads = {field: [] for field in fields}
    for _ in range(1000):
        shuffled = list(ambient)
        rng.shuffle(shuffled)
        midpoint = len(shuffled) // 2
        left, right = shuffled[:midpoint], shuffled[midpoint : midpoint * 2]
        for field in fields:
            spreads[field].append(abs(weighted_rate(left, field) - weighted_rate(right, field)))
    return {
        "seed": 455,
        "iterations": 1000,
        "ambient_rows": len(ambient),
        "metrics": {
            field: {
                "median_absolute_split_half_rate_difference": statistics.median(values),
                "p95_absolute_split_half_rate_difference": quantile(values, 0.95),
                "max_absolute_split_half_rate_difference": max(values),
            }
            for field, values in spreads.items()
        },
    }


def comparison(metrics_path: str, noise_path: str) -> dict:
    metrics = json.loads(Path(metrics_path).read_text())
    noise_data = json.loads(Path(noise_path).read_text())
    groups = {
        label: [x for x in metrics["rows"] if x["label"] == label]
        for label in ("ambient", "explicit")
    }
    fields = ("persistent_dead_added_lines_candidate", "clone_added_lines_candidate")
    summary = {}
    for field in fields:
        ambient_rate = weighted_rate(groups["ambient"], field)
        explicit_rate = weighted_rate(groups["explicit"], field)
        contrast = abs(ambient_rate - explicit_rate)
        floor = noise_data["metrics"][field]["median_absolute_split_half_rate_difference"]
        summary[field] = {
            "ambient_rate": ambient_rate,
            "explicit_rate": explicit_rate,
            "absolute_contrast": contrast,
            "median_noise_floor": floor,
            "contrast_exceeds_median_noise": contrast > floor,
        }

    group_stats = {}
    for label, rows in groups.items():
        group_stats[label] = {
            "merges": len(rows),
            "app_python_additions": sum(x["app_python_additions"] for x in rows),
            "app_python_deletions": sum(x["app_python_deletions"] for x in rows),
            "dead_added_lines_candidate": sum(x["dead_added_lines_candidate"] for x in rows),
            "persistent_dead_added_lines_candidate": sum(
                x["persistent_dead_added_lines_candidate"] for x in rows
            ),
            "dead_removed_lines_candidate": sum(x["dead_removed_lines_candidate"] for x in rows),
            "clone_added_lines_candidate": sum(x["clone_added_lines_candidate"] for x in rows),
            "clone_removed_lines_candidate": sum(x["clone_removed_lines_candidate"] for x in rows),
            "merges_with_dead_candidates": sum(bool(x["dead_added_lines_candidate"]) for x in rows),
            "merges_with_persistent_dead_candidates": sum(
                bool(x["persistent_dead_added_lines_candidate"]) for x in rows
            ),
            "merges_with_clone_candidates": sum(bool(x["clone_added_lines_candidate"]) for x in rows),
        }

    file_rows: dict[str, dict] = {}
    main_rows = sorted(
        (x for x in metrics["rows"] if x["main_ancestry_at_freeze"]),
        key=lambda x: x["finished_at"],
    )
    for row in main_rows:
        for path, delta in row["per_file"].items():
            item = file_rows.setdefault(
                path,
                {
                    "path": path,
                    "touches": 0,
                    "additions": 0,
                    "deletions": 0,
                    "explicit_additions": 0,
                    "explicit_deletions": 0,
                    "first_parent_loc": row["before_line_counts"].get(path, 0),
                    "last_target_loc": row["after_line_counts"].get(path, 0),
                },
            )
            item["touches"] += 1
            item["additions"] += delta["additions"]
            item["deletions"] += delta["deletions"]
            item["last_target_loc"] = row["after_line_counts"].get(path, 0)
            if row["label"] == "explicit":
                item["explicit_additions"] += delta["additions"]
                item["explicit_deletions"] += delta["deletions"]
    growth = []
    for item in file_rows.values():
        if item["touches"] >= 5:
            item["loc_change"] = item["last_target_loc"] - item["first_parent_loc"]
            growth.append(item)
    growth.sort(key=lambda x: (-x["touches"], x["path"]))
    return {"groups": group_stats, "metric_comparison": summary, "file_growth": growth}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("controls")
    ps = sub.add_parser("snapshot")
    ps.add_argument("--ref", required=True)
    ps.add_argument("--include-tests", action="store_true")
    pm = sub.add_parser("per-merge")
    pm.add_argument("--cohort", required=True)
    pm.add_argument("--labels", required=True)
    pm.add_argument("--frozen-main", required=True)
    pn = sub.add_parser("noise")
    pn.add_argument("--metrics", required=True)
    pc = sub.add_parser("compare")
    pc.add_argument("--metrics", required=True)
    pc.add_argument("--noise", required=True)
    args = ap.parse_args()

    if args.command == "controls":
        result = controls()
    elif args.command == "snapshot":
        result = analyze_ref(args.ref, include_tests=args.include_tests)
    elif args.command == "per-merge":
        result = per_merge(args.cohort, args.labels, args.frozen_main)
    elif args.command == "noise":
        result = noise(args.metrics)
    else:
        result = comparison(args.metrics, args.noise)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
