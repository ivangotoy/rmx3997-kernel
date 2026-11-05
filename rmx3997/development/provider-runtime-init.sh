#!/busybox sh
# Disposable production-Image guest only. Scratch and modules live on UFS/ext4.
B=/busybox
export PATH=/system/bin:/bin
finish() {
    $B dmesg
    $B sync
    /poweroff-native
    while :; do $B sleep 1; done
}
case " $($B cat /proc/cmdline 2>/dev/null) " in
    *' rmx3997.provider_guest=1 '*) ;;
    *) # /proc is not mounted on first entry; mount before checking the marker.
       $B mount -t proc proc /proc || exit 1
       case " $($B cat /proc/cmdline) " in *' rmx3997.provider_guest=1 '*) ;; *) exit 1;; esac;;
esac
if [ "${1:-}" = selinux_setup ]; then
    echo PROVIDER_GUEST_AFTER_ACTUAL_PREINIT
    if [ -f /data/FALLBACK_TEST ]; then
        [ ! -d /sys/module/oplus_bsp_hybridswap_zram ] || { echo PROVIDER_FALLBACK_REJECT_CHECK=FAIL; finish; }
        echo PROVIDER_FALLBACK_CANDIDATE_REJECTED=PASS
        cd /metadata/ksu/preinit/rmx3997-provider || finish
        KSU_PREINIT=1 /data/fallback-loader
        loader_status=$?
        echo PROVIDER_ORIGINAL_LOADER_EXIT=$loader_status
        [ "$loader_status" = 0 ] || finish
        dev=$($B cat /sys/block/zram0/dev) || finish
        $B mknod /dev/zram0 b "${dev%:*}" "${dev#*:}" || finish
        /data/provider-fallback-guest
        echo PROVIDER_FALLBACK_GUEST_EXIT=$?
        finish
    fi
    if [ ! -d /sys/module/oplus_bsp_hybridswap_zram ]; then
        echo PROVIDER_RUNTIME_BLOCKED=actual_preinit_provider_not_loaded
        finish
    fi
    dev=$($B cat /sys/block/zram0/dev) || finish
    $B mknod /dev/zram0 b "${dev%:*}" "${dev#*:}" || finish
    /data/provider-guest
    status=$?
    echo PROVIDER_CODEC_GUEST_EXIT=$status
    if [ "$status" = 0 ] && [ -f /data/provider-hybrid-guest ]; then
        dev=$($B cat /sys/class/block/sdb/dev) || finish
        $B mknod /dev/sdb b "${dev%:*}" "${dev#*:}" || finish
        /data/provider-hybrid-guest
        echo PROVIDER_HYBRID_GUEST_EXIT=$?
    fi
    echo PROVIDER_RUNTIME_REMAINING=hybrid_transport_lifetime_fallback_native_package
    finish
fi
$B mount -t sysfs sysfs /sys || exit 1
# Bind the exact retained QEMU PCI identity to production's built-in UFS driver.
printf '1b36 0013\n' > /sys/bus/pci/drivers/ufshcd/new_id || finish
n=0
while [ ! -r /sys/class/block/sda/dev ] && [ "$n" -lt 300 ]; do
    $B sleep 0.1
    n=$((n+1))
done
[ -r /sys/class/block/sda/dev ] || { echo PROVIDER_RUNTIME_BLOCKED=ufs_no_block_device; finish; }
dev=$($B cat /sys/class/block/sda/dev)
$B mknod /dev/sda b "${dev%:*}" "${dev#*:}" || finish
$B mount -t ext4 /dev/sda /data || { echo PROVIDER_RUNTIME_BLOCKED=ufs_ext4_mount; finish; }
[ "$($B cat /data/FIXTURE_ID)" = RMX3997-PROVIDER-DISPOSABLE ] || finish
$B mount -o bind /data/metadata /metadata || finish
$B chmod 700 /metadata/ksu /metadata/ksu/preinit /metadata/ksu/preinit/rmx3997-provider
# PID1 executes Android's actual preinit trigger. The built-in runner consumes
# metadata/preinit and uses its normal exec directive; no symbol-binding loader.
exec /system/bin/init selinux_setup
