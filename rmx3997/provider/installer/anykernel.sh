#!/system/bin/sh
# Provider-aware AK3 entry; extraction is the explicit update-binary allowlist.
[ -n "$AKHOME" ] || exit 10
cd "$AKHOME" || exit 10
sha256sum -c SHA256SUMS || exit 10
/system/bin/sh "$AKHOME/provider/provider-install-entry.sh" "$AKHOME"
exit $?
