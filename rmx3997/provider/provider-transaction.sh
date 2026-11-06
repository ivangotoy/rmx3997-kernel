#!/system/bin/sh
# Provider directory activation around the existing verified boot transaction.
# Adapter owns firmware/payload/hash/slot/metadata checks and exact fixed paths.
# No phone-facing adapter is enabled until the final payload is accepted.

# One shell owns both durable components. The assignment is the common logical
# commit point; traps cannot observe a half-transition. No external work occurs
# between publishing commit and discarding boot rollback state.
provider_commit() {
    [ "${PROVIDER_TRANSACTION_ACTIVE:-0}" = 1 ] &&
    [ "${PROVIDER_LOCK_HELD:-0}" = 1 ] &&
    [ "${PROVIDER_METADATA_READY:-0}" = 1 ] || return 1
    trap '' INT TERM HUP
    PROVIDER_COMMITTED=1
    WRITE_STARTED=0
    if [ "${INSTALLER_LOCK_HELD:-0}" = 1 ]; then
        trap installer_interrupt INT TERM HUP
    else
        trap provider_interrupt INT TERM HUP
    fi
}

provider_interrupt() {
    trap '' INT TERM HUP
    INSTALLER_INTERRUPTED=1
    local result=${1:-${PROVIDER_RESULT:-${INSTALLER_RESULT:-10}}}
    if [ "${PROVIDER_COMMITTED:-0}" = 1 ]; then
        # Both durable components are committed: neither handler may restore.
        result=0
        if [ "${INSTALLER_LOCK_HELD:-0}" = 1 ]; then
            installer_unlock || result=71
        fi
    else
        if [ "${INSTALLER_LOCK_HELD:-0}" = 1 ]; then
            if [ "${WRITE_STARTED:-0}" = 1 ]; then
                if [ "${INSTALLER_RESTORE_STARTED:-0}" = 1 ]; then
                    result=71
                else
                    installer_restore
                    result=$?
                fi
            fi
            installer_unlock || result=71
        fi
        if [ "${PROVIDER_LOCK_HELD:-0}" = 1 ]; then
            provider_restore && provider_sync && provider_restore_verify || result=71
        fi
    fi
    [ "${INSTALLER_CLEANUP_FAILED:-0}" = 0 ] &&
    [ "${PROVIDER_CLEANUP_FAILED:-0}" = 0 ] || result=71
    if [ "${PROVIDER_LOCK_HELD:-0}" = 1 ]; then
        provider_unlock || result=71
        PROVIDER_LOCK_HELD=0
    fi
    exit "$result"
}

provider_finish() {
    trap '' INT TERM HUP
    local result=0
    provider_unlock || { PROVIDER_CLEANUP_FAILED=1; result=71; }
    PROVIDER_LOCK_HELD=0
    PROVIDER_TRANSACTION_ACTIVE=0
    [ "${INSTALLER_CLEANUP_FAILED:-0}" = 0 ] || result=71
    # Retain terminal ownership until entry exits. A late signal must report the
    # committed result (or cleanup failure), never default-kill after commit.
    [ "$result" = 0 ] || PROVIDER_RESULT=71
    trap provider_interrupt INT TERM HUP
    return "$result"
}

provider_install() {
    provider_preflight || return 10
    PROVIDER_PENDING_SIGNAL=0
    PROVIDER_TRANSACTION_ACTIVE=1
    INSTALLER_LOCK_HELD=0
    INSTALLER_INTERRUPTED=0
    INSTALLER_RESTORE_STARTED=0
    INSTALLER_CLEANUP_FAILED=0
    PROVIDER_CLEANUP_FAILED=0
    INSTALLER_RESULT=10
    PROVIDER_COMMITTED=0
    PROVIDER_METADATA_READY=0
    unset PROVIDER_RESULT
    trap 'PROVIDER_PENDING_SIGNAL=1' INT TERM HUP
    if ! provider_lock; then
        PROVIDER_TRANSACTION_ACTIVE=0
        trap - INT TERM HUP
        return 10
    fi
    PROVIDER_LOCK_HELD=1
    trap provider_interrupt INT TERM HUP
    [ "$PROVIDER_PENDING_SIGNAL" = 0 ] || provider_interrupt
    # stage is a private sibling outside the preinit scan; publish by rename.
    if ! provider_stage || ! provider_stage_verify || ! provider_sync; then
        provider_discard_stage
        PROVIDER_RESULT=10
        provider_finish || return 71
        return 10
    fi
    if ! provider_activate || ! provider_sync; then
        local restore=0
        provider_restore && provider_sync && provider_restore_verify || restore=1
        PROVIDER_RESULT=10
        [ "$restore" = 0 ] || PROVIDER_RESULT=71
        provider_finish || return 71
        [ "$restore" = 0 ] && return 10
        return 71
    fi
    PROVIDER_METADATA_READY=1
    # Loader is pinned to the NEW kernel's notes. If power fails before the
    # boot write, the OLD kernel rejects it and boots its original provider.
    provider_boot_transaction
    local result=$?
    if [ "$result" != 0 ]; then
        if ! provider_restore || ! provider_sync || ! provider_restore_verify; then
            result=71
        fi
    fi
    PROVIDER_RESULT=$result
    provider_finish || return 71
    return "$result"
}
