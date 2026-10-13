# PineNose Step 6A — Offline release packaging and deployment readiness

**Result: PASS — OFFLINE RELEASE PACKAGE ACCEPTED**

**Package status:** SOFTWARE RELEASE CANDIDATE — MATURITY INFERENCE NOT APPROVED.

What this PASS does **not** mean:
- The Raspberry Pi environment has not been shown to be compatible.
- Real hardware has not been tested.
- No AIR expiry has been scientifically validated.
- No maturity model is approved.
- Formal four-stage ripeness judgement cannot be offered.

Strict LOGO accuracy is still about 0.424.

## 1. Worktree and commits

- Path: `C:/Users/user/enose-step6-release-packaging`.
- Branch: `analysis/step6-release-packaging`.
- Base: `2b4a1df2` (Step 5 acceptance).
- Package built from **`973be8bb`**. The report and results are committed on top of it; that commit does not change packaged code.
- All commits are local. Nothing was pushed or merged, and history was not rewritten.

## 2. Release artifact

| Item | Value |
|---|---|
| File | `C:/Users/user/enose-step6-release-packaging/release_artifacts/pinenose-rc-6a-973be8bb.tar.gz` (git-ignored, not committed) |
| Size | 93,516 bytes; 35 files (34 listed in `SHA256SUMS`, plus `SHA256SUMS` itself) |
| SHA-256 | `db468b9677fc28b246f4bcc2eaeee596b73155f98fc1a3548df0a444c24c0383` |
| Reproducible | Rebuilding from the same commit gives byte-identical output (P02) |
| Traceability | `VERSION.json` and `manifests/release_manifest.json` record the source commit, the Step 5 acceptance commit, the git blob ID and SHA-256 of every file, API contract 2.1, feature schema FIXED11, and app versions with lockfile hashes |

## 3. Source changes in this step

| Area | Change |
|---|---|
| **Service manager (new)** `pinenose_release/ops/pinenose_service.py` | `start`/`stop`/`status`/`health`/`check`, with these behaviours: (1) verifies `SHA256SUMS` before starting, so only the packaged Gateway v2 can run; (2) validates the profile and runtime config; (3) checks ports first, failing with exit 3 without starting anything; (4) PID files record the process creation time and identity; (5) graceful stop via stop file and SIGTERM, then force-kill of verified-owned process trees only; (6) health checks treat "not approved" and "scan disabled" as RUNNING, not as faults; (7) binds loopback by default, with LAN only through `lan_access` plus an explicit private IPv4; (8) engineering profiles are loopback only and need a read-only model with matching SHA-256 registered as `engineering`; (9) the data folder is bound to its profile; (10) single-thread BLAS (memory) and a fault handler; (11) child processes run without console windows. |
| **Start/stop scripts** `整合網頁/start_pineapple_system.sh`, `stop_pineapple_system.sh` | Rewritten as wrappers around the manager. No more `pkill -f app.py`, `~/` paths, or Gateway v1. |
| `pineapple_app_gateway/start_server.sh` | Disabled: it installed unpinned packages and opened an ngrok public tunnel. |
| Gateway v2 | Data folder and model path come from the deploy config. Cross-process sensor lock. `api_version` in every JSON response. Default bind 127.0.0.1:5001. |
| CLI and AIR calibration CLI | Same data/model locations as the Gateway. Same sensor lock. They honour `ARDUINO_PORT` like the Gateway. The calibration CLI now validates AIR before writing it, and writes atomically. |
| Safety layer | `DeviceLock`. Reports `MODEL_NOT_APPROVED` when the approval list has no usable entry, and never falls back to another model. |
| Web page `app_local.py` | Explicit **local execution mode**: the same accepted CLI runs as a local subprocess, so no SSH credentials are needed. paramiko is imported only when needed. Default bind 127.0.0.1:5000. |
| Unified web | iframe URLs come from config, with an "未設定" notice when unset. **`debug=True` removed**; it exposed the Werkzeug debugger. Default bind 127.0.0.1:8000. |
| Consumer App | API URL from `EXPO_PUBLIC_PINENOSE_API_URL` (no hard-coded hotspot IP). API version check. Clear messages for `MODEL_NOT_APPROVED`, `AIR_MAX_AGE_NOT_CONFIGURED`, `API_URL_NOT_CONFIGURED` and `API_VERSION_MISMATCH`. Settings placeholder shows `:5001`. |
| Farmer App | Default URL from the same deploy variable. |
| Other new tools | `rpi3_preflight.py` (read-only); `pinenose_backup.py` (install/backup/verify/switch/rollback, dry-run by default); `build_release.py`; config templates; `requirements_release.txt` (adds the Flask stack missing from `requirements_rpi.txt`; no pin changed); operations docs. |

