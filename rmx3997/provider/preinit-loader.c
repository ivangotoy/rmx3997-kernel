/* SPDX-License-Identifier: GPL-2.0-only */
/* Static ELF executed by BakaSU preinit, never its symbol-binding insmod path.
 * provider-inputs.h is generated from final reviewed artifacts by the packer.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

struct provider_input { const char *path, *name, *sha256; };
#include "provider-inputs.h"

#ifndef HASH_PROGRAM
#define HASH_PROGRAM "/system/bin/toybox"
#endif
#ifndef NOTES_PATH
#define NOTES_PATH "/sys/kernel/notes"
#endif
#ifndef MODULES_PATH
#define MODULES_PATH "/sys/module/"
#endif

/* Hash the same open inode that will be loaded, without reopening its path.
 * System toybox is on the existing verified system mount. No shell is used.
 */
static int verify_fd(int fd, const char *expected)
{
	int pipefd[2], status;
	pid_t pid;
	char output[256];
	size_t used = 0;
	ssize_t n;

	if (strlen(expected) != 64 || lseek(fd, 0, SEEK_SET) < 0 || pipe(pipefd))
		return -1;
	pid = fork();
	if (pid < 0) { close(pipefd[0]); close(pipefd[1]); return -1; }
	if (!pid) {
		if (dup2(fd, STDIN_FILENO) < 0 || dup2(pipefd[1], STDOUT_FILENO) < 0)
			_exit(126);
		close(pipefd[0]); close(pipefd[1]);
		execl(HASH_PROGRAM, HASH_PROGRAM, "sha256sum", (char *)NULL);
		_exit(127);
	}
	close(pipefd[1]);
	while (used < sizeof(output)) {
		n = read(pipefd[0], output + used, sizeof(output) - used);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) break;
		used += n;
	}
	close(pipefd[0]);
	while (waitpid(pid, &status, 0) < 0) if (errno != EINTR) return -1;
	return !WIFEXITED(status) || WEXITSTATUS(status) || used < 65 || used == sizeof(output) ||
		memcmp(output, expected, 64) || output[64] != ' ' ||
		lseek(fd, 0, SEEK_SET) < 0 ? -1 : 0;
}

static int already_loaded(const char *name)
{
	char path[256];
	struct stat st;
	if (snprintf(path, sizeof(path), "%s%s", MODULES_PATH, name) >= (int)sizeof(path))
		return 0;
	return !stat(path, &st) && S_ISDIR(st.st_mode);
}

#ifndef PROVIDER_LOAD
#define PROVIDER_LOAD(fd) syscall(SYS_finit_module, (fd), "", 0)
#endif

int main(void)
{
	int fds[sizeof(provider_inputs) / sizeof(provider_inputs[0])];
	unsigned int i, count = sizeof(fds) / sizeof(fds[0]);
	struct stat st;
	int notes, result = 1;
	const char *preinit = getenv("KSU_PREINIT");

	if (getuid() || !preinit || strcmp(preinit, "1"))
		return 1;
	/* Never unload or disturb an existing provider or active swap device. */
	if (already_loaded("oplus_bsp_hybridswap_zram"))
		return 0;
	notes = open(NOTES_PATH, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (notes < 0) return 1;
	result = verify_fd(notes, PROVIDER_KERNEL_NOTES_SHA256);
	close(notes);
	if (result) return 1;
	result = 1;
	for (i = 0; i < count; i++) fds[i] = -1;
	/* Authenticate the entire closure before the first module side effect. */
	for (i = 0; i < count; i++) {
		fds[i] = open(provider_inputs[i].path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
		if (fds[i] < 0 || fstat(fds[i], &st) || !S_ISREG(st.st_mode) ||
		    st.st_uid || (st.st_mode & 022) ||
		    verify_fd(fds[i], provider_inputs[i].sha256))
			goto out;
	}
	for (i = 0; i < count; i++) {
		if (already_loaded(provider_inputs[i].name)) continue;
		if (PROVIDER_LOAD(fds[i]) && errno != EEXIST) {
			fprintf(stderr, "RMX provider load failed: %s errno=%d; OEM boot continues\n",
				provider_inputs[i].name, errno);
			goto out;
		}
	}
	result = 0;
out:
	for (i = 0; i < count; i++) if (fds[i] >= 0) close(fds[i]);
	return result;
}
