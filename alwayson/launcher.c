// Main executable of Perch.app. It starts the menu bar app with the project's Python and waits for it.
//
// It exists so that macOS has a real, signed app to grant camera and automation access to: a child
// process inherits the permissions of the app that started it, while Python started directly by
// launchd has no usage descriptions and is refused the camera without a prompt.
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef PROJECT_DIR
#error "compile with -DPROJECT_DIR=\"/path/to/perch\""
#endif

static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    if (chdir(PROJECT_DIR) != 0) {
        perror("perch: cannot enter " PROJECT_DIR);
        return 1;
    }
    child = fork();
    if (child < 0) {
        perror("perch: fork");
        return 1;
    }
    if (child == 0) {
        execl(PROJECT_DIR "/.venv/bin/python", "python", "menubar.py", (char *)NULL);
        perror("perch: cannot start " PROJECT_DIR "/.venv/bin/python");
        _exit(127);
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
