#!/system/bin/sh
# Shared transaction logic. Android supplies the fixed platform_* adapter;
# disposable tests supply a separate adapter outside the release archive.
EXPECTED_PAYLOAD=64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881
EXPECTED_STOCK=c7ab487bac1e2fb99932738aa423d5553b4ad8bcd2b8fc4677b8c491981fe086
EXPECTED_INIT_BOOT=22f6caff3b744be48c937825aae8f4392d43a14921a5d3bbc673aba8d22deee9
BOOT_BYTES=67108864
INIT_BOOT_BYTES=8388608

installer_log() { platform_log "$*"; }
installer_reject() { installer_log "REJECT: $*"; return 10; }
installer_unlock() {
    trap - INT TERM HUP
    platform_unlock "$WORKDIR" || installer_log 'Lock cleanup failed; retain logs and remove no files automatically.'
}
installer_restore() {
    installer_log 'ROLLBACK: validating preserved original before restoration'
    if [ "$(platform_size "$BACKUP")" != "$BOOT_BYTES" ] ||
       [ "$(platform_hash "$BACKUP")" != "$BEFORE_HASH" ]; then
        installer_log 'FATAL: rollback image is invalid; no unverified restore attempted'
        return 71
    fi
    if ! platform_write "$BACKUP" "$TARGET" || ! platform_sync ||
       ! platform_readback "$TARGET" "$READBACK" ||
       [ "$(platform_size "$READBACK")" != "$BOOT_BYTES" ] ||
       [ "$(platform_hash "$READBACK")" != "$BEFORE_HASH" ]; then
        installer_log 'FATAL: restoration could not be verified; DO NOT REBOOT'
        return 71
    fi
    WRITE_STARTED=0
    installer_log "ROLLBACK VERIFIED: original boot restored; retained $BACKUP"
    return 70
}
installer_interrupt() {
    local code=10
    installer_log 'Interrupted; preserving all transaction files'
    if [ "$WRITE_STARTED" = 1 ]; then
        installer_restore
        code=$?
    fi
    installer_unlock
    exit "$code"
}

installer_main() {
    PAYLOAD=$1
    WORKDIR=$2
    WRITE_STARTED=0
    BACKUP=$WORKDIR/boot_b.before.img
    READBACK=$WORKDIR/boot_b.readback.img
    [ "$(platform_uid)" = 0 ] || { installer_reject 'root required'; return 10; }
    [ "$(platform_prop ro.build.version.sdk)" = 36 ] || { installer_reject 'Android16 required'; return 10; }
    [ "$(platform_prop ro.product.oplus_model)" = RMX3997GL ] || { installer_reject 'wrong exact OEM model'; return 10; }
    [ "$(platform_prop ro.build.display.id)" = 'RMX3997_16.0.5.1300(EX01)' ] &&
    [ "$(platform_prop ro.build.version.ota)" = 'RMX3997_11.F.81_2810_202610091732' ] || { installer_reject 'wrong or missing exact firmware'; return 10; }
    case $(platform_release) in
        5.15.197-android13-8-*) ;;
        *) installer_reject 'wrong running KMI family'; return 10;;
    esac
    [ "$(platform_prop ro.boot.slot_suffix)" = _b ] || { installer_reject 'property slot is not B'; return 10; }
    local evidence s
    evidence=$(platform_slot_evidence) || { installer_reject 'kernel slot unavailable'; return 10; }
    [ -n "$evidence" ] || { installer_reject 'independent kernel slot evidence missing'; return 10; }
    for s in $evidence; do
        [ "$s" = _b ] || { installer_reject 'conflicting kernel/property slot evidence'; return 10; }
    done
    platform_workspace_safe "$WORKDIR" || { installer_reject 'workspace must be private and disk backed'; return 10; }
    [ -f "$PAYLOAD" ] && [ ! -L "$PAYLOAD" ] || { installer_reject 'payload must be a regular file'; return 10; }
    [ "$(platform_size "$PAYLOAD")" = "$BOOT_BYTES" ] || { installer_reject 'wrong payload size'; return 10; }
    [ "$(platform_hash "$PAYLOAD")" = "$EXPECTED_PAYLOAD" ] || { installer_reject 'wrong payload hash'; return 10; }
    TARGET=$(platform_partition boot_b) || { installer_reject 'boot_b block resolution failed'; return 10; }
    INIT_TARGET=$(platform_partition init_boot_b) || { installer_reject 'init_boot_b read-only check failed'; return 10; }
    [ "$TARGET" != "$INIT_TARGET" ] || { installer_reject 'partition aliases collide'; return 10; }
    [ "$(platform_size "$TARGET")" = "$BOOT_BYTES" ] || { installer_reject 'wrong boot partition size'; return 10; }
    [ "$(platform_size "$INIT_TARGET")" = "$INIT_BOOT_BYTES" ] || { installer_reject 'wrong init_boot partition size'; return 10; }
    [ "$(platform_hash "$INIT_TARGET")" = "$EXPECTED_INIT_BOOT" ] || { installer_reject 'current patched init_boot differs from verified baseline'; return 10; }
    BEFORE_HASH=$(platform_hash "$TARGET")
    if [ "$BEFORE_HASH" = "$EXPECTED_PAYLOAD" ]; then
        installer_log 'NO-OP: exact candidate already present; no partition writes'
        return 0
    fi
    [ "$BEFORE_HASH" = "$EXPECTED_STOCK" ] || { installer_reject 'boot is not known-good stock baseline'; return 10; }
    [ ! -e "$BACKUP" ] && [ ! -L "$BACKUP" ] || { installer_reject 'rollback path already exists'; return 10; }
    [ ! -e "$READBACK" ] && [ ! -L "$READBACK" ] || { installer_reject 'readback path already exists'; return 10; }
    local free
    free=$(platform_free_bytes "$WORKDIR")
    case $free in ''|*[!0-9]*) installer_reject 'free space unavailable'; return 10;; esac
    [ "$free" -ge 201326592 ] || { installer_reject 'less than192MiB free'; return 10; }
    platform_lock "$WORKDIR" || { installer_reject 'another installation holds the lock'; return 10; }
    trap installer_interrupt INT TERM HUP
    installer_log "BEGIN: boot_b=$TARGET; init_boot is read only"
    if ! platform_backup "$TARGET" "$BACKUP" || ! platform_sync ||
       [ "$(platform_size "$BACKUP")" != "$BOOT_BYTES" ] ||
       [ "$(platform_hash "$BACKUP")" != "$BEFORE_HASH" ]; then
        installer_log 'BACKUP FAILED: target has not been written'
        installer_unlock
        return 10
    fi
    installer_log "BACKUP VERIFIED: $BACKUP sha256=$BEFORE_HASH"
    # Only now may the target be opened for writing. No preliminary erase.
    WRITE_STARTED=1
    if ! platform_write "$PAYLOAD" "$TARGET" || ! platform_sync ||
       ! platform_readback "$TARGET" "$READBACK" ||
       [ "$(platform_size "$READBACK")" != "$BOOT_BYTES" ] ||
       [ "$(platform_hash "$READBACK")" != "$EXPECTED_PAYLOAD" ]; then
        installer_log 'INSTALL VERIFY FAILED: restoring exact previous boot'
        installer_restore
        local code=$?
        installer_unlock
        return "$code"
    fi
    WRITE_STARTED=0
    installer_log "INSTALL VERIFIED: full67108864-byte readback sha256=$EXPECTED_PAYLOAD"
    installer_log "Rollback preserved at $BACKUP; no automatic reboot or slot change"
    installer_unlock
    return 0
}
