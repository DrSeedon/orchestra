"""Build disposable historical controls, never import live application state."""
import io, json, os, pathlib, subprocess, tarfile
root=pathlib.Path(__file__).resolve().parents[3]
lab=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
lab.mkdir(parents=True,exist_ok=True)
revs={'baseline':'1fc6beb677cbe7455df801607f7694fb6131963b','reference':'180a5a4f1c9372ebf557ee72d859fb2308bd4966'}
for label,rev in revs.items():
    dest=lab/label
    dest.mkdir(exist_ok=True)
    raw=subprocess.check_output(['git','archive',rev,'app','tests','scripts','pyproject.toml','uv.lock'],cwd=root)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive: archive.extractall(dest,filter='data')
    oracle=subprocess.check_output(['git','show',revs['reference']+':tests/test_pidfd_leaks.py'],cwd=root)
    (dest/'tests/test_pidfd_leaks.py').write_bytes(oracle)
print(json.dumps({'lab':str(lab),'revisions':revs},indent=2))
