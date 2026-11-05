# RMX3997 phone-confirmed kernel source

The current delivery is Linux 5.15.197 / Android13 KMI8 with built-in
BakaSU/SUSFS, NTSync, the retained networking integration and SYSVIPC,
POSIX_MQUEUE, IPC_NS and PID_NS. IPC uses task_struct reserve slots1–3;
the original OEM guard keeps slots4–8. OEM F2FS and the original Realme
ZRAM/HybridSwap modules are preserved. USER_NS, DEVTMPFS, CFS_BANDWIDTH and
CGROUP_PIDS remain disabled; the default TCP congestion control is cubic.

The already-built delivery was subsequently confirmed to boot on the phone.
Its identities are:

| Artifact | SHA-256 |
| --- | --- |
| `RMX3997-5.15.197-IPC-SLOTS123-GUARD-PRESERVED-DIAGNOSTIC.zip` | `b0fe0a27b43725770843216fb11ddbc6032b88a2baee363b6dcf4e2296345084` |
| Raw ARM64 Image | `927db11b449ebba5fdd8d808fdae55a39fe6b0726aa9f6ff4efc61a77f621b36` |
| Frozen effective config | `789f557486f3f02cd029716720d2bc9befa9c871af75450792a560371f1204c3` |
| ABI whitelist, 8656 symbols | `1b6652e1e38f09e3c30102cefbb4253d57606c4afd3b02f6c7a61db8e246f5cb` |

The ZIP's historical DIAGNOSTIC filename and embedded phone-unknown manifest
describe its creation time. Later bounded postboot evidence records user
confirmation, boot_completed=1, matching live config and the original guard
and its providers. These artifact hashes are not live partition-byte hashes.
Full DroidSpaces/rootfs behavior and physical-phone container lifecycle remain
untested. See [artifact and evidence provenance](delivery-provenance.json).

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
