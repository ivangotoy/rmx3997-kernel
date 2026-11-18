RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- `aosp-security` (`android13-5.15`): `3f0fd7f6`..`3540cf72`, 3 commits
  applied (Bluetooth L2CAP: refuse `__l2cap_chan_add` if the channel already
  has a connection; L2CAP: access `chan->conn` safely in get/setsockopt;
  RFCOMM: connect the session socket without `rfcomm_mutex`).
- `bakasu` (`main`): `548d1dda`..`5d6d1843`, 2 upstream commits, now BakaSU
  35261 (fix the return type and header install path of preinit, check
  `ksu_handle_vfs_fstat`).
- `nomount` (`dev`): `6298d58a`..`9ff48a32`, 63 upstream commits, now NoMount
  protocol 23 (rules whose backing path is virtual are rejected, native files
  resolved from their parent, out-of-bounds read fix when selecting a rule
  from a single-element array, leaf reuse during revalidation; file handles
  are not encoded for virtual inodes, rename targets and hardlinks on virtual
  inodes are refused, async direct I/O on virtual files is rejected, rule
  paths, flags and UID ranges are validated, dot path components are
  rejected, readdir reports the real file type). Install the NoMount
  metamodule build with versionCode 775 together with this kernel.
- `susfs` (`gki-android13-5.15`): `fe943d15`..`c1d1da42`, 3 upstream commits,
  still SUSFS v2.4.0: new sus_path uid filter
  (`CMD_SUSFS_SET_SUS_PATH_UID_FILTER` takes a comma-separated list of app
  package names; the added sus paths are hidden from every other app UID),
  and the SELinux hide path covers `setxattr` as it already covered
  `setprocattr`. The adbd socket hiding of the previous release is kept.
- `bbrv3` donor: pin moved `f3544ee0`..`3e7e48f0` after review; the BBRv3
  patches this kernel carries are unchanged there, so no code changed.
- Component versions in this release: AOSP `android13-5.15-lts` `f181319b`
  (Linux 5.15.223), `android13-5.15` security branch `3540cf72`, BakaSU
  `5d6d1843` (35261), SUSFS `c1d1da42` (v2.4.0), NoMount `9ff48a32`, Baseband
  Guard `028ff7fd`, BBRv3 donor `3e7e48f0`, AnyKernel3 `gki-2.0` `e1e9dce9`.
- `production.config`: unchanged.

## Kernel features

| Area | What is included |
| --- | --- |
| Base | Linux {version}, Android13-5.15 GKI, KMI 8: AOSP `android13-5.15-lts` plus the `android13-5.15` security fixes (November 2026 bulletin) |
| Compiler | ZyC Clang 18, Full LTO |
| Root | BakaSU (KernelSU fork), SUSFS |
| Module mounting | NoMount, protocol 23 |
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
