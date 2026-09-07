"""Install the approved standalone skill. Archive exact replaced paths; never delete sources."""
from pathlib import Path
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
import sys
import uuid


def install(content: bytes) -> dict:
    home=Path.home()
    archive=home/'.orchestra/skill-archive'/('html-unification-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6])
    changed=[]
    def preserve(path: Path):
        if not path.exists() and not path.is_symlink():
            return
        target=archive/path.relative_to(home)
        target.parent.mkdir(parents=True,exist_ok=True)
        path.rename(target)
        changed.append({'path':str(path),'archive':str(target)})

    root=home/'.claude/skills/html-artifacts'
    if root.is_symlink() or not root.is_dir() or not (root/'SKILL.md').is_file() or (root/'SKILL.md').read_bytes()!=content:
        preserve(root)
        root.mkdir(parents=True,exist_ok=True)
        tmp=root/('.SKILL-'+uuid.uuid4().hex+'.tmp')
        tmp.write_bytes(content)
        os.replace(tmp,root/'SKILL.md')
    for directory in ['.codex','.agents']:
        alias=home/directory/'skills/html-artifacts'
        if alias.is_symlink() and alias.resolve()==root.resolve():
            continue
        preserve(alias)
        alias.parent.mkdir(parents=True,exist_ok=True)
        alias.symlink_to(root,target_is_directory=True)
    retired=['frontend-design','apple-design','diagram-design','3d-frontend','3D-frontend','eli5','playground','quickdesign']
    for directory in ['.claude','.codex','.agents']:
        for name in retired:
            preserve(home/directory/'skills'/name)
    checks={}
    for directory in ['.claude','.codex','.agents']:
        file=home/directory/'skills/html-artifacts/SKILL.md'
        assert file.read_bytes()==content
        checks[directory]={'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    return {'home':str(home),'checks':checks,'archived':changed,'archive_root':str(archive)}


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Usage: install_global.py /path/to/approved/SKILL.md')
    print(json.dumps(install(Path(sys.argv[1]).read_bytes()),ensure_ascii=False,indent=2))
