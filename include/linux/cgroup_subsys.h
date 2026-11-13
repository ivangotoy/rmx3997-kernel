/* SPDX-License-Identifier: GPL-2.0 */
/*
 * List of cgroup subsystems.
 *
 * DO NOT ADD ANY SUBSYSTEM WITHOUT EXPLICIT ACKS FROM CGROUP MAINTAINERS.
 */

/*
 * This file *must* be included with SUBSYS() defined.
 */

#ifndef SUBSYS_EXT
#define SUBSYS_EXT(_x) SUBSYS(_x)
#define __SUBSYS_EXT_IS_SUBSYS
#endif

#if IS_ENABLED(CONFIG_CPUSETS)
SUBSYS(cpuset)
#endif

#if IS_ENABLED(CONFIG_CGROUP_SCHED)
SUBSYS(cpu)
#endif

#if IS_ENABLED(CONFIG_CGROUP_CPUACCT)
SUBSYS(cpuacct)
#endif

#if IS_ENABLED(CONFIG_BLK_CGROUP)
SUBSYS(io)
#endif

#if IS_ENABLED(CONFIG_MEMCG)
SUBSYS(memory)
#endif

#if IS_ENABLED(CONFIG_CGROUP_FREEZER)
SUBSYS(freezer)
#endif

#if IS_ENABLED(CONFIG_CGROUP_NET_CLASSID)
SUBSYS(net_cls)
#endif

#if IS_ENABLED(CONFIG_CGROUP_PERF)
SUBSYS(perf_event)
#endif

#if IS_ENABLED(CONFIG_CGROUP_NET_PRIO)
SUBSYS(net_prio)
#endif

#if IS_ENABLED(CONFIG_CGROUP_HUGETLB)
SUBSYS(hugetlb)
#endif

#if IS_ENABLED(CONFIG_CGROUP_PIDS)
SUBSYS(pids)
#endif

#if IS_ENABLED(CONFIG_CGROUP_RDMA)
SUBSYS(rdma)
#endif

#if IS_ENABLED(CONFIG_CGROUP_MISC)
SUBSYS(misc)
#endif

/*
 * The following subsystems are not supported on the default hierarchy.
 */
#if IS_ENABLED(CONFIG_CGROUP_DEBUG)
SUBSYS(debug)
#endif

/*
 * DO NOT ADD ANY SUBSYSTEM WITHOUT EXPLICIT ACKS FROM CGROUP MAINTAINERS.
 */

/*
 * KABI: subsystems that the prebuilt vendor modules were compiled without.
 * They are listed with SUBSYS_EXT() and must stay behind every SUBSYS()
 * entry: their ids come after CGROUP_SUBSYS_COUNT, so the ids above and the
 * arrays sized by CGROUP_SUBSYS_COUNT in struct cgroup and struct css_set
 * do not change. See struct cgroup_ext and struct css_set_ext.
 * An includer that does not define SUBSYS_EXT() gets them as SUBSYS().
 */
#if IS_ENABLED(CONFIG_CGROUP_DEVICE)
SUBSYS_EXT(devices)
#endif

#ifdef __SUBSYS_EXT_IS_SUBSYS
#undef SUBSYS_EXT
#undef __SUBSYS_EXT_IS_SUBSYS
#endif
