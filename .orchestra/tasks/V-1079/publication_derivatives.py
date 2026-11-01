"""Preserve raw evidence privately; replace runtime path/identity in public copies.

No lines are removed or appended to evidence. Raw originals are under the
explicitly gitignored private-verbatim directory and must not be force-added.
The manifest contains hashes/counts rather than the removed literals.
"""
import hashlib
import json
from pathlib import Path
import socket

TASK = Path(__file__).resolve().parent
PRIVATE = TASK / 'private-verbatim'
PRIVATE.mkdir(exist_ok=True)
home = Path.home()
replacements = (
    (str(home), '/home/<runtime-user-redacted>'),
    (home.name, '<runtime-user-redacted>'),
    (socket.gethostname(), '<runtime-host-redacted>'),
)
manifest_path = TASK / 'publication-redactions.json'
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
for path in sorted(TASK.rglob('*')):
    if not path.is_file() or any(part in ('tmp', '__pycache__', 'private-verbatim')
                                for part in path.relative_to(TASK).parts):
        continue
    if path == manifest_path:
        continue
    raw = path.read_bytes()
    original = raw.decode()
    derivative = original
    for literal, marker in replacements:
        derivative = derivative.replace(literal, marker)
    if derivative == original:
        continue
    published = derivative.encode()
    relative = path.relative_to(TASK)
    archive = PRIVATE / relative
    if archive.exists() and archive.read_bytes() != raw:
        archive = archive.with_name(archive.name + '.' + hashlib.sha256(raw).hexdigest()[:12])
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(raw)
    assert original.count('\n') == derivative.count('\n')
    entry = {
        'raw_private_file': str(archive.relative_to(TASK)),
        'raw_sha256': hashlib.sha256(raw).hexdigest(),
        'published_sha256': hashlib.sha256(published).hexdigest(),
        'newline_count': original.count('\n'),
        'derivative': 'runtime identity/path redaction only; every line preserved',
    }
    manifest.setdefault(str(relative), []).append(entry)
    path.write_bytes(published)
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
print('Publication derivatives updated; changed files: ' + str(len(manifest)))
print('Verbatim originals: gitignored private-verbatim/; do not force-add')
