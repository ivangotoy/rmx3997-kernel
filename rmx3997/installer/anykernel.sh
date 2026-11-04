#!/system/bin/sh
# RMX3997 AnyKernel3-format full boot image installer; Android root only.
# No ramdisk repack, root injection, extra partitions or generic slot fallback.
[ -n "$AKHOME" ] || exit 10
cd "$AKHOME" || exit 10
sha256sum -c SHA256SUMS || exit 10
. "$AKHOME/android-platform.sh"
. "$AKHOME/installer-core.sh"
installer_main "$AKHOME/boot.img" "$AKHOME"
exit $?
