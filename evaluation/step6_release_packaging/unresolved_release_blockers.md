# Step 6A — Unresolved release blockers and open items

**Severity:**
- **P0-DEPLOY** — must be resolved before any real deployment or formal use. These are not offline software defects.
- **BLOCKED** — needs an environment that is not available here.
- **OPEN** — owner review or decision needed.
- **NOTE** — known limitation.

No offline P0 software defect is open. Every reproducible offline defect found in this step was fixed and re-tested.

| # | Severity | Item | Evidence | Needed |
|---|---|---|---|---|
| 1 | **P0-DEPLOY** | **The exposed Pi SSH credential must be rotated.** It is redacted in the working tree but remains in git history. The release package contains no credentials (P03). The web page's new local execution mode needs no SSH at all. | Step 5 secret scan; P03 | Manual rotation by the owner; a decision on rewriting git history |
| 2 | **P0-DEPLOY** | **No approved maturity model.** The formal registry is empty, so formal inference is refused (`MODEL_NOT_APPROVED`). Strict LOGO accuracy is about 0.424. | F02, F03, P04 | Human model-approval decision. Not supported by any result so far. |
| 3 | **P0-DEPLOY** | **No validated AIR expiry and no real AIR calibration.** The formal template keeps `air_max_age_sec: null`, so scanning is disabled. All tests used a TEST-ONLY value of 3600 s. | F01 | A justified expiry; a real calibration procedure on the device |
| 4 | **BLOCKED** | **Raspberry Pi 3 not tested:** OS and architecture, wheel installation, memory and CPU with all services running, the Linux `fcntl.flock` lock path, the Linux `/proc` identity path (unit-tested only on a synthetic `/proc`), SIGTERM graceful stop, and `systemd`/boot integration (none provided). | `runtime_requirements.md`, `rpi3_compatibility_matrix.csv` | Step 6B/6C on real hardware; run `ops/rpi3_preflight.py` first |
| 5 | **BLOCKED** | **Real Arduino serial not tested:** header, 1 Hz timing, USB device naming, `dialout` permission, and whether `close()` interrupts a blocked read. | — | Hardware test |
| 6 | **BLOCKED** | **Native App builds (APK/IPA) and device/emulator tests.** | `app_release_consistency.md` | Android SDK/Gradle/EAS or Xcode |
| 7 | OPEN | **OS target decision.** Bookworm 64-bit is recommended: PyPI wheels exist for all pins. Bullseye is **incompatible** (`requires_python ≥ 3.11`). 32-bit needs piwheels, and the 64→32-bit model pickle load is unverified. | `rpi3_compatibility_matrix.csv` | Confirm the Pi's OS (preflight) |
| 8 | OPEN | **Farmer App dependency review:** `expo-speech@55` is incompatible with Expo SDK 54 and unused by the code; 10 direct dependencies are on newer patch versions than the Consumer App; the lockfile was generated in Step 5. | `expo install --check`; `logs/app_lockfile_comparison.txt` | Owner review before any native build |
| 9 | OPEN | **Peer conflict** in both apps: `lucide-react-native@0.475` declares React ≤ 18 while the apps use React 19.1. | npm ERESOLVE | Upgrade lucide, or adopt bun installs officially |
| 10 | OPEN | **Offline Python dependency delivery.** The package lists pins but does not bundle wheels, because wheels are architecture-specific. Installing on the Pi needs network access or a pre-downloaded wheelhouse for the Pi's architecture. | `requirements_release.txt` | Decide on a wheelhouse in Step 6B |
| 11 | NOTE | **The web (CLI) path writes no scan history.** Only Gateway scans are recorded. This is unchanged since Step 4B; web results are display-only. | D01 | Product decision |
| 12 | NOTE | **The photo/variety page** (port 5002, external model server) and Gateway v1 are outside this release. The unified page shows "未設定" for the photo tab unless a URL is configured. | inventory | — |
| 13 | NOTE | **The "0～9 program structure" could not be found** in any tracked path. | `release_source_inventory.md` | Owner to confirm where it lives |
| 14 | NOTE | **Tests ran on Windows x86_64 with Python 3.12.7.** Python 3.11 (Bookworm) was not available locally. | — | Re-run the package tests on the target |
