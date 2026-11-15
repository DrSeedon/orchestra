/* Setgid agy_oauth launcher for /usr/local/libexec/agy-vendor.elf.
 * Sets rgid = egid = agy_oauth so kernel socket skgid is agy_oauth
 * (enforcing nftables direct-egress block) while keeping rgid == egid
 * so child GNU bash is not in privileged mode and honors BASH_ENV.
 */
#define _GNU_SOURCE
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef AGY_VENDOR_ELF
#define AGY_VENDOR_ELF "/usr/local/libexec/agy-vendor.elf"
#endif

int main(int argc, char **argv) {
    (void)argc;
    uid_t ruid = getuid();
    struct passwd *pw = getpwnam("kesha");
    if (ruid != 0 && (!pw || ruid != pw->pw_uid)) {
        fprintf(stderr, "orchestra-agy-exec: unauthorized uid %u\n", (unsigned)ruid);
        return 112;
    }
    gid_t egid = getegid();
    if (setregid(egid, egid) != 0) {
        perror("orchestra-agy-exec: setregid");
        return 111;
    }
    argv[0] = (char *)AGY_VENDOR_ELF;
    execv(AGY_VENDOR_ELF, argv);
    perror("orchestra-agy-exec: execv");
    return 127;
}
