# RMX3997 approved kernel baseline

This repository starts from upstream Android13/Linux5.15.197 commit
`7bdd6d06fa9df6cbb36f22b1e96c84f689c5c838` and records the already approved
OEM F2FS port, four OEM vendor hooks and associated ABI description/symbol-list
updates. Its source matches the retained phone-booted baseline byte for byte.
No kernel code was changed as part of this Git setup.

The original repository has one available upstream commit and a shallow-history
boundary. Both are preserved here. This clone has an independent object store;
it does not depend on an alternate object directory in the old project.

## Configuration and installer sources

- `config/production.config` is the exact validated effective configuration.
- `config/abi-symbol-list.txt` preserves the corresponding build whitelist.
- `build-environment.json` and `build-argv.json` retain the actual Clang14/KMI8
  build settings and historical invocation. Their absolute paths refer to the
  original workspace; they are provenance, not a relocated build command.
- `installer/` contains the verified working OEM-F2FS boot-only installer sources,
  including the Android adapter and on-device entry runner. Its payload pin is
  the working boot image64da...8881 and its read-only init_boot pin is the
  BakaSU-patched image22f6...eee9. The old stock boot hash remains the existing
  allowed starting baseline; an already-present exact payload is a no-op.
  The existing package producer/tool assets and verified binary images remain in
  the retained workspace and are deliberately not copied into this repository.
- `approved-baseline.json` records exact source, configuration and artifact
  identities and identifies the retained external workspaces.

CFI, full LTO, symbol-version enforcement and the OEM F2FS persistent formats are
unchanged. BakaSU remains an external LKM loaded by the existing patched
init_boot image: no built-in root implementation or root module is added here.
KernelSU-Next/SUSFS integration code, its configuration and experimental
installers are excluded from this approved baseline. All experimental work stays
in its existing separate workspace, unchanged.

Build outputs, images, firmware/partition dumps, downloaded tools and temporary
files are ignored. Existing upstream-tracked source/fixtures remain tracked.
No compilation, packaging, device access, flashing or publication was performed.
