import json,os,pathlib,socket,subprocess
rows=[]
def probe(label,fn,want):
    try: value=fn(); outcome='allowed'
    except PermissionError:value=None;outcome='denied'
    except OSError as exc:value=str(exc);outcome='error'
    rows.append({'probe':label,'outcome':outcome,'expected':want,'detail':value})
probe('own code read',lambda:len(pathlib.Path('app/bg_jobs.py').read_bytes()),'allowed')
probe('own write',lambda:pathlib.Path('boundary-write.txt').write_text('ok'),'allowed')
for name,path in {
 'main code':'/home/kesha/orchestra/app/bg_jobs.py',
 'main git':'/home/kesha/orchestra/.git/HEAD',
 'report':'/home/kesha/orchestra/.orchestra/tasks/V-546/report.md',
 'changelog':'/home/kesha/orchestra/CHANGELOG.md',
 'KB':'/home/kesha/orchestra/.orchestra/kb/models-and-quotas.md',
 'TODO':'/home/kesha/orchestra/TODO.md',
 'oracle':'/home/kesha/.cache/orchestra-bench-V-558/quota-reference/tests/test_quota_gate.py',
 'sibling':'/home/kesha/.cache/orchestra-bench-V-558/arm-sol/work/app/quota_gate.py',
 'db':'/home/kesha/orchestra/data/orchestra.db',
 'parent process environ':f'/proc/{os.getppid()}/environ',
 'proc root alias':'/proc/self/root/home/kesha/orchestra/app/bg_jobs.py',
}.items():probe(name,lambda p=path:len(pathlib.Path(p).read_bytes()),'denied')
probe('direct external HTTPS',lambda:socket.create_connection(('1.1.1.1',443),timeout=2).close(),'denied')
probe('dashboard TCP',lambda:socket.create_connection(('127.0.0.1',8888),timeout=2).close(),'denied')
probe('host unix socket',lambda:socket.socket(socket.AF_UNIX).close(),'denied')
if os.environ.get('BENCH_RELAY_PORT'):
    def relay(target):
        with socket.create_connection(('127.0.0.1',int(os.environ['BENCH_RELAY_PORT'])),timeout=10) as sock:
            sock.sendall(f'CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n'.encode())
            return sock.recv(1024).decode().split('\r\n')[0]
    for target,code in [('github.com:443','403'),('127.0.0.1:8888','403'),('api.anthropic.com:443','200'),('chatgpt.com:443','200')]:
        status=relay(target)
        rows.append({'probe':target,'outcome':status.split()[1],'expected':code})
print(json.dumps(rows,indent=2))
assert all(r['outcome']==r['expected'] for r in rows)
