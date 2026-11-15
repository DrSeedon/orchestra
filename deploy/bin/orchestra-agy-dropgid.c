/* Setgid kesha helper for child worker shells spawned by agy run_command.
 * Restores rgid = egid = kesha and strips residential proxy env vars
 * before executing /bin/bash or /bin/sh.
 */
#define _GNU_SOURCE
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

static int is_allowed_shell(const char *path) {
    return strcmp(path, "/bin/bash") == 0 ||
           strcmp(path, "/usr/bin/bash") == 0 ||
           strcmp(path, "/bin/sh") == 0 ||
           strcmp(path, "/usr/bin/sh") == 0;
}

int main(int argc, char **argv) {
    if (argc < 2 || !is_allowed_shell(argv[1])) {
        fprintf(stderr, "orchestra-agy-dropgid: invalid shell target\n");
        return 113;
    }
    uid_t ruid = getuid();
    struct passwd *pw = getpwnam("kesha");
    if (ruid != 0 && (!pw || ruid != pw->pw_uid)) {
        fprintf(stderr, "orchestra-agy-dropgid: unauthorized uid %u\n", (unsigned)ruid);
        return 112;
    }
    gid_t egid = getegid();
    if (setregid(egid, egid) != 0) {
        perror("orchestra-agy-dropgid: setregid");
        return 111;
    }
    static const char *const strip_vars[] = {
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GRPC_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "grpc_proxy",
        "NO_GRPC_PROXY", "no_grpc_proxy", "BASH_ENV",
        NULL
    };
    for (int i = 0; strip_vars[i] != NULL; ++i) {
        unsetenv(strip_vars[i]);
    }
    execv(argv[1], &argv[1]);
    perror("orchestra-agy-dropgid: execv");
    return 127;
}
