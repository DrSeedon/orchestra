import io,json,pathlib,subprocess,tarfile
root=pathlib.Path(__file__).resolve().parents[3]
lab=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
revs={'quota-baseline':'9948ab52542a52bb189cec6f84bb5b45a4729351','quota-reference':'084a989edad3164192311669080d9aba6af9e6da'}
for label,rev in revs.items():
 dest=lab/label;dest.mkdir(exist_ok=True)
 raw=subprocess.check_output(['git','archive',rev,'app','tests','scripts','pyproject.toml','uv.lock'],cwd=root)
 with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(dest,filter='data')
 for name in ['test_quota_gate.py','test_quota_map_api.py','conftest.py']:
  (dest/'tests'/name).write_bytes(subprocess.check_output(['git','show',revs['quota-reference']+':tests/'+name],cwd=root))
print(json.dumps(revs,indent=2))
