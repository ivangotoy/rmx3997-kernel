RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- `bakasu`: now built from the owner's BakaSU fork (`ivangotoy/BakaSU`, `main`) instead of the upstream repository: `cac1e793`..`8fa29976`, now BakaSU 35463 (v4.2.0-rc3-ci14). The fork contains every upstream commit up to `cac1e793` plus its own kernel fixes. Those in code this kernel compiles: overlong and empty umount paths are refused, `init_module` keeps `-EPERM` for callers that cannot load modules, a `set_cred_ucounts` failure is reported from the root profile escape, xperm ranges that do not parse are rejected, the kernel log is read with a kmsg dump iterator, and SELinux policy changes are applied when the saved original symbols are stale. The local integration changes are unchanged.
- Nothing else changed: Linux 5.15.226, the `android13-5.15` security branch `7f10d301`, SUSFS `c1d1da42` (v2.4.0), NoMount `c803cbf0` (metamodule versionCode 790), Baseband Guard `48d9fdea`, BBRv3 and AnyKernel3 are the same as in `rmx3997-v13`, and `production.config` is unchanged.

## Kernel features

| Area | What is included |
| --- | --- |
| Base | Linux {version}, Android13-5.15 GKI, KMI 8: AOSP `android13-5.15-lts` plus the `android13-5.15` security fixes (November 2026 bulletin) |
| Compiler | ZyC Clang 18, Full LTO |
| Root | BakaSU (KernelSU fork, from the `ivangotoy/BakaSU` fork), SUSFS |
| Module mounting | NoMount, protocol 23 (metamodule versionCode 790) |
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
