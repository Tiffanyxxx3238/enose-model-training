# Step 5 — Offline System Acceptance Protocol (pre-registered)

Written **before** the replay and lifecycle suites were run. Base commit `8e051578`, branch `analysis/step5-offline-acceptance`.
These criteria are not changed after results are seen. Any deviation is reported as a deviation.

## Replay set

- **Eligible set:** S99 from R1 (`pipeline_b_corrected_training.csv`, `in_S99 == True`). These are 99 unique fruit-days, each counted once.
- **Exclusions are reported, not replayed as valid scans:**
  - the one S100-only day, whose fruit file is identical to its AIR file;
  - the rows in R1 `excluded_samples.csv`: no raw file, no human label, or AIR out of range.
- **Inputs:**
  - AIR: same-day AIR xlsx rows;
  - fruit: same-day fruit xlsx rows;
  - both read with the R1 repaired parser (`read_raw_xlsx_fixed`), keeping complete rows only, as in R1.
- **Acquisition contract:**
  - a fake serial port emits one CSV row per simulated second (1 Hz row clock);
  - the Gateway uses W0, the first 30 rows after warm-up = 0;
  - the CLI collects for 30 s and uses the last 30 rows, which equals W0 at 1 Hz;
  - no multi-window averaging, voting, AIR overrides, or window-consistency rules.
- **AIR calibration** goes through the real Gateway `/calibrate` path (engineering mode), using replayed historical AIR rows.
  - The resulting `_meta.source` is `live` because that is what the code path writes.
  - The temp file is annotated `test_fixture_note: historical replay — NOT a real measurement` and deleted after the run.
- **Mode:**
  - engineering (TEST) mode with a test-only registry entry: deploy model `a57dbbbf…16a1`, status `engineering`;
  - test-only `air_max_age_sec` = 3600 (an engineering test value, not a production recommendation);
  - formal mode keeps the shipped empty registry and must return `MODEL_NOT_APPROVED`.

## Pre-declared tolerances

| Quantity | Criterion |
|---|---|
| FIXED11 features, Gateway vs CLI | max \|Δ\| ≤ 1e-9 |
| FIXED11 features, Gateway vs R1 training-pipeline features (`pipeline_b_corrected_training.csv`) | max \|Δ\| ≤ 1e-9 |
| AIR baseline, Gateway `/calibrate` vs R1 `air_A0_*` | max relative \|Δ\| ≤ 1e-9 |
| Four-class probabilities, Gateway (API, rounded to 6 dp) vs CLI (full precision) | max \|Δ\| ≤ 5e-7 |
| Probabilities, web page (CLI printed text) vs CLI trace | within the printed precision (≤ 0.5 × 10^-d, where d = printed decimals) |
| Stage | identical across Gateway, CLI, and web |
| Repeated-run determinism | Gateway run twice: bit-identical probabilities. CLI run twice: bit-identical trace probabilities |
| API structure | every `/status` result passes the schema check and the Consumer App's real `validateRpiResult` |

## Acceptance categories (PASS / FAIL / BLOCKED / NOT TESTED)

- **A. Offline Python backend.**
  - PASS only if the Step 4B regression suite (85 runtime checks) and the Step 5 lifecycle suite run with 0 FAIL on the actual Gateway, CLI, and web entrypoints.
- **B. App build and API.**
  - PASS only if both apps compile (`tsc --noEmit` exit 0) and bundle (Expo export, web and Android JS),
  - and their API-client / screen integration tests pass against the real Gateway.
  - Native binary builds (APK/IPA) and device/emulator runs are reported separately. If unavailable they are BLOCKED; that does not by itself fail B, but it is listed as a blocker.
- **C. Offline end-to-end.**
  - PASS only if all eligible S99 days replay through Gateway, CLI, and web within the tolerances above (or each non-replayed day has a correct, explicit rejection reason),
  - and the invalid-scan cases are rejected.
- **D. Release consistency.**
  - PASS only if the manifest is produced and all of the following are verified:
    - model/feature checks;
    - config authority;
    - TEST labelling;
    - storage separation;
    - error-code/HTTP consistency;
    - secret scan;
    - port layout.
  - Any unresolved conflict is FAIL. If a conflict only has a proposed resolution that is not yet applied, report it as an open item.
- **E. Real hardware.**
  - Always NOT TESTED in Step 5.
- **Overall offline acceptance:**
  - PASS only if A, B, C, and D are all PASS;
  - and no critical actual-entrypoint test is BLOCKED or FAIL;
  - and both apps are built.
  - A BLOCKED native build is reported. It does not make the overall result PASS-with-hardware.

## Not in scope

- Model accuracy: the strict LOGO accuracy is about 0.424, and this step does not change it.
- Approval of any model.
- Raspberry Pi 3 compatibility.
- Real serial ports or sensors.
