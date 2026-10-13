# Step 6A — App release consistency (Consumer / Farmer)

**Environment:**
- Node: VS Code's Electron runtime used as Node v24.20.0. npm: 10.9.2, portable and integrity-verified; the same setup as Step 5.
- Lint and bundling ran in an ASCII-path mirror, with every file SHA-256-verified, because ESLint's TypeScript resolver cannot handle the CJK/space path.
- **Native APK/IPA builds and device/emulator tests were not done (BLOCKED).**

## 1. Farmer lockfile (generated in Step 5 — reviewed here, not assumed reviewed)

| Check | Result |
|---|---|
| Lockfile root `dependencies`/`devDependencies` vs `package.json` | **identical** |
| Frozen clean install: `npm ci --legacy-peer-deps --ignore-scripts` | exit 0, 983 packages, **lockfile unchanged** (sha256 checked before and after) |
| TypeScript `tsc --noEmit` | exit 0, matching Step 5 |
| Expo SDK compatibility: `expo install --check`, offline | **1 finding:** `expo-speech@55.0.18` installed, Expo SDK 54 expects `~14.0.8`. The cause is `package.json` (`"expo-speech": "^55.0.8"`), not lockfile drift. The Farmer source never imports `expo-speech`. **Dormant but SDK-incompatible native dependency — needs owner review** (remove it, or pin `~14.0.8`). Not changed in this step. |
| Direct dependencies vs Consumer lock | 10 differ — newer patch releases within the same majors (e.g. expo 54.0.37 vs 54.0.34, expo-router 6.0.24 vs 6.0.23) plus `expo-speech` 55 vs 14. 271 of 1,011 shared transitive packages differ, because the lock was resolved at a later date. Details: `logs/app_lockfile_comparison.txt`. **Needs owner review** before a native build. |
| Peer conflict | Both apps: `lucide-react-native@0.475.0` declares React ≤ 18, but the apps use React 19.1.0. Installs need `--legacy-peer-deps`, and the project's own tool is bun. Unchanged from Step 5. |

## 2. Consumer lockfile

- Frozen `npm ci`: exit 0, 1,012 packages, lockfile unchanged.
- `expo install --check`: "Dependencies are up to date" (offline mode; Expo notes that offline validation is less reliable).
- `tsc`: exit 0.
- ESLint (project config): 0 errors.

## 3. Both apps — release behaviour

| Requirement | Consumer | Farmer | Evidence |
|---|---|---|---|
| API base URL from deployment config | `EXPO_PUBLIC_PINENOSE_API_URL` at build time, or entered by the user in settings; the default is empty | Same variable; Farmer has no scan API | `app_bundle_checks.txt`: the URL is injected when set. APP-C40: empty URL → `API_URL_NOT_CONFIGURED`, no request sent |
| No hard-coded hotspot Gateway IP in bundles | `192.168.43.251` removed, including the settings placeholder, which now shows `:5001` | `172.20.10.2` removed | Bundle scan: neither IP present. The photo/variety URL `192.168.43.90:5001` is out of scope and kept. |
| `/status` requires a scan_id | `apiGetStatus(scanId)` → `/status?scan_id=` | n/a | Step 5 APP-C03 re-run (400 without an id) |
| API contract version | The app expects `2.1`. Every Gateway JSON response carries `api_version`. A mismatch gives `API_VERSION_MISMATCH`; a missing version gives `INCOMPLETE_RESPONSE`. | n/a | APP-C41: old Gateway (1.0) rejected; current 2.1 accepted |
| TEST label preserved | Yes (Step 5 tests re-run) | No results at all | APP-C02, C09, C18, C22 |
| Clear state when the formal model is not approved | The scan screen shows "尚未提供正式成熟度判定 — 目前沒有經核准的成熟度模型（MODEL_NOT_APPROVED）…" and never reaches the result screen | Scan is refused (`FARMER_SENSOR_NOT_CONNECTED`) | APP-C42, **APP-C43** (real `processing.tsx` against the real formal Gateway) |
| No demo/mock fallback | Mock removed (Step 4B) | Mock removed | APP-C06–C08, F01 |
| No random maturity, Brix, blackheart risk or confidence | Yes | Yes: scan creates no sample; the summary shows "—" | F03, F04, C19 |
| No fabricated temperature/humidity/pressure | null → "—" | n/a | C10, C22 |
| App ↔ Gateway versions tracked together | `manifests/app_versions.json` in the release: app version, slug, package-lock SHA-256, expo/react-native/react/typescript versions, and the expected API version | Same, with "no scan contract" noted | release manifest |

## 4. Runnable results (real App TypeScript modules against the real Gateway on loopback)

- **Consumer: 30/30 PASS.** These are the 26 Step 5 tests re-run, plus APP-C40–C43. One Step 5 test (C23) needed a timing fix: wait up to 5 s for the asynchronous cancel record instead of a fixed 300 ms. The assertion itself is unchanged.
- **Farmer: 4/4 PASS.**
- **Bundles:**

  | App | Web bundle | Android (Hermes) bundle |
  |---|---|---|
  | Consumer | exit 0, 3.34 MB | exit 0, 5.20 MB |
  | Farmer | exit 0, 3.24 MB | exit 0, 4.96 MB |

- Logs: `logs/app_integration_consumer.log`, `logs/app_integration_farmer.log`, `logs/*_tsc.log`, `logs/*_npm_ci_frozen.log`, `logs/*_expo_install_check.log`, `logs/*_export_*.log`.

## 5. Not done

- **Native APK/IPA builds, device or emulator runs: BLOCKED** (no Android SDK, Gradle or Xcode).
- No phone↔Pi network test.
- No app store or signing work.
