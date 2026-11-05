### RMX3997 adaptation of WildKernels AnyKernel3
properties() { '
kernel.string=RMX3997 OEM-preserving 5.15.197 BakaSU/SUSFS
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=0
do.cleanuponabort=0
do.check_boot_version=1
keycheck.timeout=0
'; }

# Bind only the active boot partition. Never select init_boot or vendor_boot.
block=boot
is_slot_device=1
slot_select=active
ramdisk_compression=auto
patch_vbmeta_flag=0
no_magisk_check=1

. tools/ak3-core.sh

case "$(getprop ro.product.oplus_model)" in
  RMX3997|RMX3997GL) ;;
  *) abort "RMX3997 device required" ;;
esac
[ "$(getprop ro.board.platform)" = mt6835 ] || abort "MT6835 required"
[ "$(getprop ro.build.version.sdk)" = 36 ] || abort "Android 16 required"
case "$SLOT:$BLOCK" in
  _a:/dev/block/by-name/boot_a|_b:/dev/block/by-name/boot_b|_a:/dev/block/bootdevice/by-name/boot_a|_b:/dev/block/bootdevice/by-name/boot_b) ;;
  *) abort "Unexpected active boot partition" ;;
esac
[ -b "$BLOCK" ] || abort "Boot is not a block device"
[ "$(blockdev --getsize64 "$BLOCK")" = 67108864 ] || abort "Unexpected boot partition size"
[ "$(extract_kernel_version "$AKHOME/Image")" = 5.15.197-android13 ] || abort "Wrong Image family"
[ "$(dd if=Image bs=1 skip=56 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')" = 41524d64 ] || abort "Invalid ARM64 Image"

split_boot
# Android v3/v4 header, validated before repack. No baseline SHA restriction.
case "$(od -An -tu4 -j40 -N4 "$BOOTIMG" | tr -d ' \n')" in
  3|4) ;;
  *) abort "Unsupported boot header" ;;
esac
# Compare the extracted kernel from the captured boot before any repack.
do_check_boot_version
. "$BIN/rmx-avb.sh"
rmx_avb_prepare
# Keep the original split ramdisk, DT and header. With no ramdisk changes the
# WK flash_boot method repacks directly; unpack/repack_ramdisk would needlessly
# reconstruct the cpio. No write_boot multi-partition dispatch is used.
flash_boot
ui_print "RMX3997 boot installed. Original boot retained at $BOOTIMG" "No automatic reboot."
