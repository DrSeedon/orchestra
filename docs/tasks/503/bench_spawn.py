import subprocess, time, re, os, statistics
os.chdir('/home/kesha/orchestra')
target='README.md'
data=open(target,'rb').read()
pat=re.compile(rb'worktree')
def inproc():
    t=time.perf_counter(); n=len(pat.findall(data)); return time.perf_counter()-t, n
def external():
    t=time.perf_counter()
    r=subprocess.run(['/usr/bin/grep','-c','worktree',target],capture_output=True)
    return time.perf_counter()-t, r.stdout.strip()
def true_floor():
    t=time.perf_counter(); subprocess.run(['/bin/true']); return time.perf_counter()-t, 0
A=[];B=[];C=[]
for i in range(40):                      # interleaved A/B/A/B per CLAUDE.md rule
    a,_=inproc(); A.append(a)
    b,_=external(); B.append(b)
    c,_=true_floor(); C.append(c)
f=lambda xs: f"median {statistics.median(xs)*1e6:8.1f} us  p90 {sorted(xs)[int(len(xs)*0.9)]*1e6:8.1f} us"
print("loadavg:", open('/proc/loadavg').read().split()[:3])
print("in-process regex over README :", f(A))
print("external `grep -c` same file :", f(B))
print("bare /bin/true fork+exec     :", f(C))
print("ratio external/in-process    :", round(statistics.median(B)/statistics.median(A),1))
