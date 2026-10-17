import calendar,time
def stream(t,nbytes):
    x=(t<<16)|0x330E; out=[]
    for _ in range(nbytes):
        x=(0x5DEECE66D*x+0xB)%2**48; out.append(x>>40)
    return bytes(out)
t=calendar.timegm((1997,8,16,1,52,34))
want=bytes.fromhex("C49D360886E704936A6678E1139D26B7819F7E90")
s=stream(t,20*3000+40)
for n in range(3000):
    if s[20*n:20*n+20]==want: print("disjoint idx",n)
for n in range(len(s)-20):
    if s[n:n+20]==want: print("sliding idx",n)
print(t)
