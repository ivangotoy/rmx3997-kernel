RMX3997 kernel **{kernel}** for the realme 12x 5G (RMX3997, EU), built by Forgejo Actions from commit `{commit}`.

The release has two files: the AnyKernel3 ZIP and its SHA-256 checksum.

## Changes in this release

- `bakasu` (`main`): `5d6d1843`..`7b65bde0`, 1 upstream commit.
- `production.config` refreshed with `olddefconfig` for the new upstream code: only new symbols were added, no existing option changed.
- Other changes on main since the previous release:
  - can: keep the stock can_skb_priv and uniqframe layouts
  - tipc: keep the stock tipc_crypto layout
  - pinctrl: sunxi: keep the stock sunxi_pinctrl layout
  - strparser: keep the stock strparser flag bitfields
  - HID: steam: keep the stock steam_device layout
  - netlink: keep the stock netlink_compare_arg layout
  - kprobes: keep the stock kprobe_blacklist_entry layout
  - tracing: keep the stock field_var_hist layout
  - f2fs: keep the gc_thread pointer layout of f2fs_sb_info
  - genetlink: keep the stock ctrl_dump_policy_ctx layout
  - bridge: keep the stock net_bridge and br_frame_type layouts
  - cdc-acm: keep the stock struct acm layout
  - Merge AOSP android13-5.15-lts 0d108e1e8c7b (5.15.225)
  - nomount: report encode_fh failure as FILEID_INVALID
  - upstream: nomount 00e7c5d4fdbf..9ff48a329f36
  - update-binary: say why the backend stops before any work
  - install-on-device.sh: say why the installer stops
  - susfs: update to gki-android13-5.15 c1d1da42 (v2.4.0)
  - upstream: nomount 6298d58af34a..00e7c5d4fdbf
  - upstream: bakasu 548d1dda060c..5d6d1843c893
  - UPSTREAM: Bluetooth: L2CAP: refuse __l2cap_chan_add if chan already has conn
  - UPSTREAM: Bluetooth: L2CAP: access chan->conn safely in get/setsockopt
  - UPSTREAM: Bluetooth: RFCOMM: connect the session socket without rfcomm_mutex

## Kernel features

| Area | What is included |
| --- | --- |
| Base | Linux {version}, Android13-5.15 GKI, KMI 8: AOSP `android13-5.15-lts` plus the `android13-5.15` security fixes (November 2026 bulletin) |
| Compiler | ZyC Clang 18, Full LTO |
| Root | BakaSU (KernelSU fork), SUSFS |
| Module mounting | NoMount, protocol 23 (metamodule versionCode 775) |
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
