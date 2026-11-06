# RMX3997 kernel - Android 13 / Linux 5.15.197

Custom GKI-compatible kernel source for the Realme RMX3997 (MediaTek MT6835),
built from the Android13-5.15 branch. Every delivery listed here was flashed and
verified on hardware, not only built.

## Status

| | |
| --- | --- |
| Kernel | Linux 5.15.197, Android13 KMI8 (`5.15.197-android13-8-g7bdd6d06fa9d-dirty`) |
| Compiler | ZyC Clang 18.0.0git (LLVM `3dea0aa8`), Full LTO, strict CFI |
| Default TCP congestion control | `bbr3` (BBRv3 backport); upstream `bbr` still available |
| Metamodule support | NoMount protocol 22 (metamodule versionCode 647) |
| Phone status | Booted on slot B, full partition image flashed and read back identical |

Current delivery:

| Artifact | SHA-256 |
| --- | --- |
| `RMX3997-5.15.197-E-ZYC-BBRV3.zip` | `85079edee98ee7e25c7a2d6fe2479f749528eb6bdc985b127ca489ad686260a1` |
| Raw ARM64 `Image` | `c3ff239ac2e96b9e90b8ee41c5afc83415d380c1e5263d329bac51467b419dbd` |
| Effective config | `1156a9cbaf11bd605baa7b6965e38b9408b8540090a4043099ce688da26c07e7` |
| `boot_b` partition image (64 MiB) | `585515f7e96989adedce0e1e6c16e9305912528d080fa850ad61559a221ecf49` |

The previous delivery (D2, identical source without BBRv3, stock-CTF-safe and
phone-confirmed) stays usable as a fallback:
`boot_b` image `df8e83eaec4542dfa590a47b7bf2a3c8b732a10b6d422465150103ab37735f51`.

## Features

**Root and security tooling**

- BakaSU (KernelSU fork) built in, SUSFS `d5df1d93`
- NoMount on the upstream track (maxsteeel `dev`), protocol 22
- Baseband Guard built in
- CFI enforced for both kernel and OEM modules, stack protector strong
- MGLRU compiled but left disabled by default

**Namespaces and containers**

- USER_NS, IPC_NS, PID_NS, CGROUP_NS, UTS_NS
- SYSVIPC, POSIX_MQUEUE, NTSync
- DEVTMPFS built in and deliberately not auto-mounted
- CFS_BANDWIDTH and CGROUP_PIDS stay disabled by design

**Filesystems and storage**

- CIFS/SMB3, F2FS with OEM module compatibility preserved
- TMPFS xattr and POSIX ACLs
- Original Realme ZRAM and HybridSwap modules untouched

**Networking**

- IPv6 NAT, MASQUERADE and hop-limit matching, ipset, xt set/LOG/recent, TTL target
- CAKE, PIE, FQ-PIE, CONNMARK
- BBRv3 (default), BBR, Westwood, HTCP, Cubic, Reno
- MACVLAN

**Compatibility constraints that are deliberate**

- `task_struct` IPC state uses reserve slots 1-3 only; the OEM guard keeps
  slots 4-8, which is what keeps the stock vendor modules loading
- The Oplus guard modules (`oplus_security_guard` and companions) and
  `oplus_bsp_sched_assist` are retained and load unchanged under a Clang 18
  kernel built for them
- MGLRU, CFS bandwidth control and cgroup PIDs are off; enabling them is not a
  supported configuration

## Building

`config/production.config` is the canonical seed. It matches the shipped
effective config byte for byte apart from one documented relocation:
`CONFIG_UNUSED_KSYMS_WHITELIST="rmx3997/config/abi-symbol-list.txt"`.

Build prerequisites are external: the retained workspace supplies
`kernel/build`, `kernel/prebuilts` (Clang r450784e for host tools, NDK r23),
ABI baselines and the checker corpus. A bare clone is not a complete toolchain.