## 4. Service port layout (applied)

| Service | Formal | Engineering (TEST) |
|---|---|---|
| Web ripeness page | 5000 | 5100 |
| **Gateway v2** | **5001** | 5101 |
| Unified web | 8000 | 8100 (off) |

- Gateway v1 is retired: not packaged and never started.
- Default bind is 127.0.0.1 for every service.

Details are in `service_port_layout.md`.

## 5. Acceptance rules (all required to PASS)

| Rule | Result | Tests |
|---|---|---|
| Correct Gateway selected | **PASS** | S13 (v1 copied over v2 → integrity failure; `start_server.sh` refuses; package contains no v1; layout points to v2); S01 (log shows the module path inside the extracted release) |
| No service port conflict | **PASS** | Profile check S14 (duplicate ports rejected); S07 (occupied port → exit 3, nothing started) |
| Safe startup | **PASS** | S01, S02 (repeated start), S08 (config missing or wrong → exit 2), S09 (crash → stale cleanup), S04 (health not a fault) |
| Safe shutdown | **PASS** | S05 (graceful), S06 (repeated), S10 (PID reuse → not killed), S11 (stale PID), S12 (forced stop kills only owned processes), S15 (no leftover processes or PID files; ports free; no `__pycache__` in releases); Linux identity unit tests 6/6 |
| Formal model blocking | **PASS** | F01 (template → `AIR_MAX_AGE_NOT_CONFIGURED`), F02 (`MODEL_NOT_APPROVED`; client cannot switch to engineering), F03 (no model loaded, no fallback) |
| Engineering TEST isolation | **PASS** | E01 (model checks), D01 (TEST only in the engineering data folder), D03 (data folder bound to profile) |
| Valid scan replay | **PASS** | **E03: 99/99 fruit-days** through the extracted package's real HTTP endpoints: TEST label, same stage as Step 5, max \|Δp\| = 0.0. E04 web path. |
| Invalid scan rejection | **PASS** | E06 (ADC NaN, no header, too few rows, serial open failure, stale/corrupt/demo AIR), E07 (cancel), E08 (stuck read → `timed_out` at the real 65 s deadline), E09 (model error), E05 (sensor lock between processes) |
| Data integrity | **PASS** | D01, D02 (append-only across restart), B06/B07 |
| Backup verification | **PASS** | B02 (dry-run changes nothing; four categories with SHA-256), B08 (tampered backup → verify fails and rollback refuses) |
| Rollback verification | **PASS** | B05 (candidate start fails), B06 (rollback → previous release healthy; newer AIR and history kept; approval not restored; model still not approved), B07 (conflict → nothing overwritten, side copy kept), B09 (missing release restored from backup) |
| SHA-256 manifest verification | **PASS** | P01, P02, P05 (install verifies), startup integrity check (S13) |
| Secret exclusion | **PASS** | P03 (no credentials, models, raw data, AIR/history, local paths); package scan in `git_safety_check.txt` |
| Package extraction independence | **PASS** | P05/P06: installed into `%TEMP%` from the tarball only; runs with a neutral working directory and `PINENOSE_*`/`PYTHONPATH` cleared; no profile → explicit failure |

Counts:

| Suite | Result |
|---|---|
| Startup/shutdown (S) | **14/14** |
| Package, formal, engineering, data (P/F/E/D) | **22/22** |
| Backup/rollback (B) | **10/10** |
| Linux `/proc` unit tests | **6/6** |
| Step 4B regression on modified code | **85/85** (+14/14 static) |
| Step 5 lifecycle / storage / contract | **11/11, 7/7, 29/29** |

## 6. Apps (details in `app_release_consistency.md`)

- **Farmer lockfile**:
  - matches `package.json`;
  - a frozen `npm ci` succeeds and leaves the lockfile unchanged;
  - `tsc` exit 0.
  - **Review item:** `expo-speech@55` is incompatible with Expo SDK 54 and unused; 10 direct dependencies are on newer patch versions than the Consumer App.
