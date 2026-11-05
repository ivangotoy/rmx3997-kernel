#!/system/bin/sh
# Sourced after the accepted release's installer-core.sh/android-platform.sh
# and generated provider-release.sh. No alternate phone paths or test switches.
# Package caller sets PROVIDER_ASSETS, PAYLOAD and WORKDIR to verified disk files.

provider_preflight() {
    [ "$(platform_uid)" = 0 ] || return 1
    [ "$(platform_prop ro.product.oplus_model)" = RMX3997GL ] || return 1
    [ "$(platform_prop ro.build.display.id)" = 'RMX3997_16.0.5.1300(EX01)' ] || return 1
    [ "$(platform_prop ro.build.version.ota)" = RMX3997_11.F.81_2810_202610091732 ] || return 1
    [ "$(platform_prop ro.build.version.sdk)" = 36 ] || return 1
    [ "$(platform_prop ro.boot.slot_suffix)" = _b ] || return 1
    local slot path
    slot=$(platform_slot_evidence) || return 1
    [ -n "$slot" ] || return 1
    for path in $slot; do [ "$path" = _b ] || return 1; done
    case $(platform_release) in 5.15.197-android13-8-*) ;; *) return 1;; esac
    [ "$(platform_hash "$PAYLOAD")" = "$EXPECTED_PAYLOAD" ] || return 1
    [ "$(platform_size "$PAYLOAD")" = "$BOOT_BYTES" ] || return 1
    [ -d /metadata ] && [ ! -L /metadata ] || return 1
    case $(stat -f -c %t /metadata) in ef53|f2f52010) ;; *) return 1;; esac
    PROVIDER_KSU=/metadata/ksu
    for path in /metadata/vold/ksu /metadata/watchdog/ksu; do
        if [ -d "$path/preinit" ]; then PROVIDER_KSU=$path; break; fi
    done
    # Match the runner's precedence and exact safe_owner invariant on its
    # directories. Android's shared metadata parent is not a preinit module.
    case $PROVIDER_KSU in
        /metadata/vold/ksu) PROVIDER_PARENTS='/metadata/vold /metadata/vold/ksu' ;;
        /metadata/watchdog/ksu) PROVIDER_PARENTS='/metadata/watchdog /metadata/watchdog/ksu' ;;
        /metadata/ksu) PROVIDER_PARENTS='/metadata/ksu' ;;
        *) return 1;;
    esac
    for path in /metadata $PROVIDER_PARENTS "$PROVIDER_KSU/preinit"; do
        [ ! -L "$path" ] || return 1
        if [ -e "$path" ]; then
            [ -d "$path" ] || return 1
            if [ "$path" = "$PROVIDER_KSU" ] || [ "$path" = "$PROVIDER_KSU/preinit" ]; then
                [ "$(stat -c %u "$path")" = 0 ] || return 1
                local mode
                mode=$(stat -c %a "$path") || return 1
                [ $((0$mode & 0022)) = 0 ] || return 1
            fi
        fi
    done
    PROVIDER_ACTIVE=$PROVIDER_KSU/preinit/rmx3997-provider
    PROVIDER_STAGE=$PROVIDER_KSU/provider-stage.$$
    [ ! -e "$PROVIDER_ACTIVE" ] && [ ! -L "$PROVIDER_ACTIVE" ] || return 1
    [ ! -e "$PROVIDER_STAGE" ] && [ ! -L "$PROVIDER_STAGE" ] || return 1
    [ "$(platform_hash /vendor_dlkm/lib/modules/oplus_bsp_hybridswap_zram.ko)" = 66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302 ] || return 1
    provider_assets_verify "$PROVIDER_ASSETS"
}

provider_assets_verify() {
    local path=$1 name digest
    [ ! -L "$path" ] && [ -d "$path" ] || return 1
    for name in provider-loader provider.ko original-provider.ko preinit.conf; do
        [ ! -L "$path/$name" ] && [ -f "$path/$name" ] || return 1
        case $name in
            provider-loader) digest=$PROVIDER_LOADER_SHA256 ;;
            provider.ko) digest=$PROVIDER_MODULE_SHA256 ;;
            original-provider.ko) digest=66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302 ;;
            preinit.conf) digest=$PROVIDER_CONF_SHA256 ;;
        esac
        [ "$(platform_hash "$path/$name")" = "$digest" ] || return 1
    done
    [ -f "$path/provider-dependencies.sha256" ] && [ ! -L "$path/provider-dependencies.sha256" ] || return 1
    [ "$(platform_hash "$path/provider-dependencies.sha256")" = "$PROVIDER_DEPS_SHA256" ] || return 1
    local count=0
    while read -r digest name; do
        case $name in
            oplus_bsp_mm_osvelte.ko|mtk_disp_notify.ko|oplus_bsp_kshrink_slabd.ko|oplus_bsp_eas_opt.ko|oplus_bsp_sched_assist.ko|oplus_schedinfo.ko|oplus_bsp_zsmalloc.ko) ;;
            *) return 1;;
        esac
        [ -f "$path/$name" ] && [ ! -L "$path/$name" ] || return 1
        [ "$(platform_hash "$path/$name")" = "$digest" ] || return 1
        count=$((count+1))
    done < "$path/provider-dependencies.sha256"
    [ "$count" = 7 ]
}
provider_lock() { mkdir /metadata/rmx3997-provider-install.lock; }
provider_unlock() { rmdir /metadata/rmx3997-provider-install.lock; }
provider_sync() { sync; }
provider_stage() {
    (umask 077; mkdir -p "$PROVIDER_KSU/preinit") || return 1
    mkdir -m 700 "$PROVIDER_STAGE" || return 1
    local name
    for name in provider-loader provider.ko original-provider.ko preinit.conf provider-dependencies.sha256 \
        oplus_bsp_mm_osvelte.ko mtk_disp_notify.ko oplus_bsp_kshrink_slabd.ko oplus_bsp_eas_opt.ko \
        oplus_bsp_sched_assist.ko oplus_schedinfo.ko oplus_bsp_zsmalloc.ko; do
        cp "$PROVIDER_ASSETS/$name" "$PROVIDER_STAGE/$name" || return 1
        chmod 600 "$PROVIDER_STAGE/$name" || return 1
    done
    chmod 700 "$PROVIDER_STAGE/provider-loader"
}
provider_stage_verify() { provider_assets_verify "$PROVIDER_STAGE"; }
provider_activate() { mv "$PROVIDER_STAGE" "$PROVIDER_ACTIVE"; }
provider_discard_stage() {
    # Failed scratch is retained outside the runner's scanned directory.
    :
}
provider_restore() {
    if [ -d "$PROVIDER_ACTIVE" ]; then
        [ ! -e "$PROVIDER_STAGE" ] && [ ! -L "$PROVIDER_STAGE" ] || return 1
        provider_assets_verify "$PROVIDER_ACTIVE" || return 1
        mv "$PROVIDER_ACTIVE" "$PROVIDER_STAGE" || return 1
    fi
    [ ! -e "$PROVIDER_ACTIVE" ] && [ ! -L "$PROVIDER_ACTIVE" ]
}
provider_restore_verify() {
    [ ! -e "$PROVIDER_ACTIVE" ] && [ ! -L "$PROVIDER_ACTIVE" ] &&
    [ "$(platform_hash /vendor_dlkm/lib/modules/oplus_bsp_hybridswap_zram.ko)" = 66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302 ]
}
provider_boot_transaction() { installer_main "$PAYLOAD" "$WORKDIR"; }
