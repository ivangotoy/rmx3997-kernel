# realme 12x 5G (RMX3997, EU) kernel - Linux 5.15.223

Custom GKI-compatible kernel source for the **realme 12x 5G**, model RMX3997,
EU variant (build RMX3997_16.0.5.1300(EX01)), MediaTek Dimensity 6100+
(MT6835). The kernel follows AOSP `android13-5.15-lts`, the GKI branch this
device ships, plus the security fixes of `android13-5.15` that have not
reached the LTS branch yet, with the stock vendor modules kept loadable. Builds and releases
come from Forgejo Actions; see Releases for downloads.

> **Original repository:** https://git.digtvbg.com/ivangotoy/rmx3997-kernel (Forgejo).
> Development, CI and releases happen there.
>
> **GitHub mirror:** https://github.com/ivangotoy/rmx3997-kernel is a read-only copy,
> synced automatically from the original. Changes pushed there are overwritten;
> use the original repository for releases.

## Status

| | |
| --- | --- |
| Device | realme 12x 5G, RMX3997, EU variant (EX01), Dimensity 6100+ (MT6835) |
| Device ROM | RMX3997_16.0.5.1300(EX01) |
| Kernel | Linux 5.15.223, Android13-5.15 GKI KMI8 |
| Compiler | ZyC Clang 18.0.0git (LLVM `3dea0aa8`), Full LTO, strict CFI |
| Default TCP congestion control | `bbr3` (BBRv3 backport); upstream `bbr` still available |
| Metamodule support | NoMount protocol 22 (metamodule versionCode 647) |

## Features

**Root and security tooling**

- BakaSU (KernelSU fork) built in, SUSFS `d5df1d93`
- NoMount on the upstream track (maxsteeel `dev`), protocol 22
- Baseband Guard built in
- CFI enforced for both kernel and OEM modules, stack protector strong
- MGLRU compiled but left disabled by default

**Namespaces and containers**

- User, IPC, PID, UTS, network and cgroup namespaces; creating a user
  namespace requires CAP_SYS_ADMIN, so root container launchers keep
  working while unprivileged processes cannot create one
- SYSVIPC, POSIX_MQUEUE, OverlayFS, FUSE, NTSync
- DEVTMPFS built in and deliberately not auto-mounted
- CFS_BANDWIDTH and CGROUP_PIDS stay disabled by design

**Filesystems and storage**

- F2FS (OEM appboost and compression kept), ext4, EROFS, CIFS/SMB3
- TMPFS xattr and POSIX ACLs
- Original realme ZRAM and HybridSwap modules untouched
- memfd ashmem compatibility shim

**Networking**

- nftables built in (inet, IPv4, IPv6, ARP, bridge, netdev families, NAT,
  conntrack, FIB, TPROXY, `nft_compat` for iptables-nft)
- IPv6 NAT, MASQUERADE and hop-limit matching, ipset, xt set/LOG/recent, TTL target
- CAKE, PIE, FQ-PIE, CONNMARK
- BBRv3 (default), BBR, Westwood, HTCP, Cubic, Reno
- BBRv3 per-socket context ownership: a cloned socket never uses or frees
  its parent's BBRv3 state, and the BBRv3 loss hook is dispatched by a
  congestion-control flag instead of a name compare
- WireGuard (built in), TUN, MACVLAN

**Compatibility constraints that are deliberate**

- `task_struct` SysV IPC state uses KABI reserve slots 1-3 only. The OEM
  security guard writes slots 4-8 on every syscall, so they stay untouched.
  AOSP's `user_dumpable` flag, which upstream keeps in slot 1, lives in the
  task bitfield instead; layout and symbol CRCs are unchanged
- Binder descriptors are allocated as on the shipped kernel: the OEM
  `oplus_binder_strategy` hooks stay in charge and the upstream descriptor
  bitmap is not used, because it cannot see OEM-allocated descriptors
- `struct net` keeps the stock layout with nftables enabled: the nf_tables
  generation cursor lives in per-netns nf_tables data instead of `struct net`
- The memfd ashmem shim, dropped upstream, is kept because the shipped
  configuration enables it
- The Oplus guard modules (`oplus_security_guard` and companions) and
  `oplus_bsp_sched_assist` are retained and load unchanged under a Clang 18
  kernel built for them
- MGLRU, CFS bandwidth control and cgroup PIDs are off; enabling them is not a
  supported configuration

## Building

`rmx3997/config/production.config` is the configuration; `olddefconfig` must
reproduce it byte for byte. `rmx3997/ci/build.sh STAGE` is the build: ZyC Clang
18 with LLD, Full LTO, `-j16` inside a systemd scope (MemoryHigh 12G,
MemoryMax 16G) under a resource guard that aborts before host memory runs out.

The toolchain, the host Clang/pahole and the stock OEM module corpus used for
the ABI checks are host-local inputs pinned in `rmx3997/ci/host-inputs.json`;
they are not in the repository, so a bare clone is not a complete build
environment.

## Installing

The release ZIP is installable from a rooted, booted Android through its own
installer: it splits the active boot partition, preserves ramdisk/DT/header,
repacks with the new `Image`, verifies the original AVB metadata and writes
truthful unsigned AVB `NONE` metadata, keeping a backup under
`/data/adb/rmx3997-ak3/work.*`. It does not touch `init_boot`, `vendor_boot` or
`vbmeta`, and it does not reboot or roll back on its own.

## Verification

Every CI build checks the effective config, the CFI/LTO/MODVERSIONS and root
contract, and every imported symbol CRC of all 489 stock OEM modules against the
built `Module.symvers`; see CI builds below. Static ABI equivalence is not a
performance or power claim.

## Known limits

