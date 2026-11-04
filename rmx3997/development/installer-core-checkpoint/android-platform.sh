#!/system/bin/sh
# Production adapter: fixed Android interfaces, no test switches or alternate root.
platform_uid() { id -u; }
platform_prop() { /system/bin/getprop "$1"; }
platform_release() { uname -r; }
platform_slot_evidence() {
    local found=''
    if [ -r /proc/bootconfig ]; then
        found=$(sed -n 's/^[[:space:]]*androidboot\.slot_suffix[[:space:]]*=[[:space:]]*"\(_[ab]\)"[[:space:]]*$/\1/p; s/^[[:space:]]*androidboot\.slot[[:space:]]*=[[:space:]]*"\([ab]\)"[[:space:]]*$/_\1/p' /proc/bootconfig)
    fi
    printf '%s\n' "$found"
    tr ' ' '\n' < /proc/cmdline | sed -n 's/^androidboot\.slot_suffix=\(_[ab]\)$/\1/p; s/^androidboot\.slot=\([ab]\)$/_\1/p'
}
platform_partition() {
    case $1 in boot_b|init_boot_b) ;; *) return 1;; esac
    local path resolved='' candidate
    for path in /dev/block/by-name/"$1" /dev/block/bootdevice/by-name/"$1"; do
        [ -e "$path" ] || continue
        candidate=$(readlink -f "$path") || return 1
        [ -b "$candidate" ] || return 1
        case $candidate in /dev/block/*) ;; *) return 1;; esac
        [ -z "$resolved" ] || [ "$candidate" = "$resolved" ] || return 1
        resolved=$candidate
    done
    [ -n "$resolved" ] || return 1
    printf '%s\n' "$resolved"
}
platform_size() {
    if [ -b "$1" ]; then blockdev --getsize64 "$1"; else stat -c %s "$1"; fi
}
platform_hash() { sha256sum "$1" | awk '{print $1}'; }
platform_workspace_safe() {
    local path fs
    path=$(readlink -f "$1") || return 1
    [ "$path" = "$1" ] || return 1
    case $path in /data/adb/rmx3997-ak3/work.*) ;; *) return 1;; esac
    # The bundled BusyBox reports F2FS's name as UNKNOWN on this firmware.
    # Numeric magic identifies the same allowed F2FS/ext filesystem families.
    fs=$(stat -f -c %t "$path") || return 1
    case $fs in f2f52010|ef53) ;; *) return 1;; esac
    [ -d "$path" ] && [ ! -L "$path" ]
}
platform_free_bytes() { df -Pk "$1" | awk 'NR==2 {printf "%.0f\n", $4*1024}'; }
platform_lock() { mkdir /data/adb/rmx3997-ak3/install.lock; }
platform_unlock() { rmdir /data/adb/rmx3997-ak3/install.lock; }
platform_backup() { dd if="$1" of="$2" bs=1048576 count=64 conv=fsync; }
platform_write() {
    # This is the only production write-to-device primitive. Caller has pinned
    # TARGET via fixed boot_b resolution and verified rollback first.
    [ "$2" = "$TARGET" ] && [ -b "$2" ] || return 1
    dd if="$1" of="$2" bs=1048576 count=64 conv=fsync
}
platform_readback() { dd if="$1" of="$2" bs=1048576 count=64 conv=fsync; }
platform_sync() { sync; }
platform_log() { printf '%s\n' "$*"; }
