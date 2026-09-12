"""Restore old database-dependent assembly / drop saved parent, then restore bytes."""
import os
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[3]
env={**os.environ,'UV_PROJECT_ENVIRONMENT':'/home/kesha/orchestra/.venv'}
cases=[('app/manager.py',lambda _: subprocess.check_output(['git','show','a1674c4c:app/manager.py']),
        'tests/test_manager.py::TestPromptSourceStability::test_database_changes_preserve_prompt_bytes[pm-glava]'),
       ('app/session.py',lambda b:b.replace(b'                            parent_name=self.parent_name or None,\n',b''),
        'tests/test_hot_apply.py::test_resume_preserves_saved_parent_identity')]
for file,mutate,test in cases:
 p=root/file;old=p.read_bytes()
 try:
  mutated=mutate(old)
  if file=='app/manager.py':
   # Restore only removed state injection; the old model helper was also deleted.
   mutated=mutated.replace(b'    available_models_block,\n',b'').replace(b'        base += f"\\n\\n{available_models_block()}"\n',b'')
  assert mutated!=old
  p.write_bytes(mutated)
  result=subprocess.run(['uv','run','--frozen','python','-m','pytest',test,'-q'],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  print('MUTATION',file,'RETURN_CODE',result.returncode,flush=True)
  print(result.stdout.decode(),flush=True)
  assert result.returncode==1
 finally:p.write_bytes(old)
