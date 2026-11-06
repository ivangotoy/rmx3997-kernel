# RMX3997 phone-confirmed kernel source

The current delivery is Linux 5.15.197 / Android13 KMI8 built with ZyC Clang
18.0.0git (LLVM `3dea0aa8`) and Full LTO with strict CFI. It carries built-in
BakaSU/SUSFS, NTSync, SYSVIPC, POSIX_MQUEUE, IPC_NS and PID_NS, upstream
NoMount (maxsteeel `dev` `3f8b5d1`, protocol 22, metamodule versionCode 647),
NP3/diting configuration parity (USER_NS, DEVTMPFS not auto-mounted, TMPFS
xattr/ACL, IPv6 NAT/MASQUERADE/HL, ipset, xt set/LOG/recent, CAKE, CIFS,
Baseband Guard `028ff7fd`), the applicable WildKernels parity items (MACVLAN,
Westwood/HTCP, TTL/HL, CONNMARK, PIE/FQ-PIE, KSU toolkit, WildKernels tuning
patches) and the BBRv3 TCP congestion-control backport, which is the default
congestion control (`bbr3`; upstream BBR remains available). IPC uses
task_struct reserve slots 1-3; the original OEM guard keeps slots 4-8. OEM F2FS
and the original Realme ZRAM/HybridSwap modules are preserved.
CFS_BANDWIDTH and CGROUP_PIDS remain disabled; MGLRU is compiled but
default-off. The stock Oplus vendor modules (built with Clang 14) load unchanged
under this kernel.

The delivery was flashed as a full boot_b partition image and verified over ADB
on the phone, including the NoMount metamodule and a DroidSpaces Ubuntu 24.04
container:

| Artifact | SHA-256 |
| --- | --- |
| `RMX3997-5.15.197-E-ZYC-BBRV3.zip` | `85079edee98ee7e25c7a2d6fe2479f749528eb6bdc985b127ca489ad686260a1` |
| Raw ARM64 Image | `c3ff239ac2e96b9e90b8ee41c5afc83415d380c1e5263d329bac51467b419dbd` |
| Effective config | `1156a9cbaf11bd605baa7b6965e38b9408b8540090a4043099ce688da26c07e7` |
| `boot_b-E-ZYC-BBRV3.img` (64 MiB partition image) | `585515f7e96989adedce0e1e6c16e9305912528d080fa850ad61559a221ecf49` |

`build-argv.json` and `build-environment.json` record the E build. These
artifact hashes are not live partition-byte hashes, except the boot_b image
whose read-back from the device was verified. The phone-confirmed D2 and D1
builds, the PARITY-B delivery and earlier records are kept in
[artifact and evidence provenance](delivery-provenance.json).

## Canonical configuration and build

`config/production.config` is the current canonical seed. It preserves the
frozen effective config byte-for-byte except for one documented path relocation:
`CONFIG_UNUSED_KSYMS_WHITELIST="rmx3997/config/abi-symbol-list.txt"` is relative to
the source root. `development/prepare-stage.py` selects this seed and runs the
tracked upstream flattener through `prepare-kmi-whitelist.py`, then binds
`stage/out/abi_symbollist.raw` before real `olddefconfig`. Restoring only the
original whitelist pathname recovers the exact frozen config hash above.
The generated raw whitelist is byte-identical to the original, not merely an
equivalent symbol set. Both relative and bound paths were exercised through
the real `scripts/gen_autoksyms.sh` consumer.

Build prerequisites are external: the retained OEM-F2FS workspace's
`kernel/build`, `kernel/prebuilts` (Clang r450784e / 14.0.7, kernel build tools
and NDK r23), ABI baselines, runner/checker files and `tests/check_f2fs_btf.py`.
The preparation script explicitly lists the copied names in its source.
The Git checkout alone is not a complete toolchain or validation corpus.
`build-argv.json` and `build-environment.json` are historical invocation
templates; their old host paths are not portable build commands. Preparation
relocates the prebuilt paths from the supplied ancestor and writes the actual
argv/environment under the new stage, retaining the flags, timestamp, user,
host, epoch and KMI generation. No old absolute whitelist file is required.

From the repository root, with `ANCESTOR` set to that retained workspace and
`STAGE` to a new directory on disk under the existing task scratch root:

