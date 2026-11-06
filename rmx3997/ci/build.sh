#!/bin/bash
# Build the RMX3997 kernel from a clean checkout into "$1/out".
#
# Same toolchain, make variables and environment as the phone-verified
# deliveries, with host-local paths taken from host-inputs.json roots.
# The build runs in a systemd user scope (MemoryHigh=12G, MemoryMax=16G)
# under rmx3997/development/resource-guard.py, which aborts the whole build
# before host memory or swap is exhausted.
set -Eeuo pipefail

STAGE=${1:?usage: build.sh STAGE}
JOBS=${RMX_JOBS:-16}
SRC=$(git rev-parse --show-toplevel)
cd "$SRC"

ZYC=$HOME/.cache/zyc-clang-18.0.0git-20240124/extracted
PRE=$HOME/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/kernel/prebuilts
HOSTCLANG=$PRE/clang/host/linux-x86/clang-r450784e
BT=$PRE/kernel-build-tools/linux-x86
SYSROOT=$PRE/ndk-r23/toolchains/llvm/prebuilt/linux-x86_64/sysroot
OUT=$STAGE/out

for d in "$ZYC/bin" "$HOSTCLANG/bin" "$BT/bin" "$SYSROOT"; do
  test -d "$d" || { echo "FAIL: missing toolchain directory ${d/#$HOME/\~}"; exit 1; }
done

# Do not overlap Full-LTO links with other kernel builds on this host.
deadline=$((SECONDS + 1800))
while :; do
  avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  peers=$(pgrep -x ld.lld | wc -l || true)
  if [ "$avail" -ge $((22 * 1024 * 1024)) ] && [ "$peers" -eq 0 ]; then break; fi
  echo "waiting for host capacity: MemAvailable=$((avail / 1024 / 1024))GiB ld.lld=$peers"
  [ "$SECONDS" -lt "$deadline" ] || { echo 'FAIL: host busy for 30 min; no build started'; exit 1; }
  sleep 30
done

mkdir -p "$OUT" "$STAGE/tmp"
export BRANCH=android13-5.15 KMI_GENERATION=8 LC_ALL=C TZ=UTC
export KBUILD_BUILD_HOST=build-host KBUILD_BUILD_USER=build-user KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP='Tue Oct 13 20:28:27 UTC 2026' SOURCE_DATE_EPOCH=1791923307
# CFI/UBSAN check data embeds source paths that -fmacro-prefix-map does not
# remap; strip the source directory (and the leading root) from them.
STRIP=$(( $(printf %s "$SRC" | tr -cd / | wc -c) + 1 ))
export KCFLAGS=" -D__ANDROID_COMMON_KERNEL__ -fsanitize-undefined-strip-path-components=$STRIP"
export HOSTCFLAGS="-I$BT/include"
export HOSTLDFLAGS="-L$BT/lib64 -Wl,-rpath,$BT/lib64 -fuse-ld=lld --rtlib=compiler-rt"
export USERCFLAGS="--target=aarch64-linux-android31 --sysroot=$SYSROOT -Wno-unused-function"
export USERLDFLAGS="-fuse-ld=lld --rtlib=compiler-rt --target=aarch64-linux-android31 -resource-dir=$HOSTCLANG/lib64/clang/14.0.7 --unwindlib=none"
export PATH="$ZYC/bin:$HOSTCLANG/bin:$BT/bin:/usr/bin:/bin"
export TMPDIR=$STAGE/tmp PYTHONPYCACHEPREFIX=$STAGE/pycache

MAKEVARS=(-C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 LLVM_IAS=1
  CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabi-
  HOSTCC="$HOSTCLANG/bin/clang" HOSTCXX="$HOSTCLANG/bin/clang++"
  PAHOLE="$BT/bin/pahole" LD="$ZYC/bin/ld.lld --threads=1")

{
  echo "clang: $("$ZYC/bin/clang" --version | head -1)"
  echo "ld.lld: $("$ZYC/bin/ld.lld" --version | head -1)"
  echo "host clang: $("$HOSTCLANG/bin/clang" --version | head -1)"
  echo "pahole: $("$BT/bin/pahole" --version)"
  echo "jobs: $JOBS"
} | tee "$STAGE/toolchain.txt"

cp rmx3997/config/production.config "$OUT/.config"
make "${MAKEVARS[@]}" olddefconfig > "$STAGE/olddefconfig.log" 2>&1
python3 -I rmx3997/ci/rmx_ci.py config --out "$OUT"

set +e
systemd-run --user --scope --quiet --collect \
  --unit="rmx3997-ci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}" \
  -p MemoryHigh=12G -p MemoryMax=16G -p MemorySwapMax=24G -- \
  python3 -I rmx3997/development/resource-guard.py \
    --log "$STAGE/build.log" --result "$STAGE/build-execution.json" -- \
    make "${MAKEVARS[@]}" -j"$JOBS" Image modules
rc=$?
set -e
python3 -I - "$STAGE/build-execution.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print('build: exit=%s aborted=%s reason=%s min_MemAvailable_GiB=%s' % (
    r.get('exit_code'), r.get('aborted'), r.get('reason'),
    round((r.get('minimum_actual_MemAvailable_bytes') or 0) / 2**30, 2)))
EOF
if [ "$rc" -ne 0 ]; then
  echo "FAIL: build exited $rc; last log lines:"
  tail -n 60 "$STAGE/build.log" | sed "s#$HOME#~#g"
  exit "$rc"
fi
cat "$OUT/include/config/kernel.release"
