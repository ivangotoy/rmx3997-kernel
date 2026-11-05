#!/system/bin/sh
# Booted Android launcher; extraction and all AK3 working files stay on /data.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Root required'; exit 1; }
[ "$#" = 1 ] || { echo 'Usage: sh install-on-device.sh PACKAGE.zip'; exit 1; }
ZIP=$(readlink -f "$1")
[ -f "$ZIP" ] || exit 1
umask 077
BASE=/data/adb/rmx3997-ak3
[ ! -L "$BASE" ] || exit 1
mkdir -p "$BASE"
chmod 700 "$BASE"
# Explicitly reject RAM filesystems even if /data was mounted unusually.
case "$(stat -f -c %t "$BASE")" in 1021994|858458f6) echo 'Disk-backed /data required'; exit 1;; esac
export AKHOME=$BASE/work.$$
mkdir "$AKHOME"
unzip -oq "$ZIP" -d "$AKHOME"
cd "$AKHOME"
chmod 700 tools/busybox
tools/busybox sha256sum -c SHA256SUMS || exit 1
# The actual pinned WK backend initializes BusyBox and executes anykernel.sh.
exec /system/bin/sh META-INF/com/google/android/update-binary 3 1 "$ZIP"
