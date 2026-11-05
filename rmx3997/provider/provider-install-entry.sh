#!/system/bin/sh
# Final packager places this file in PACKAGE/provider beside accepted assets.
# It calls the unchanged boot transaction through provider metadata activation.
[ "$#" = 1 ] && [ "$(id -u)" = 0 ] || exit 10
PACKAGE=$(readlink -f "$1") || exit 10
[ "$PACKAGE" = "$1" ] && [ -d "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || exit 10
[ "$(stat -c %u "$PACKAGE")" = 0 ] || exit 10
mode=$(stat -c %a "$PACKAGE") || exit 10
[ $((0$mode & 0022)) = 0 ] || exit 10
PROVIDER_ASSETS=$PACKAGE/provider
[ -d "$PROVIDER_ASSETS" ] && [ ! -L "$PROVIDER_ASSETS" ] || exit 10
[ "$(stat -c %u "$PROVIDER_ASSETS")" = 0 ] || exit 10
mode=$(stat -c %a "$PROVIDER_ASSETS") || exit 10
[ $((0$mode & 0022)) = 0 ] || exit 10
for file in "$PACKAGE/installer-core.sh" "$PACKAGE/android-platform.sh" \
    "$PROVIDER_ASSETS/provider-release.sh" "$PROVIDER_ASSETS/provider-transaction.sh" \
    "$PROVIDER_ASSETS/provider-android.sh"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 10
    [ "$(stat -c %u "$file")" = 0 ] || exit 10
    mode=$(stat -c %a "$file") || exit 10
    [ $((0$mode & 0022)) = 0 ] || exit 10
done
case $(stat -f -c %t "$PACKAGE") in ef53|f2f52010) ;; *) exit 10;; esac
. "$PACKAGE/installer-core.sh"
. "$PACKAGE/android-platform.sh"
. "$PROVIDER_ASSETS/provider-release.sh"
. "$PROVIDER_ASSETS/provider-transaction.sh"
. "$PROVIDER_ASSETS/provider-android.sh"
BASE=/data/adb/rmx3997-ak3
[ ! -L /data/adb ] && [ ! -L "$BASE" ] || exit 10
(umask 077; mkdir -p "$BASE") || exit 10
[ "$(readlink -f "$BASE")" = "$BASE" ] || exit 10
case $(stat -f -c %t "$BASE") in ef53|f2f52010) ;; *) exit 10;; esac
export TMPDIR=$BASE
WORKDIR=$BASE/work.provider.$$
mkdir -m 700 "$WORKDIR" || exit 10
PAYLOAD=$PACKAGE/boot.img
provider_install
exit $?
