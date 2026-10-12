# Step 5A — App build and API integration results

Outcome: **both apps compile (TypeScript) and bundle (Expo export: web + Android JS/Hermes bytecode); all runnable API-client / screen integration tests pass against the real modified Gateway.**

Not done here:
- Native binary builds (APK/IPA) and device/emulator runs are **BLOCKED**: there is no Android SDK, Gradle or Xcode on this machine.
- The Farmer App has **no real scan integration**. It is verified only to refuse scanning without inventing results.

## Environment (no admin rights, no global changes)

| Item | What was used |
|---|---|
| Node.js | Not installed. Used VS Code's bundled Electron runtime as Node: `Code.exe` with `ELECTRON_RUN_AS_NODE=1` → **Node v24.20.0**. Session-local shims only; PATH and the system are unchanged. |
| npm | **npm 10.9.2**, downloaded from registry.npmjs.org into the session scratch folder. Its tarball sha512 matched the registry `dist.integrity`. |
| Dependency install | Consumer: `npm ci --legacy-peer-deps --ignore-scripts` from the existing `package-lock.json` (lockfile hash unchanged after install). Farmer: **no lockfile in the repository** → `npm install --legacy-peer-deps --ignore-scripts` resolved from package.json ranges. The resulting `package-lock.json` is committed as the record of the exact tree tested; it needs owner review. |
| Why `--legacy-peer-deps` | The lockfile itself has a peer conflict: `lucide-react-native@0.475.0` declares React ≤18, while the project uses React 19.1.0. The project's own tooling is bun (`bun.lock`, `bunx rork …`), which does not enforce peers. No package versions were changed. |
| Test-only dependency | `react-test-renderer@19.1.0`, installed in a separate scratch folder, not in either app. |
| ESLint path issue | `eslint-import-resolver-typescript` cannot resolve `@/…` aliases when the project path contains CJK characters and spaces (`Semester 2 Final Exam (三下-期末)`). It was proven by resolving the same files from an ASCII path. Lint and Expo export therefore ran in an **ASCII mirror**: every source file copied and SHA-256-verified, with `node_modules` as a junction. `tsc` ran in place. |

## Results

| App | Step | Command | Exit | Result |
|---|---|---|---|---|
| Consumer | Install | `npm ci --legacy-peer-deps --ignore-scripts` | 0 | 1012 packages; lockfile unchanged |
| Consumer | TypeScript (first run, before fixes) | `tsc --noEmit -p .` | **2** | **8 errors.** Step 4B made environment fields nullable but did not update `app/history.tsx`, `app/history-detail.tsx` or `services/api.ts` |
| Consumer | TypeScript (after fixes) | `tsc --noEmit -p .` | **0** | 0 errors |
| Consumer | ESLint (project `eslint.config.js`, in mirror) | `eslint .` | 0 | 0 errors, 21 warnings (unused vars, hook deps; pre-existing) |
| Consumer | ESLint (in place, CJK path) | `eslint .` | 1 | 101 × `import/no-unresolved` on `@/` aliases only — path-encoding environment issue (see above) |
| Consumer | Bundle web | `expo export --platform web` | 0 | `entry-*.js` 3.34 MB |
| Consumer | Bundle Android | `expo export --platform android` | 0 | `entry-*.hbc` 5.2 MB (Hermes bytecode) |
| Farmer | Install | `npm install --legacy-peer-deps --ignore-scripts` | 0 | expo 54.0.37, react-native 0.81.5, react 19.1.0, typescript 5.9.3 |
| Farmer | TypeScript (first run) | `tsc --noEmit -p .` | **2** | **3 errors (pre-existing, not Step 4B):** `app/batches/[batchId]/{index,scan,summary}.tsx` imported `../../../../screens/…`, which points above the project root |
| Farmer | TypeScript (after fix) | `tsc --noEmit -p .` | **0** | 0 errors |
| Farmer | Existing test script | `node scripts/smoke-test.js` | 0 | Structure smoke test passed (file-existence checks only) |
| Farmer | Lint | `expo lint` | — | **NOT CONFIGURED**: the repo has no ESLint config, and `expo lint` would create one. An ad-hoc run with the Consumer App's Expo config (mirror only) found 0 errors in app sources and 1 error (`no-undef __dirname`) in the Node script `scripts/smoke-test.js` |
| Farmer | Bundle web | `expo export --platform web` | 0 | `entry-*.js` 3.24 MB |
| Farmer | Bundle Android | `expo export --platform android` | 0 | `entry-*.hbc` 4.96 MB |
| Both | Native build (APK/IPA), emulator, device | — | — | **BLOCKED**: no Android SDK, Gradle, Xcode or emulator; no device connection |

## Defects found by building and running the apps, and repaired

