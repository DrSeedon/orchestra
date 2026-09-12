import hashlib,io,json,os,pathlib,shutil,subprocess,tarfile
here=pathlib.Path(__file__).resolve().parent;root=here.parents[2]
lab=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
rev='9948ab52542a52bb189cec6f84bb5b45a4729351'
raw=subprocess.check_output(['git','archive',rev,'app','tests','scripts','pyproject.toml','uv.lock'],cwd=root)
rows=[]
for name in ['luna','sol','astra','opus','fable']:
 arm=lab/('arm-'+name);repo=arm/'seed';work=arm/'work';home=arm/'home'
 repo.mkdir(parents=True);home.mkdir();(arm/'tmp').mkdir()
 with tarfile.open(fileobj=io.BytesIO(raw)) as arc:arc.extractall(repo,filter='data')
 def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.STDOUT).decode().strip()
 git('init','-b','seed');git('config','user.name','Benchmark');git('config','user.email','benchmark@local.invalid')
 git('add','.');git('commit','-m','Initial benchmark snapshot')
 git('worktree','add','-b','solution',str(work))
 for path in [home/'.codex',home/'.claude']:path.mkdir(mode=0o700)
 # Private credential copies never enter a tracked worktree or evidence.
 if name in ['luna','sol','astra']:
  shutil.copyfile(pathlib.Path(os.environ['CODEX_HOME'])/'auth.json',home/'.codex/auth.json')
  os.chmod(home/'.codex/auth.json',0o600)
 else:
  shutil.copyfile(pathlib.Path.home()/'.claude/.credentials.json',home/'.claude/.credentials.json')
  os.chmod(home/'.claude/.credentials.json',0o600)
  (home/'.claude.json').write_text('{"hasCompletedOnboarding":true}')
 (home/'.gitconfig').write_text('[user]\n name = Benchmark\n email = benchmark@local.invalid\n')
 rows.append({'model':name,'root':str(arm),'cwd':str(work),'tree':git('rev-parse','HEAD^{tree}'),'history_count':git('rev-list','--count','HEAD'),'remotes':git('remote','-v')})
(here/'evidence/arms-manifest.json').write_text(json.dumps({'source_revision':rev,'prompt_sha256':hashlib.sha256((here/'prompt.txt').read_bytes()).hexdigest(),'arms':rows},indent=2)+'\n')
