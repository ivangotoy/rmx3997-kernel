RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- Linux 5.15.225 to 5.15.226: merge of AOSP `android13-5.15-lts` `0d108e1e`..`52f96c99`. The merge keeps the OEM F2FS compression and dedup out-of-place checks beside the new forced out-of-place update for compressed files, and the ucount rlimit fixes work on the extended ucount counters.
- Stock struct layouts kept for vendor modules: where an LTS fix changed a struct of the stock kernel, the fix is kept and its new state lives outside the struct (behind it in the same allocation, in padding, in an existing member or as a function argument). Covered: `regulator_irq`, `hiddev`, `damon_ctx`, `wacom_hdev_data`, `pk_device` and `pcmidi_snd`, `tipc_member`, `assoc_array_edit`, `policy_dbs_info`, `ifa6_config`, `skb_gso_cb`, `ovl_aio_req`, `ovl_lookup_data`, `ovl_readdir_data`, `its_baser` and `its_node`, `vgic_irq`, `kvm_vcpu_arch`.
- `aosp-security` (`android13-5.15`): `3540cf72`..`7f10d301`, 65 commits applied, 1 already present through the LTS merge: wrapfd driver updates (the driver is not enabled in this kernel) and `anon_inode_getfile_secure()`.
- `bakasu` (`main`): `7b65bde0`..`cac1e793`, 24 upstream commits, now BakaSU 35286 (v4.2.0-rc3): SELinux hide split into a SUSFS and an automatic variant, `inode_setxattr` LSM hook, SUSFS priority and sus_path uid filters refreshed after the manager is tracked, logd may read root process attributes, SELinux policy generation tracking fixes.
- `nomount` (`dev`): `9ff48a32`..`c803cbf0`, 15 upstream commits, still NoMount protocol 23: virtual backing paths resolve to their real object, backing directory lookups are proxied, rename targets are rejected before rebinding, rules whose backing was replaced are rebound, native parents are pinned with full paths. Install the NoMount metamodule build with versionCode 790 together with this kernel.
- `baseband-guard` (`main`): `028ff7fd`..`48d9fdea`, 1 upstream commit (version guards for newer kernels; no change for 5.15).
- Component versions in this release: AOSP `android13-5.15-lts` `52f96c99` (Linux 5.15.226), `android13-5.15` security branch `7f10d301`, BakaSU `cac1e793` (35286), SUSFS `c1d1da42` (v2.4.0), NoMount `c803cbf0`, Baseband Guard `48d9fdea`, BBRv3 donor `efc078ab`, AnyKernel3 `gki-2.0` `e1e9dce9`.
- `production.config` refreshed with `olddefconfig`: only the version header changed and one existing BakaSU option moved within its menu; no option was added, removed or changed.

## Kernel features

| Area | What is included |
| --- | --- |
| Base | Linux {version}, Android13-5.15 GKI, KMI 8: AOSP `android13-5.15-lts` plus the `android13-5.15` security fixes (November 2026 bulletin) |
| Compiler | ZyC Clang 18, Full LTO |
| Root | BakaSU (KernelSU fork), SUSFS |
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