- BBRv3 changes TCP structure layouts that kernel symbol versioning does not
  advertise. OEM accesses were classified statically (all flagged reads
  reviewed, none unsafe), but the change is not certified for every binary
- `TCP_CC_INFO` now reports the larger BBRv3 structure
- MGLRU, CFS bandwidth control and cgroup PIDs remain off
- No performance or battery certification is claimed for the scheduling,
  filesystem, cache or logging defaults

## CI builds

`.forgejo/workflows/build-rmx3997.yml` builds the kernel on the maintainer's
own host runner (`aimax-rmx-host`). It runs only on manual dispatch or when an
`rmx3997-*` tag is pushed. Both need write access to this repository, and
there is no pull-request trigger, so outside code never runs on the runner.
Forks and mirrors skip the job.

One run does the following, and any failed gate fails the run:

1. Checks out the exact commit, optionally pinned with the `expected_sha` input.
2. Verifies the host-local inputs against `rmx3997/ci/host-inputs.json`: ZyC
   Clang 18 and LLD, the host Clang and pahole, the stock OEM module corpus
   (489 files). None of these are in the repository.
3. Runs `olddefconfig` and requires the result to equal
   `rmx3997/config/production.config` byte for byte.
4. Builds `Image` and modules with Full LTO inside a systemd scope
   (MemoryMax 16G) under `rmx3997/development/resource-guard.py`, which aborts
   the build before host memory or swap runs out.
5. Acceptance: root, SUSFS, CFI, LTO and MODVERSIONS contract, the Image's
   embedded config, required root/SUSFS/NTSync symbols, MGLRU still default-off,
   and every imported symbol CRC of all stock OEM modules against the built
   `Module.symvers`, then the struct layout gate: every named struct and union
   in the stock kernel's BTF is compared member by member with the built
   kernel, and a difference passes only if it equals the layout recorded from
   the phone-proven kernel in `rmx3997/ci/layout-approved.json`. It also fails
   if any member shares bytes with the `task_struct` reserve slots 4 to 8 that
   the OEM security guard writes. CRCs cannot see these changes; this gate
   rejects the 5.15.223 build that had SysV IPC in slot 4.
6. Packages the AnyKernel3 ZIP and fails if the kernel or any ZIP member
   contains a host build path.
7. Uploads only the ZIP and its checksum as a run artifact. A tag build also
   publishes a release with those two files.

The kernel release string comes from the built commit (`-g<sha12>`).

### Upstream updates

`rmx3997/ci/upstreams.json` lists every upstream the kernel takes code from
and the exact commit it is at: AOSP `android13-5.15-lts`, the AOSP
`android13-5.15` security branch, BakaSU, SUSFS, NoMount, Baseband Guard, the
BBRv3 donor, AnyKernel3 and ZyC Clang. `python3 rmx3997/ci/upstream.py verify`
checks that the vendored files equal those pins.

`.forgejo/workflows/upstream-rmx3997.yml` runs every Monday (and on manual
dispatch). When an upstream has moved, it builds an `auto/<date>` branch from
main with the updates applied:

- AOSP LTS: merged as a tree snapshot, like the earlier LTS merges.
- AOSP security branch: new commits that are not in LTS are cherry-picked.
- BakaSU, SUSFS, NoMount, Baseband Guard: the upstream diff since the pin is
  applied with a 3-way merge onto the local files.
- BBRv3, AnyKernel3, ZyC Clang: reported only; they need a manual port.

The branch then goes through the same config, build and acceptance gates as a
tag build, including the struct layout gate, and the ZIP is kept as a run
artifact. `olddefconfig` may add new symbols there; a change to any existing
option fails the run. The result, with the upstream commit lists, is posted
to the `Upstream updates` issue. A merge conflict or failed gate is reported
the same way. The workflow never changes main and never tags; a release is
still a manual fast-forward of main and an `rmx3997-*` tag push.

## License

The kernel source is Linux, licensed under GPL-2.0; [COPYING](COPYING) is the
short pointer this tree ships and the full text is in
[LICENSES/preferred/GPL-2.0](LICENSES/preferred/GPL-2.0). The AnyKernel3 installer scripts under
`rmx3997/development/wk-anykernel/` keep their upstream license, reproduced in
that directory. The bundled installer tools keep their own licenses and carry
provenance records beside them: avbroot (GPL-3.0), magiskboot (GPL-3.0) and
BusyBox (GPL-2.0), each with its license text and upstream source location.

The project's own build, packaging and acceptance scripts are provided under
GPL-2.0 as well, to match the kernel they operate on.

Nothing here is affiliated with or endorsed by realme, Oplus or MediaTek. No
vendor firmware, proprietary module or signing material is redistributed.

## Repository layout

`rmx3997/config/` seed configuration and KMI symbol list.
`rmx3997/build-argv.json`, `build-environment.json` recorded build invocation.
`rmx3997/delivery-provenance.json` machine-readable history of every delivery,
including superseded ones.
`rmx3997/development/` staged build, packaging and acceptance tooling, including
the WildKernels-derived installer sources in `wk-anykernel/`.
`rmx3997/installer/`, `rmx3997/provider/`, `approved-baseline.json` and the
config fragments are earlier interfaces kept for provenance; they are not
current entry points.

## History

| Release | Kernel | Change |
| --- | --- | --- |
| `rmx3997-v1` | 5.15.197 | First CI release |
| `rmx3997-v2` | 5.15.223 | Merge of AOSP `android13-5.15-lts` |
| `rmx3997-v3` | 5.15.223 | `android13-5.15` security fixes (November 2026), nftables |
| `rmx3997-v4` | 5.15.223 | BBRv3 per-socket context ownership, user namespace creation requires CAP_SYS_ADMIN |

Earlier development deliveries (baseline, networking, parity, D1, D2, E) are
recorded in `rmx3997/delivery-provenance.json`.
