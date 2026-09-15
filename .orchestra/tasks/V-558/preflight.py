import asyncio,json,os,pathlib,subprocess
from transport import Relay
HERE=pathlib.Path(__file__).resolve().parent
LAB=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
async def main():
    relay=await Relay().start()
    rows=[]
    try:
        for name in ['luna','sol','astra','opus','fable']:
            arm=LAB/('arm-'+name);cwd=arm/'work';home=arm/'home'
            source=(HERE/'probe_boundary.py').read_text().replace("'sibling':'/home/kesha/.cache/orchestra-bench-V-558/arm-sol/work/app/quota_gate.py'",f"'sibling':'/home/kesha/.cache/orchestra-bench-V-558/arm-{'luna' if name=='sol' else 'sol'}/work/app/quota_gate.py'")
            env={'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','TMPDIR':str(arm/'tmp'),'CODEX_HOME':str(home/'.codex'),'CLAUDE_CONFIG_DIR':str(home/'.claude'),'BENCH_RELAY_PORT':str(relay.port)}
            cmd=['/usr/bin/python3',str(HERE/'sandbox.py'),'--workspace',str(arm),'--cwd',str(cwd),'--port',str(relay.port),'/usr/bin/python3','-S','-c',source]
            proc=await asyncio.create_subprocess_exec(*cmd,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await proc.communicate()
            (HERE/'evidence'/f'boundary-{name}.json').write_bytes(stdout)
            (HERE/'evidence'/f'boundary-{name}.stderr').write_bytes(stderr)
            rows.append({'model':name,'boundary_rc':proc.returncode})
            if proc.returncode:raise RuntimeError(f'{name} boundary failed: {stderr.decode()}')
            (cwd/'boundary-write.txt').unlink() # own disposable probe file
    finally:
        await relay.close()
        (HERE/'evidence/relay-preflight.json').write_text(json.dumps(relay.events,indent=2)+'\n')
        (HERE/'evidence/preflight-results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows))
asyncio.run(main())
