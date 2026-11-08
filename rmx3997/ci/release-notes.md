RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- AmneziaWG built in, next to WireGuard. AmneziaWG is a WireGuard fork that
  adds traffic obfuscation (junk packets, randomized headers and padding)
  against deep packet inspection. The driver is
  `amneziawg-linux-kernel-module` v3.1.20260906 (commit `4569c4c67f3a`),
  using the kernel's own crypto library. Interfaces use the `amneziawg` link
  type and are configured with `awg` and `awg-quick` from `amneziawg-tools`;
  plain WireGuard interfaces and `wg` keep working unchanged.

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
| Containers | User (creation requires CAP_SYS_ADMIN), IPC, PID, UTS, network and cgroup namespaces, SysV IPC, POSIX message queues, OverlayFS, FUSE |
| Windows compatibility | NTSync, `/dev/ntsync` usable by apps |
| Filesystems | F2FS, ext4, EROFS, CIFS/SMB3, NFSv4 client (4.0, 4.1, 4.2), tmpfs with xattrs and POSIX ACLs |
| Memory | memfd ashmem compatibility, MGLRU built in but off by default |

## Not enabled

MGLRU (off by default), CFS bandwidth control, the cgroup PIDs controller, and automatic devtmpfs mounting.
