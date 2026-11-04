/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LINUX_BAKASU_SUSFS_HOOKS_H
#define _LINUX_BAKASU_SUSFS_HOOKS_H

#include <linux/types.h>

struct filename;
struct user_arg_ptr;

/* Shared by the SUSFS callers and pinned BakaSU definitions. */
int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);
int ksu_handle_execveat(int *fd, struct filename **filename, void *argv,
		       void *envp, int *flags);
int ksu_handle_execveat_sucompat(int *fd, struct filename **filename, void *argv,
				void *envp, int *flags);
int ksu_handle_post_execveat_sucompat(int *fd, struct filename **filename,
			void *argv, void *envp, int *flags, int *retval);
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);
int ksu_handle_sys_read(unsigned int fd, char __user **buf, size_t *count);
int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value);
int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);
int ksu_setup_preinit_file(struct filename **filename, struct user_arg_ptr *argv);
int ksu_preinit_handle_post_execveat(int *fd, struct filename **filename,
		void *argv, void *envp, int *flags, int *retval, int *preinit_fd);

#endif
