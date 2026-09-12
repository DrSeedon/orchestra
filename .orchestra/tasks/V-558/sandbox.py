"""Benchmark-only inherited Landlock/seccomp boundary; no service configuration changes."""
import argparse, ctypes as c, ctypes.util, errno, os, pathlib

class Ruleset(c.Structure):
    _fields_=[('fs',c.c_uint64),('net',c.c_uint64)]
class PathRule(c.Structure):
    _pack_=1
    _fields_=[('access',c.c_uint64),('fd',c.c_int32)]
class NetRule(c.Structure):
    _fields_=[('access',c.c_uint64),('port',c.c_uint64)]
class Arg(c.Structure):
    _fields_=[('arg',c.c_uint),('op',c.c_int),('a',c.c_uint64),('b',c.c_uint64)]

def restrict(workspace, port=0):
    libc=c.CDLL(None,use_errno=True)
    def check(r):
        if r<0: raise OSError(c.get_errno(),os.strerror(c.get_errno()))
        return r
    abi=check(libc.syscall(444,0,0,1))
    if abi<4: raise RuntimeError(f'Landlock ABI {abi}, need >=4')
    fs=(1<<15)-1
    rules=Ruleset(fs,3)
    fd=check(libc.syscall(444,c.byref(rules),c.sizeof(rules),0))
    def allow(path,access):
        if not os.path.exists(path): return
        pfd=os.open(path,os.O_PATH|os.O_CLOEXEC)
        try:
            if not os.path.isdir(path): access &= (1<<0)|(1<<1)|(1<<2)|(1<<14)
            rule=PathRule(access,pfd)
            check(libc.syscall(445,fd,1,c.byref(rule),0))
        finally: os.close(pfd)
    read=(1<<0)|(1<<2)|(1<<3)
    for path in ['/usr','/lib','/lib64','/bin','/opt/orchestra/runtimes',
                 '/etc/ssl','/etc/ld.so.cache','/etc/resolv.conf','/etc/hosts','/etc/nsswitch.conf',
                 '/proc/self','/proc/thread-self','/dev/urandom','/dev/random']:
        allow(path,read)
    for path in ['/dev/null','/dev/zero']: allow(path,read|(1<<1))
    allow(str(pathlib.Path(workspace).resolve()),fs)
    if port:
        rule=NetRule(2,port)
        check(libc.syscall(445,fd,2,c.byref(rule),0))
    check(libc.prctl(38,1,0,0,0))
    check(libc.syscall(446,fd,0))
    os.close(fd)
    # Block process-memory/handle escape and AF_UNIX access to host service sockets.
    sec=c.CDLL(ctypes.util.find_library('seccomp'),use_errno=True)
    sec.seccomp_init.argtypes=[c.c_uint32]; sec.seccomp_init.restype=c.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes=[c.c_char_p];sec.seccomp_syscall_resolve_name.restype=c.c_int
    sec.seccomp_rule_add_array.argtypes=[c.c_void_p,c.c_uint32,c.c_int,c.c_uint,c.POINTER(Arg)]
    sec.seccomp_load.argtypes=[c.c_void_p];sec.seccomp_release.argtypes=[c.c_void_p]
    ctx=sec.seccomp_init(0x7fff0000)
    if not ctx: raise RuntimeError('seccomp_init failed')
    try:
        for name in ['ptrace','process_vm_readv','process_vm_writev','pidfd_getfd','open_by_handle_at']:
            nr=sec.seccomp_syscall_resolve_name(name.encode())
            if nr>=0 and sec.seccomp_rule_add_array(ctx,0x50000|errno.EPERM,nr,0,None): raise RuntimeError(name)
        arg=Arg(0,4,1,0) # SCMP_CMP_EQ, AF_UNIX
        nr=sec.seccomp_syscall_resolve_name(b'socket')
        if sec.seccomp_rule_add_array(ctx,0x50000|errno.EPERM,nr,1,c.byref(arg)): raise RuntimeError('socket rule')
        if sec.seccomp_load(ctx): raise RuntimeError('seccomp_load failed')
    finally: sec.seccomp_release(ctx)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--cwd')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    restrict(args.workspace,args.port)
    os.chdir(args.cwd or args.workspace)
    os.execvpe(args.command[0],args.command,os.environ)