| # | App | Defect | Origin | Fix |
|---|---|---|---|---|
| 1 | Consumer | 8 TypeScript errors: nullable `Temp_C`, `Humidity_pct`, `Pressure_hPa` used with `.toFixed` in `history.tsx` and `history-detail.tsx`; `ScanRecordPayload` typed as non-null | Step 4B integration | Show "—" when a value is missing; payload type nullable |
| 2 | Consumer | `buildScanRecordPayload` hard-coded `confidence: 0.7` (fabricated confidence) | Pre-existing, missed by Step 4B | Confidence is now a required argument; payload requires `scan_id` and `result_kind` |
| 3 | Consumer | Legacy upload queue (`uploadScanRecord`) posted payloads with no `scan_id` or result kind | Pre-existing | Rejects TEST payloads and payloads without a `scan_id` (`TEST_RECORD_NOT_UPLOADABLE`) |
| 4 | Consumer | `generateMockSensorData` (random sensor values) still exported; unused | Pre-existing | Removed |
| 5 | Farmer | 3 broken route imports (`../../../../screens/`) — the app could not compile | Pre-existing | `../../../screens/` |
| 6 | Farmer | Batch summary showed "平均糖度 0.0 Brix" with zero samples (looks like a measurement) | Pre-existing | Shows "—" |
| 7 | Farmer | Scan screen text said "目前保留展示用 mock 結果" (false after Step 4B) | Step 4B leftover | Text now says no result is produced |

## Runnable API-client and screen integration tests

Full list: `api_contract_results.csv` and `storage_integrity_results.csv`; runner: `app_integration_tests.js`.

How the tests ran:
- The **apps' own TypeScript source** was transpiled with each app's own TypeScript and executed in Node.
- The backend was the **real modified Gateway v2**, served on 127.0.0.1 by `backend_harness.py`, with a fake serial port replaying historical rows.
- Test doubles were limited to native/device modules: AsyncStorage (in memory), expo-constants, expo-linking, expo-router, expo-linear-gradient, safe-area, lucide icons, react-native-svg and expo-speech.
- `react-native` was mapped to `react-native-web`, with `Alert` recorded.

**Consumer: 26/26 PASS.** Coverage:
- Formal mode with the shipped (empty) approval list: `MODEL_NOT_APPROVED`, and no serial port is opened.
- Engineering scan (`apiStartScan`, then `apiGetStatus(scanId)` until done): result kind TEST.
- `/status` without a scan_id: 400.
- `DEVICE_BUSY` is reported as an error, not followed.
- Stale result validated against a newer scan_id: `RESULT_SCAN_ID_MISMATCH`.
- Connection failure; backends returning no scan_id or HTML: `INCOMPLETE_RESPONSE`.
- Real `SensorProvider`:
  - success with TEST;
  - **missing environment data gives null, not 25 / 65 / 1013**;
  - ADC NaN, Inf, out-of-range or missing gives `ADC_INVALID` with no history write;
  - cancel during the serial read: Gateway records `cancelled`, port closed, no history;
  - 120 s poll timeout: `SCAN_TIMEOUT`, and `/cancel` is sent;
  - incomplete "done" payload is rejected;
  - `validateRpiResult` rejects `measurement_valid=false`, NaN probabilities, argmax mismatch, and a result-kind mismatch.
- `CalibrationProvider`: calibration tracked by scan_id to done with provenance `{live, formal, device_id: null}`. With an unreachable backend it shows "空氣校正失敗" instead of counting down locally.
- Real `HistoryProvider` and storage:
  - a TEST record goes only to `@pineapple_scan_history_test` and is never uploaded;
  - creating a record without scan_id, result kind or confidence throws;
  - a FORMAL record with an uncommitted scan_id gets 409 from the Gateway and never enters backend history.
- Real `app/processing.tsx`: leaving the screen mid-scan sends `/cancel`.
- Real `app/result.tsx`: TEST badge shown for TEST and absent for FORMAL; missing environment values show "—".
- **All 99 replay payloads** from the full replay pass the app's real `validateRpiResult`.

**Farmer: 4/4 PASS.**
- `services/api.startScan` throws `FARMER_SENSOR_NOT_CONNECTED`.
- `pingServer` against the real Gateway returns false: the Gateway has no `/ping`, so there is no Farmer↔Gateway scan contract.
- The real `BatchScanScreen` inside the real `AppProvider`: pressing scan shows "無法掃描", creates 0 samples, and displays no maturity, Brix, risk or confidence.
- The real `BatchSummaryScreen` with 0 samples shows "—", not "0.0 Brix".

## What these tests are not

- Not a React Native runtime, Hermes engine, or device/emulator test (BLOCKED).
- Not a test of real networking between a phone and the Pi.
- The Farmer App provides no ripeness measurement at all. Its passing tests prove only that it does not fabricate one.
