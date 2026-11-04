#!/system/bin/sh
# Invoke the standard AK3 entry from disk; no tmpfs-backed wrapper required.
[ "$#" = 1 ] && [ "$(id -u)" = 0 ] || { echo 'Usage as root: sh install-on-device.sh /absolute/package.zip'; exit 10; }
ZIPFILE=$1
[ -f "$ZIPFILE" ] || exit 10
TOYBOX=/system/bin/toybox
BASE=/data/adb/rmx3997-ak3
[ ! -L /data/adb ] && [ ! -L "$BASE" ] || exit 10
mkdir -p "$BASE" || exit 10
chmod 700 "$BASE" || exit 10
[ "$("$TOYBOX" realpath "$BASE")" = "$BASE" ] || exit 10
case $("$TOYBOX" stat -f -c %T "$BASE") in f2fs|ext2|ext3|ext2/ext3|ext3/4|ext4) ;; *) exit 10;; esac
export TMPDIR=$BASE
ENTRY=$BASE/entry.$$.sh
[ ! -e "$ENTRY" ] && [ ! -L "$ENTRY" ] || exit 10
/system/bin/unzip -p "$ZIPFILE" META-INF/com/google/android/update-binary > "$ENTRY" || exit 10
[ "$("$TOYBOX" sha256sum "$ENTRY" | "$TOYBOX" cut -d ' ' -f 1)" = 5e56bdc00ec467c55c039c27541fb684b1cf5421517715a8f543c386efc3c306 ] || exit 10
/system/bin/sh "$ENTRY" 3 1 "$ZIPFILE"
code=$?
"$TOYBOX" rm -f "$ENTRY"
exit "$code"
