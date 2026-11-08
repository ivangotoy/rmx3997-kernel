/* SPDX-License-Identifier: GPL-2.0 */
/*
 * In-tree build glue for AmneziaWG, force-included after compat/compat.h.
 *
 * Android common kernels keep the frozen 5.15 KMI and do not carry every
 * 5.15.y backport that compat/compat.h assumes from the sublevel; Kbuild
 * detects the missing ones from the kernel headers.
 */
#ifndef _AMNEZIAWG_INTREE_H
#define _AMNEZIAWG_INTREE_H

#ifdef COMPAT_NO_DEV_STATS_INC
#undef DEV_STATS_INC
#define DEV_STATS_INC(DEV, FIELD) ++DEV->stats.FIELD
#undef DEV_STATS_ADD
#define DEV_STATS_ADD(DEV, FIELD, VAL) DEV->stats.FIELD += VAL
#endif

#ifdef COMPAT_NO_TIMER_DELETE_SYNC
#define timer_delete_sync(timer) del_timer_sync(timer)
#endif

#endif /* _AMNEZIAWG_INTREE_H */
