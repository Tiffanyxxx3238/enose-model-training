# Step 6A — test commands, exit codes and logs

All service tests ran against the **extracted release package** in `%TEMP%\s6a\...`, outside the worktree. Services bound to `127.0.0.1` only. A test-only fake `serial` module was injected through `PYTHONPATH`; it is not part of the package. No Raspberry Pi, SSH, real serial port, or deployment was involved.

From the final runs onward, all child processes ran with `CREATE_NO_WINDOW` (no console windows).

**Python environments:**

| Venv | Used for | Contents |
|---|---|---|
| Release venv (`%TEMP%\s6v`) | Runs the packaged services | Python 3.12.7 plus exactly `requirements_release.txt` |
| Test venv (`%TEMP%\s6t`) | Runs the test harness | The same, plus openpyxl 3.1.5 (test-only, to read raw XLSX) |

## Final runs (package `pinenose-rc-6a-973be8bb`, built from commit `973be8bb`)

| Step | Command (cwd `evaluation/step6_release_packaging`) | Exit | Result | Duration | Log |
|---|---|---|---|---|---|
| Build | `python pinenose_release/build_release.py --commit HEAD --out-dir release_artifacts` | 0 | 35 files, 93,516 bytes | <5 s | stdout |
| Package acceptance | `S6A_PACKAGE_ID=pinenose-rc-6a-973be8bb python -u package_tests.py` | 0 | **36/36 PASS** (incl. 99/99 replay) | 12 m 52 s | `logs/package_tests.log` |
| Backup / rollback | `python -u backup_rollback_tests.py` | 0 | **10/10 PASS** | 53 s | `logs/backup_rollback_tests.log` |
| Linux `/proc` identity (synthetic `/proc`) | `python linux_proc_unit_tests.py` | 0 | **6/6 PASS** | <1 s | `logs/linux_proc_unit_tests.log`, `logs/linux_proc_unit_test_results.csv` |
| Pi compatibility metadata | `python rpi3_compat_query.py` (PyPI + piwheels JSON) | 0 | 16 packages × 6 targets | ~1 min | `rpi3_compatibility_matrix.csv`, `logs/rpi3_compatibility_summary.csv` |
| Resource proxy (x86_64) | inline script | 0 | see `runtime_requirements.md` | — | `logs/resource_measurement_x86.txt` |
| Preflight on a fresh site (Windows, not a Pi) | part of P07 | 0 | PREFLIGHT OK; read-only | — | `logs/rpi3_preflight_smoke.txt` |
| Step 4B regression on modified code | copy of `step4b_tests.py` (`EVAL` path adjusted) | 0 | 85/85 runtime + 14/14 static | 43 s | `logs/pre_commit_step4b_regression.log` |
| Step 5 lifecycle regression | copy of `lifecycle_tests.py` | 0 | lifecycle 11/11, storage 7/7, contract 29/29 | ~30 s | `logs/pre_commit_step5_lifecycle.log` |

### Apps (Node = VS Code Electron, v24.20.0; npm 10.9.2)

| App | Command | Exit | Result / log |
|---|---|---|---|
| Consumer | `npm ci --legacy-peer-deps --ignore-scripts` | 0 | 1012 packages, lockfile unchanged — `logs/consumer_npm_ci_frozen.log` |
| Farmer | `npm ci --legacy-peer-deps --ignore-scripts` | 0 | 983 packages, lockfile unchanged — `logs/farmer_npm_ci_frozen.log` |
| Consumer / Farmer | `tsc --noEmit -p .` | 0 / 0 | `logs/consumer_tsc.log`, `logs/farmer_tsc.log` |
| Consumer / Farmer | `expo install --check` (offline) | 0 / **1** | Farmer: `expo-speech@55` should be `~14.0.8` — `logs/*_expo_install_check.log` |
| Consumer | `eslint .` (ASCII mirror) | 0 | 0 errors — `logs/consumer_eslint.log` |
| Consumer | `EXPO_PUBLIC_PINENOSE_API_URL=http://192.168.50.10:5001 expo export --platform web` | 0 | URL injected — `logs/consumer_export_web_with_url.log` |
| Consumer / Farmer | `expo export --platform android` / `web` | 0 | `logs/*_export_*.log`; bundle scan in `logs/app_bundle_checks.txt` |
| Consumer | `node app_integration_tests.js` (`APP=consumer`; real Gateway via `test_support/s5_app/backend_harness.py`) | 0 | **30/30** — `logs/app_integration_consumer.log` |
| Farmer | `node app_integration_tests.js` (`APP=farmer`) | 0 | **4/4** — `logs/app_integration_farmer.log` |

## Earlier runs during development (fixed, then re-run above)

| Run | Outcome | Fix |
|---|---|---|
| Package debug run 1 (3-day replay) | 33/35 | D01 expectation was wrong (the web path writes no history). E08: the Gateway exited once, and it did not reproduce in 6 later attempts. A fault handler was added; never seen again in 5 full runs. |
| Package debug runs (interrupted by the user) | — | Console windows popped up. All child processes now use `CREATE_NO_WINDOW`, and `tasklist`/`attrib` were replaced with the Windows API and `os.chmod`. |
| Package run (`93c0c77b`) | 35/35 | — |
| Preflight smoke | Traceback on a fresh site (data folder missing) | Fixed; P07 added |
| Package run (`5f9bb73e`) | 35/36 | P07 found `__pycache__` written into the release folder. The ops tools now set `sys.dont_write_bytecode`, and S15 now asserts that no `__pycache__` appears. |
| Rollback run before fix | — | A newer AIR calibration was flagged as a conflict; it is now kept |
| Consumer C23 | Timing race (fixed 300 ms wait) | Waits up to 5 s for the asynchronous cancel |

Test result files:
- `startup_shutdown_test_results.csv` (S × 14);
- `release_package_test_results.csv` (P, F, E, D);
- `package_replay_results.csv` (99 fruit-days);
- `backup_rollback_test_results.csv` (B × 10).
