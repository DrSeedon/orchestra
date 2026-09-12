"""Frozen inputs and sealed overlays; never traverse submitted symlinks."""
import fnmatch
import difflib
import hashlib
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

GENERATED_DIRS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
FORBIDDEN_ROOTS = {'.bench', '.orchestra', '.git', '.env', 'AGENTS.md', 'CLAUDE.md', 'TODO.md', 'CHANGELOG.md'}


def generated(path):
    p = Path(path)
    return bool(set(p.parts) & GENERATED_DIRS) or p.suffix in {'.pyc', '.pyo'}


def inventory(root):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        relative = p.relative_to(root)
        if generated(relative):
            continue
        if p.is_symlink():
            raise ValueError(f'symlink in input/submission: {relative}')
        if p.is_file():
            result[str(relative)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def copy_tree(source, target):
    inventory(source)  # Reject escapes before copying any file.
    shutil.copytree(source, target, ignore=lambda _, names: [n for n in names if n in GENERATED_DIRS or n.endswith(('.pyc', '.pyo'))])


def build(source, target):
    target = Path(target)
    target.mkdir()
    if 'repo' in source:
        repo = source['repo']
        revision = subprocess.check_output(['git', '-C', repo, 'rev-parse', '--verify', '--end-of-options', source['revision'] + '^{commit}'], text=True).strip()
        data = subprocess.check_output(['git', '-C', repo, 'archive', revision, '--', *source['include']])
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive.getmembers():
                if Path(member.name).parts[0] in FORBIDDEN_ROOTS:
                    raise ValueError(f'forbidden snapshot path: {member.name}')
                if member.issym() or member.islnk():
                    raise ValueError(f'symlink in snapshot: {member.name}')
            archive.extractall(target, filter='data')
    else:
        root = Path(source['directory'])
        for selected in source['include']:
            if Path(selected).parts[0] in FORBIDDEN_ROOTS:
                raise ValueError(f'forbidden snapshot path: {selected}')
            original = root / selected
            ancestors = [original, *list(original.parents)[:len(original.relative_to(root).parts)]]
            if any(p.is_symlink() for p in ancestors) or not original.resolve().is_relative_to(root.resolve()):
                raise ValueError(f'symlink source: {selected}')
            dest = target / selected
            dest.parent.mkdir(parents=True, exist_ok=True)
            if original.is_dir():
                copy_tree(original, dest)
            else:
                shutil.copyfile(original, dest)
        revision = None
    files = inventory(target)
    if not files:
        raise ValueError('empty snapshot')
    return {'revision': revision, 'files': files}


def overlay(root, files):
    for relative, original in files.items():
        target = Path(root) / relative
        for parent in [target, *target.parents]:
            if parent == Path(root).parent:
                break
            if parent.is_symlink():
                raise ValueError(f'symlink overlay destination: {relative}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes(original))


def file_bytes(source):
    if isinstance(source, dict):
        revision = subprocess.check_output(['git', '-C', source['repo'], 'rev-parse', '--verify', '--end-of-options', source['revision'] + '^{commit}'], text=True).strip()
        return subprocess.check_output(['git', '-C', source['repo'], 'show', revision + ':' + source['path']])
    return Path(source).read_bytes()


def changes(before, after, allowed):
    names = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    unexpected = [p for p in names if Path(p).parts[0] == '.bench' or not any(fnmatch.fnmatchcase(p, pattern) for pattern in allowed)]
    return names, unexpected


def diff(before_root, after_root, paths):
    """Never execute Git on model-controlled .git/config or external diff drivers."""
    chunks = []
    for relative in paths:
        old = Path(before_root) / relative
        new = Path(after_root) / relative
        old_bytes = old.read_bytes() if old.is_file() else b''
        new_bytes = new.read_bytes() if new.is_file() else b''
        try:
            a = old_bytes.decode('utf-8').splitlines(keepends=True)
            b = new_bytes.decode('utf-8').splitlines(keepends=True)
        except UnicodeDecodeError:
            chunks.append(f'Binary content differs: {relative}\n')
            continue
        chunks.extend(difflib.unified_diff(a, b, fromfile='a/' + relative, tofile='b/' + relative))
    return ''.join(chunks)
