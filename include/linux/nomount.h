/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_NOMOUNT_VFS_H
#define _LINUX_NOMOUNT_VFS_H
#include <linux/types.h>
struct inode;
#ifdef CONFIG_NOMOUNT
bool nomount_is_virtual_inode(const struct inode *inode);
#else
static inline bool nomount_is_virtual_inode(const struct inode *inode) { return false; }
#endif
#endif
