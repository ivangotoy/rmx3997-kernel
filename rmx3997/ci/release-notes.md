RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- NoMount `7fce5e2c`..`6298d58a` (maxsteeel `dev`, 65 upstream commits), ported
  by hand: hash-bucket child index, rules that follow their backing file,
  refcounted leaves with RCU retirement, and upstream fixes for a NULL dentry
  dereference on cross-superblock backing children, rebind type mismatch,
  out-of-bounds readdir and positive whiteouts. The protocol stays 22. Install
  the matching NoMount metamodule build, versionCode 713
  (`NoMount-v2.2.0-dev-6298d58-713`), together with this kernel.
- SUSFS: the adbd and `jdwp-control` sockets are hidden from app UIDs. Apps can
  no longer connect to `@jdwp-control` or see `/dev/socket/adbd`. Side effect:
  JDWP debugging of apps on the phone (the Android Studio debugger) does not
  work with this kernel; `adb shell`, `logcat` and `install` are unaffected.
- Scheduler: `select_idle_capacity()` starts its scan at the CPU after the
  target (mainline `8589018acc65`).
- Wakelocks: a userspace wakelock written to `/sys/power/wake_lock` without a
  timeout now expires after 500 ms unless it is taken again; wakelocks with an
  explicit timeout and kernel wakeup sources are unchanged.
- fanotify: `CONFIG_FANOTIFY` and `CONFIG_FANOTIFY_ACCESS_PERMISSIONS`
  (`fanotify_init`, `fanotify_mark`, permission events, the
  `fs.fanotify.*` and `user.max_fanotify_*` sysctls).
- Device cgroup: `CONFIG_CGROUP_DEVICE`, the cgroup v1 `devices` controller
  (`devices.allow`, `devices.deny`, `devices.list`) for container runtimes.
- Bridge netfilter: `CONFIG_BRIDGE_NETFILTER`, `br_netfilter` built in, so
  iptables, ip6tables and conntrack can see bridged traffic
  (`net.bridge.bridge-nf-call-iptables` and related sysctls; they default
  to 0, so bridged traffic is filtered only after they are set to 1). The xt
  `physdev` match is not enabled.
- These three options normally change the layout of kernel structs that the
  stock vendor modules were built against. Here their extra state is stored
  outside those structs, so every struct of the stock kernel keeps its
  layout and the existing subsystem, counter and extension ids keep their
  values.
- Component versions in this release: AOSP `android13-5.15-lts` `f181319b`
  (Linux 5.15.223), `android13-5.15` security branch `3f0fd7f6`, BakaSU
  `548d1dda` (35259), SUSFS `fe943d15` (v2.4.0), NoMount `6298d58a`, Baseband
  Guard `028ff7fd`, BBRv3 donor `f3544ee0`, AnyKernel3 `gki-2.0` `e1e9dce9`.
  Only NoMount changed since the previous release.
- `production.config`: `CONFIG_FANOTIFY=y`,
  `CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y`, `CONFIG_CGROUP_DEVICE=y`,
  `CONFIG_BRIDGE_NETFILTER=y`; no other option changed.

## Kernel features

| Area | What is included |
| --- | --- |
| Base | Linux {version}, Android13-5.15 GKI, KMI 8: AOSP `android13-5.15-lts` plus the `android13-5.15` security fixes (November 2026 bulletin) |
| Compiler | ZyC Clang 18, Full LTO |
| Root | BakaSU (KernelSU fork), SUSFS |
| Module mounting | NoMount, protocol 22 |
| Security | Clang CFI for the kernel and OEM modules, strong stack protector, Baseband Guard |
| OEM compatibility | Stock vendor modules load unchanged: OEM security guard, sched_assist, binder strategy, F2FS appboost and compression, ZRAM and HybridSwap |
| TCP congestion control | BBRv3 (`bbr3`, default) with per-socket context ownership, BBR, CUBIC, Westwood, HTCP |
| Queue disciplines | CAKE, PIE, FQ-PIE |
| Firewall and NAT | nftables (inet, IPv4, IPv6, ARP, bridge, netdev; NAT, conntrack, FIB, TPROXY, `nft_compat` for iptables-nft), IPv6 NAT and MASQUERADE, hop-limit match, ipset, xt `set`, `LOG`, `recent`, `addrtype`, TTL target, CONNMARK |
| VPN and virtual networking | WireGuard and AmneziaWG (both built in), TUN, MACVLAN |
| Containers | User (creation requires CAP_SYS_ADMIN), IPC, PID, UTS, network and cgroup namespaces, SysV IPC, POSIX message queues, OverlayFS, FUSE, cgroup v1 `devices` controller, fanotify, bridge netfilter |
| Windows compatibility | NTSync, `/dev/ntsync` usable by apps |
| Filesystems | F2FS, ext4, EROFS, CIFS/SMB3, NFSv4 client (4.0, 4.1, 4.2), tmpfs with xattrs and POSIX ACLs |
| Memory | memfd ashmem compatibility, MGLRU built in but off by default |

## Not enabled

MGLRU (off by default), CFS bandwidth control, the cgroup PIDs controller, and automatic devtmpfs mounting.
