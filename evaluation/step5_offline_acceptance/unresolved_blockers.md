# Step 5 — unresolved blockers and open items

Severity:
- **BLOCKER** — must be resolved before any real deployment or formal use.
- **OPEN** — must be decided or fixed during packaging (Step 6) or before release.
- **NOTE** — tracked limitation.

| # | Severity | Item | Evidence | Needed |
|---|---|---|---|---|
| 1 | **BLOCKER** | **Exposed Pi SSH credential.** A 7-character, non-placeholder `RPI_PASSWORD` value was found in tracked `pineapple_final/README_pineapple_final.md:282`. The value is not reproduced in any Step 5 output. | Redacted in this branch. The value **remains in git history** on main and earlier commits. | **Rotate the Pi credential manually.** Decide whether to rewrite history; this is the owner's decision, and Step 5 did not do it. |
| 2 | **BLOCKER** | **No approved maturity model.** `model_registry.json` is empty, so formal inference returns `MODEL_NOT_APPROVED` by design. | R04; APP-C01; L07; contract rows | Human approval decision. Strict LOGO accuracy remains about 0.424, and no Step 5 result supports approval. |
| 3 | **BLOCKER** | **No production AIR expiry and no real calibration.** All tests used a TEST-ONLY `air_max_age_sec` of 3600. The existing Pi `air_base.json` has no provenance and is rejected (`AIR_NO_PROVENANCE`). | R06; Step 4B B01 | Decide on an AIR expiry with justification; perform a real formal calibration on the device. |
| 4 | BLOCKER (hardware) | **Real hardware not tested:** Raspberry Pi 3 OS, Python, armv7/aarch64 wheels for scikit-learn 1.8.0 / numpy 2.4.3 / pandas 3.0.1; Arduino serial timing; USB device names; whether `serial.close()` interrupts a blocked read on the Pi. | E = NOT TESTED | Step with real hardware |
| 5 | BLOCKED | **Native app builds and device/emulator runs.** No Android SDK, Gradle, Xcode or emulator on this machine. | app_build_results.md | Build environment such as EAS or Android Studio; device tests |
| 6 | OPEN | **Service port conflicts.** `app_gateway_v2.py` and `app_local.py` both bind 5000; `app_gateway.py` (v1) and the unified web page both bind 8000. | R08 | Apply the proposed layout (manifest: `proposed_service_layout (NOT APPLIED)`): app_local 5000, Gateway v2 5001, photo 5002, unified 8000, retire v1. Update the Consumer `DEFAULT_API_URL` and the unified-web iframe together. |
| 7 | OPEN | **Start/stop scripts.** `start_pineapple_system.sh` launches v1 (port 8000, clashes with unified web) and **does not launch Gateway v2**. `stop_pineapple_system.sh` runs `pkill -f "app.py"`, which kills any process with app.py in its name. Unified web iframe URLs are hard-coded to `192.168.0.152`. | R09 | Rewrite the scripts and make hosts/ports configurable during Step 6 packaging |
| 8 | OPEN | **Farmer App has no lockfile and no lint config.** The lockfile committed here was generated at test time with `--legacy-peer-deps`. | app_build_results.md | Owner review of the lockfile; add an ESLint config, with Node globals for `scripts/` |
| 9 | OPEN | **Peer-dependency conflict** in both apps: `lucide-react-native@0.475.0` declares React ≤18, while the apps use React 19.1.0. | npm ERESOLVE | Upgrade lucide, or document the bun-based install |
| 10 | NOTE | **The Farmer App has no ripeness function.** It is only verified not to fabricate results. | APP-F01–F04 | Product decision |
| 11 | NOTE | Consumer App records saved before Step 4B have no scan_id or result kind. They stay in local history and cannot be uploaded (`TEST_RECORD_NOT_UPLOADABLE`); there is no silent conversion. | APP-C21 | Product decision on legacy records |
| 12 | NOTE | ESLint's TypeScript import resolver fails on the CJK/space project path. Lint was verified in an ASCII mirror. | app_build_results.md | Consider an ASCII deployment path in packaging |
| 13 | NOTE | Local Python 3.10 cannot install the pinned versions (scikit-learn 1.8 / numpy 2.4 need Python ≥ 3.11). The pinned run used Python 3.12.7. The Pi's Python version is unknown. | manifest | Confirm the Pi's Python version |

Not a blocker for offline packaging, but critical to understand: **offline software acceptance is not model-accuracy validation and not Raspberry Pi hardware validation.**