```sh
export TMPDIR="$STAGE/scratch" PYTHONPYCACHEPREFIX="$STAGE/pycache"
python3 rmx3997/development/prepare-stage.py --ancestor "$ANCESTOR" --stage "$STAGE" --config-only
```

This runs config generation only (including host Kconfig tools); it does not
build Image/modules. Publication ran this path successfully with the original
compiler/flags and compared the entire result to the frozen config, allowing
only the whitelist-path relocation. The whitelist regression is:

```sh
python3 rmx3997/development/test-kmi-whitelist.py --output "$CHECK_DIR"
```

`CHECK_DIR` must be a new disk directory. For a future independently validated
build, use a new stage and omit `--config-only` to run the retained preparation
targets, then:

```sh
python3 rmx3997/development/build-stage.py "$STAGE" build
```

The launcher waits for at least 22 GiB available memory and no peer LTO linker,
then invokes the retained hard-abort resource guard with four jobs and
`ld.lld --threads=1`. Read the execution report to distinguish completion from
an abort. FullLTO, strict CFI, MODVERSIONS, MODULE_SIG_PROTECT and trim remain
enabled. Preparation or config checking is not a rebuild. SCM-derived release
strings and the relocated embedded config can change a new Image's bytes;
the frozen binary identity is not promised for a new checkout/build.

Before delivering any new build, validate its actual Image/vmlinux, embedded
config, OEM module corpus, CRC/protection/import tables and F2FS/task layouts.
The retained candidate's raw upstream ABI comparison exited **8**, classified
as compatible reserved-slot reuse using the exact report plus binary/layout
proof. It is not a raw PASS. The current ZIP was made by the retained
`ipc-slots123-diagnostic/package.py` wrapper calling
`development/package-oem-candidate.py`'s `inspect`/`package` functions after
those explicit checks and actual-Image guest acceptance. Its wrapper and
evidence hashes are in the provenance record. The generic packager CLI's
raw-PASS gate is an earlier interface and cannot package this classified
candidate directly. Do not relabel its ABI result to satisfy that gate.
New packaging also needs stock Android installer/AVB/full-payload validation
and separate phone acceptance. No new Image or ZIP was made for publication.

## Current installer

The current installer sources are `development/wk-anykernel/`, adapted from
pinned WildKernels AnyKernel3. All 12 installer/license/tool files exactly
match the confirmed ZIP. Three bundled executable inputs (BusyBox, magiskboot,
avbroot) are pinned vendor tools, with origin/license records; they are not
generated kernel outputs.

Installation requires booted Android on RMX3997, root, disk-backed `/data`, and
the installer's explicit `0/unlocked/orange` verified-boot state. First verify
the complete ZIP against the SHA-256 above. Extract its `install-on-device.sh`
to disk at `/data/local/install-on-device.sh`, then run from a root Android shell:

```sh
/system/bin/sh /data/local/install-on-device.sh /sdcard/RMX3997-5.15.197-IPC-SLOTS123-GUARD-PRESERVED-DIAGNOSTIC.zip
```

The launcher checks package SHA256SUMS and runs the real WK backend. It splits
the active boot partition, preserves ramdisk/DT/header, repacks with the Image
and writes boot only with fsync. It verifies the original AVB metadata and
creates truthful custom-unsigned AVB NONE metadata using pinned avbroot;
it does not write init_boot or vbmeta. The original boot is retained in the
private `/data/adb/rmx3997-ak3/work.*` directory. There is no automatic reboot
or automatic rollback. After a failed write, retain that backup and repair
the boot partition before rebooting. These are instructions only: publication
performed no phone operations; the verified existing ZIP is already on `/sdcard`.

## Historical interfaces

`approved-baseline.json`, `installer/`, provider replacement/transaction tools,
`development/delivery-core/`, old config seeds/fragments and broad feature
inventories describe earlier baselines or experiments. They are not the
current production entry points or current acceptance records. In particular,
`bakasu-susfs.config`, `features.config` and the locally retained
`full-feature-oem.config` must not be layered onto the canonical seed.
See the [development interface map](development/README.md). Original shallow
history is retained; this publication adds the confirmed integration and its
config/build/installer provenance without changing kernel semantics further.
