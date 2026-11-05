# Pinned avbroot 3.37.1 extra CLI. RMX3997 unlocked custom-unsigned policy.
# Parse the tool's own metadata, never AVB binary structures in shell.
rmx_avb_require_unlocked() {
  [ "$(getprop ro.boot.flash.locked):$(getprop ro.boot.vbmeta.device_state):$(getprop ro.boot.verifiedbootstate)" = 0:unlocked:orange ] || abort "CUSTOM-UNSIGNED requires verified unlocked device (0/unlocked/orange); refusing boot write";
}

rmx_avb_prepare() {
  export TMPDIR="$AKHOME";
  mkdir "$AKHOME/avb-original" || abort "AVB work directory failed";
  "$BIN/avbroot" avb info -i "$BOOTIMG" > "$AKHOME/avb-original/info" || abort "Malformed AVB input or missing footer; refusing boot write";
  "$BIN/avbroot" avb verify -i "$BOOTIMG" --fail-if-missing || abort "Original AVB verification failed; refusing boot write";
  "$BIN/avbroot" avb unpack -i "$BOOTIMG" --no-output-raw --output-info "$AKHOME/avb-original/avb.toml" || abort "Original AVB unpack failed";
  # Deliberately narrow policy: a footer, one boot Hash, properties only.
  awk '
    /^\[footer\]$/ {footer++}
    /^version_major = / {if ($0 != "version_major = 1") bad=1; major++}
    /^version_minor = / {if ($0 != "version_minor = 0") bad=1; minor++}
    /^algorithm_type = / {if ($0 != "algorithm_type = \"None\"" && $0 != "algorithm_type = \"Sha256Rsa2048\"") bad=1; algo++}
    /^type = / {if ($0 == "type = \"Hash\"") hash++; else if ($0 != "type = \"Property\"") bad=1}
    /^partition_name = / {if ($0 != "partition_name = \"boot\"") bad=1; part++}
    END {exit !(footer==1 && major==1 && minor==1 && algo==1 && hash==1 && part==1 && !bad)}
  ' "$AKHOME/avb-original/avb.toml" || abort "Malformed AVB or unsupported layout/footer version; refusing boot write";
  rmx_avb_require_unlocked;
  # Direct stderr shares the launcher's log offset; ui_print's append-open can
  # be overwritten by subsequent tools when stdout is redirected to a file.
  echo "CUSTOM-UNSIGNED: verified unlocked RMX3997; output AVB NONE (no OEM signature)." >&2;
  echo "Original AVB integrity verified; vbmeta partition and rollback flags unchanged." >&2;
}

rmx_avb_correct() {
  local extent size;
  mkdir "$AKHOME/avb-corrected" || abort "AVB output directory failed";
  # Repack updates the footer extent even though the hash descriptor is stale.
  # info parses structure only; do not unpack or accept a failed unpack here.
  "$BIN/avbroot" avb info -i "$AKHOME/boot-new.img" > "$AKHOME/avb-corrected/repacked-info" || abort "Malformed repacked AVB metadata";
  extent=$(awk '/^            original_image_size: [0-9]+,$/ {gsub(/,/, "", $2); print $2; n++} END {if(n!=1) exit 1}' "$AKHOME/avb-corrected/repacked-info") || abort "Missing full repacked payload extent";
  size=$(wc -c < "$AKHOME/boot-new.img");
  [ "$extent" -gt 0 ] && [ "$extent" -lt "$size" ] && [ "$size" = "$(wc -c < "$BOOTIMG")" ] || abort "Invalid repacked payload extent";
  # Full direct extraction: default unpack raw.img can zero a real kernel tail.
  dd if="$AKHOME/boot-new.img" of="$AKHOME/avb-corrected/full-payload.img" bs=4096 count=$((extent / 4096)) || abort "Payload copy failed";
  if [ $((extent % 4096)) -ne 0 ]; then
    dd if="$AKHOME/boot-new.img" bs=1 skip=$((extent / 4096 * 4096)) count=$((extent % 4096)) >> "$AKHOME/avb-corrected/full-payload.img" || abort "Payload tail copy failed";
  fi;
  [ "$(wc -c < "$AKHOME/avb-corrected/full-payload.img")" = "$extent" ] || abort "Incomplete payload copy";
  rmx_avb_require_unlocked;
  # Upstream documented --force without --key removes signing material and
  # selects NONE. Preserve original metadata; avbroot recomputes hash/extent.
  "$BIN/avbroot" avb pack --force --input-info "$AKHOME/avb-original/avb.toml" --input-raw "$AKHOME/avb-corrected/full-payload.img" -o "$AKHOME/avb-corrected/boot.img" --output-info "$AKHOME/avb-corrected/avb.toml" || abort "AVB correction failed";
  grep -qx 'algorithm_type = "None"' "$AKHOME/avb-corrected/avb.toml" || abort "CUSTOM-UNSIGNED output algorithm mismatch";
  "$BIN/avbroot" avb verify -i "$AKHOME/avb-corrected/boot.img" --fail-if-missing || abort "Corrected AVB verification failed";
  mv -f "$AKHOME/avb-corrected/boot.img" "$AKHOME/boot-new.img" || abort "Corrected image staging failed";
}
