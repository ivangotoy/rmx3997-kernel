# RMX3997 development interface status

The current phone-confirmed candidate and installation instructions are in
the [RMX3997 README](../README.md), with exact [provenance](../delivery-provenance.json).

| Interface | Status |
| --- | --- |
| `prepare-stage.py`, `prepare-kmi-whitelist.py`, `flatten_symbol_list` | Current production config preparation; selects `../config/production.config`. Explicit ancestor/stage paths replace the old positional stage-name interface. |
| `build-stage.py`, `resource-guard.py`, `resource_guard.py` | Current guarded build launcher, compatibility adapter and retained supervisor. Prior execution is evidence for the frozen candidate only. |
| `test-kmi-whitelist.py` | Targeted whitelist producer/consumer regression; not kernel build or phone proof. |
| `wk-anykernel/`, `wk-anykernel-origin.json` | Exact current ZIP installer/tool/license inputs. |
| `package-oem-candidate.py` | Current shared inspect/package functions. The frozen candidate used the retained IPC package wrapper and explicit exit8 compatibility evidence; the generic CLI's raw ABI PASS requirement is historical for this candidate. |
| `bakasu-susfs.config`, `features.config`, any local `full-feature-oem.config` | Historical seeds/experimental feature selections; not current validated production configuration. |
| `prepare-core-delivery.py`, `delivery-core/`, `config-parity-inventory*`, `inventory.py`, `retained-artifact-check.json` | Earlier baseline snapshots/inventories; artifact identities and assumptions are historical. |
| `full-feature-*`, `test-full-feature-contracts.py`, `run-target.py` and other feature/donor experiments | Historical feature investigation/test interfaces; no claim that their full feature inventory is enabled or currently accepted. |
| `package-provider-candidate.py`, `installer-ufs-run.py`, `../provider/`, provider guest tests and installer repair notes | Retired replacement-provider delivery and checkpoint transaction; not the OEM-preserving production installer. |
| `test-wk-anykernel-guest.py`, `wk-anykernel-guest-*`, `wk-anykernel-write-error-tests.sh` where locally retained | Historical installer validation fixtures. Their existence/setup is not a new execution or current phone confirmation. |

Unpublished local experiments may be present in an existing developer checkout.
They are not dependencies of the current config/installer path. Old absolute
paths and recorded commands are provenance for their original workspaces;
they do not establish a reproducible relocated build. Use the canonical
preparation entry and supply the matching external prerequisites explicitly.