- **Consumer**:
  - frozen `npm ci` OK;
  - `tsc` OK;
  - ESLint 0 errors;
  - `expo install --check` OK.
- **Bundles**:
  - both apps build web and Android (Hermes) bundles;
  - the deploy URL is injected;
  - no old hotspot IPs remain.
- **Integration tests** against the real Gateway: Consumer **30/30** (incl. version mismatch, URL not configured, `MODEL_NOT_APPROVED` screen), Farmer **4/4**.
- **Native APK/IPA and device tests: BLOCKED.**

## 7. Raspberry Pi 3 compatibility (details in `runtime_requirements.md`, `rpi3_compatibility_matrix.csv`)

**From published metadata (verifiable, not executed on a Pi):**
- **Bookworm 64-bit (Python 3.11, aarch64):** PyPI wheels exist for all 16 pinned packages. Recommended target.
- **Bullseye (Python 3.9):** **BLOCKER** — numpy, pandas, scikit-learn and scipy require Python ≥ 3.11.
- **Trixie 32-bit:** numpy and scipy have no wheel.
- **32-bit Bookworm:** works only through piwheels, and loading the model pickle across bitness is unverified.

**Not verified:**
- installation and execution on the Pi;
- memory and CPU with all three services running (x86 proxy: about 165 MB per model-loading process with single-thread BLAS);
- Linux `flock` and SIGTERM paths;
- serial permissions;
- Python 3.11 itself (tests used 3.12.7).

All of these are **UNVERIFIED — REQUIRES TARGET ENVIRONMENT CHECK**. Run `ops/rpi3_preflight.py` on the Pi first.

## 8. Real defects found and fixed in this step

1. `requirements_rpi.txt` omitted Flask and Werkzeug, which all three services need. They are now in `requirements_release.txt`, pinned.
2. The unified web ran with `debug=True` on `0.0.0.0` (remote code execution through the Werkzeug debugger).
3. Gateway v2 and the web page both bound 5000; Gateway v1 and the unified web both bound 8000. The start script launched v1, not v2.
4. `stop_pineapple_system.sh` used `pkill -f "app.py"`, which could kill unrelated programs.
5. `start_server.sh` opened an ngrok public tunnel and installed unpinned packages.
6. The web CLI and Gateway v2 could read the same Arduino at the same time. Fixed with a cross-process lock.
7. The CLIs ignored `ARDUINO_PORT` while the Gateway honoured it, so the two paths could use different devices.
8. The calibration CLI wrote AIR without the Gateway's validation, and not atomically.
9. The web page required SSH credentials even when running on the Pi itself. A local execution mode now avoids this.
10. Hard-coded hotspot IPs in both apps, and the old `:5000` in the Consumer settings placeholder.
11. Repository files are stored with CRLF line endings, which would break the shell scripts on Linux. The build normalizes to LF and records git blob IDs.
12. Committed memory was about 1.4 GB per process from OpenBLAS thread buffers. Single-thread BLAS brings it to about 164 MB, with results unchanged.
13. The preflight crashed on a fresh site. Fixed and covered by P07.
14. The ops tools wrote `__pycache__` into the release folder. Fixed and asserted by S15.
15. Rollback flagged a newer AIR as a conflict. It is now kept.

## 9. Open, blocked and P0-deploy items

Full list in `unresolved_release_blockers.md`. **No offline P0 software defect is open.**

**P0-DEPLOY** (must be resolved before any real deployment):
- rotate the exposed Pi SSH credential;
- no approved maturity model;
- no validated AIR expiry or real calibration.

**BLOCKED:**
- the Pi 3 itself;
- the real Arduino;
- native app builds.

**OPEN:**
- choose the target OS and architecture;
- review the Farmer dependencies (`expo-speech@55`);
- the lucide/React 19 peer conflict;
- offline wheel delivery for the Pi.

**NOTE:**
- the web (CLI) path records no scan history;
- the photo/variety service is out of scope;
- the "0～9" program structure could not be located in the repository.

## 10. Can Step 6B (pre-deployment status check) start?

**Yes.** Step 6B can start as a read-only check of the real Pi (OS, architecture, Python, installed files and running services) against this release candidate, using `ops/rpi3_preflight.py` and `deployment_preflight_checklist.md`. That needs explicit authorization and the credential rotation done first.

Installing on the Pi, changing its settings, or starting the services there are Step 6C and are **not** authorized by this result.
