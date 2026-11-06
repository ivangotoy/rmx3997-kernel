#!/system/bin/sh
# Final packager places this file in PACKAGE/provider beside accepted assets.
# It calls the unchanged boot transaction through provider metadata activation.
# EXIT also diagnoses an unexpected sourced-script or shell failure.
ENTRY_PHASE=arguments
trap 'entry_code=$?; if [ "$entry_code" != 0 ]; then printf "PROVIDER ENTRY DENIED: phase=%s exit=%s\n" "$ENTRY_PHASE" "$entry_code" >&2; fi' EXIT
entry_deny() { printf 'PROVIDER ENTRY DENIED: %s\n' "$*" >&2; exit 10; }
entry_mode_safe() {
    # Android mksh treats a leading zero as decimal; ash treats it as octal.
    # Validate stat output before explicit base conversion. Mask18 is octal022.
    case $1 in ''|*[!0-7]*) return 1;; esac
    [ $((8#$1 & 18)) = 0 ]
}
[ "$#" = 1 ] && [ "$(id -u)" = 0 ] || entry_deny "check failed: $ENTRY_PHASE"
ENTRY_PHASE=package-path
PACKAGE=$(readlink -f "$1") || entry_deny "check failed: $ENTRY_PHASE"
[ "$PACKAGE" = "$1" ] && [ -d "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || entry_deny "check failed: $ENTRY_PHASE"
ENTRY_PHASE=package-owner-mode
[ "$(stat -c %u "$PACKAGE")" = 0 ] || entry_deny "check failed: $ENTRY_PHASE"
mode=$(stat -c %a "$PACKAGE") || entry_deny "check failed: $ENTRY_PHASE"
entry_mode_safe "$mode" || entry_deny "check failed: $ENTRY_PHASE"
ENTRY_PHASE=provider-assets-owner-mode
PROVIDER_ASSETS=$PACKAGE/provider
[ -d "$PROVIDER_ASSETS" ] && [ ! -L "$PROVIDER_ASSETS" ] || entry_deny "check failed: $ENTRY_PHASE"
[ "$(stat -c %u "$PROVIDER_ASSETS")" = 0 ] || entry_deny "check failed: $ENTRY_PHASE"
mode=$(stat -c %a "$PROVIDER_ASSETS") || entry_deny "check failed: $ENTRY_PHASE"
entry_mode_safe "$mode" || entry_deny "check failed: $ENTRY_PHASE"
for file in "$PACKAGE/installer-core.sh" "$PACKAGE/android-platform.sh" \
    "$PROVIDER_ASSETS/provider-release.sh" "$PROVIDER_ASSETS/provider-transaction.sh" \
    "$PROVIDER_ASSETS/provider-android.sh"; do
    ENTRY_PHASE="source-owner-mode:$file"
    [ -f "$file" ] && [ ! -L "$file" ] || entry_deny "check failed: $ENTRY_PHASE"
    [ "$(stat -c %u "$file")" = 0 ] || entry_deny "check failed: $ENTRY_PHASE"
    mode=$(stat -c %a "$file") || entry_deny "check failed: $ENTRY_PHASE"
    entry_mode_safe "$mode" || entry_deny "check failed: $ENTRY_PHASE"
done
ENTRY_PHASE=package-filesystem
case $(stat -f -c %t "$PACKAGE") in ef53|f2f52010) ;; *) entry_deny "unsupported disk filesystem: $ENTRY_PHASE";; esac
ENTRY_PHASE=source-core
. "$PACKAGE/installer-core.sh"
ENTRY_PHASE=source-android-platform
. "$PACKAGE/android-platform.sh"
ENTRY_PHASE=source-provider-release
. "$PROVIDER_ASSETS/provider-release.sh"
ENTRY_PHASE=source-provider-transaction
. "$PROVIDER_ASSETS/provider-transaction.sh"
ENTRY_PHASE=source-provider-android
. "$PROVIDER_ASSETS/provider-android.sh"
ENTRY_PHASE=persistent-workspace
BASE=/data/adb/rmx3997-ak3
[ ! -L /data/adb ] && [ ! -L "$BASE" ] || entry_deny "check failed: $ENTRY_PHASE"
(umask 077; mkdir -p "$BASE") || entry_deny "check failed: $ENTRY_PHASE"
[ "$(readlink -f "$BASE")" = "$BASE" ] || entry_deny "check failed: $ENTRY_PHASE"
case $(stat -f -c %t "$BASE") in ef53|f2f52010) ;; *) entry_deny "unsupported disk filesystem: $ENTRY_PHASE";; esac
export TMPDIR=$BASE
WORKDIR=$BASE/work.provider.$$
mkdir -m 700 "$WORKDIR" || entry_deny "check failed: $ENTRY_PHASE"
PAYLOAD=$PACKAGE/boot.img
ENTRY_PHASE=provider-transaction
provider_install
exit $?
