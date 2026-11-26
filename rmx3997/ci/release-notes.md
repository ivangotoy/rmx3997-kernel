RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- Installer: the ZIP is now stock WildKernels AnyKernel3 (`gki-2.0` `e1e9dce9`), unmodified, plus the `Image` and `rmx3997-provenance.json`, packaged the same way as the GKI kernels. The RMX installer adaptation is gone: no device, partition or boot property checks, no AVB rewrite, no booted-Android-only launcher. It flashes like any AnyKernel3 ZIP and keeps no backup of the previous boot image.
- BBRv3 now comes from WildKernels/kernel_patches (`70c394f1`, the android13-5.15-lts backport) with the GKI kernels' per-socket ctx ownership patch, as in the GKI kernels. The code was already that pair except that `tx.in_flight` was also clamped when it is written; it is now clamped only where it is read, as upstream does.
- Unicode: the WildKernels utf8 decomposition fix from the GKI kernels; zero-width characters are no longer skipped during name normalization.
- BIC TCP congestion control is built in, as in the GKI kernels (BBRv3 stays the default).
- DroidSpaces is tracked as a component; its SysV IPC KABI patch is carried in the slot 1-3 form this device needs.
- Otherwise the kernel is built from the same sources as `rmx3997-v14`: Linux 5.15.226, BakaSU `8fa29976` from the owner's fork, SUSFS `c1d1da42` (v2.4.0), NoMount `c803cbf0` (metamodule versionCode 790), Baseband Guard `48d9fdea`.

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