```sh
export TMPDIR="$STAGE/scratch" PYTHONPYCACHEPREFIX="$STAGE/pycache"
python3 rmx3997/development/prepare-stage.py --ancestor "$ANCESTOR" --stage "$STAGE" --config-only
python3 rmx3997/development/build-stage.py "$STAGE" build
```

`prepare-stage.py` selects the seed, regenerates the KMI whitelist through the
tracked flattener and binds `stage/out/abi_symbollist.raw` before the real
`olddefconfig`. `build-stage.py` waits for available memory, then runs the
retained hard-abort resource guard. Recent builds run at `-j16` under
`MemoryHigh=12G`, `MemoryMax=16G`, `MemorySwapMax=24G`, with `-j8` as the retry.

Regenerating a config is not a rebuild, and SCM-derived release strings and the
embedded config can change Image bytes: a new checkout does not reproduce the
shipped binary identity.

## Installing

Two paths, both verified on the phone.

**fastbootd (fast, needs a bootable kernel)**

```sh
adb reboot fastboot
fastboot flash boot_b boot_b-E-ZYC-BBRV3.img
fastboot reboot
```

Userspace fastboot runs from the recovery ramdisk, so it only exists while the
boot partition it would replace still boots. It cannot rescue a broken kernel.

**Preloader mode (kernel independent)**

Write the same 64 MiB `boot_b` partition image with a MediaTek download tool in
preloader mode, `Download Only`, selecting `boot_b`. This is the recovery path
when a kernel does not boot. Slot A still carries the stock kernel.

**AnyKernel ZIP**

The ZIP remains installable from a rooted, booted Android through its own
installer: it splits the active boot partition, preserves ramdisk/DT/header,
repacks with the new `Image`, verifies the original AVB metadata and writes
truthful unsigned AVB `NONE` metadata, keeping a backup under
`/data/adb/rmx3997-ak3/work.*`. It does not touch `init_boot`, `vendor_boot` or
`vbmeta`, and it does not reboot or roll back on its own.

## Verification

Every delivery is checked before it reaches the phone:

- Build under the retained memory guard, with the effective config compared to
  the seed
- 463 stock OEM binaries and modules checked for imported symbol CRCs;
  `Module.symvers` compared against the previous delivery
- Required public struct layouts, plus BTF layout comparison where applicable
- CFI runtime interface compared against the Clang 14-built OEM modules
- QEMU guest run of the actual `Image`: CFI negative test, OEM module loads,
  NoMount runtime, networking and container features
- Installer, AVB footer and full payload verification
- After flashing: boot completion, live config hash, CFI failure count, OEM
  guard modules, NoMount protocol, and a container workload with networking

Capability claims are limited to what was measured. Static equivalence of a
struct is not a performance or power claim, and a guest run is not hardware.

## Known limits

- Bootloader fastboot is not available on retail firmware; access is gated by
  OEM-signed authorization, so flashing uses fastbootd or preloader mode
- BBRv3 changes TCP structure layouts that kernel symbol versioning does not
  advertise. OEM accesses were classified statically (all flagged reads
  reviewed, none unsafe), but the change is not certified for every binary
- `TCP_CC_INFO` now reports the larger BBRv3 structure
- MGLRU, CFS bandwidth control and cgroup PIDs remain off
- No performance or battery certification is claimed for the scheduling,
  filesystem, cache or logging defaults

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

| Delivery | Change | Result |
| --- | --- | --- |
| Baseline | BakaSU, SUSFS, NTSync on the stock configuration | Booted |
| Networking | xt addrtype and the container networking set | Booted |
| PARITY-B | NP3/diting configuration parity, upstream NoMount | Booted |
| D1 | NoMount `dev` `3f8b5d1`, WildKernels parity items | Booted |
| D2 | Same source on ZyC Clang 18 | Booted |
| E | BBRv3 backport, `bbr3` default | Booted, current |

IPC slot and guard-module experiments that came before this are recorded in the
provenance file together with their outcomes.
