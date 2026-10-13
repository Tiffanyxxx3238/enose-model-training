# Step 6A — Release source inventory (written before any code change)

- Repository: `C:/Users/user/electronic-nose-pineapple-ripeness-assessment`. Its `.git` is the common dir shared by all worktrees.
- Worktree: `C:/Users/user/enose-step6-release-packaging`.
- Branch: `analysis/step6-release-packaging`.
- Base: `2b4a1df2273635caab481d130791716f2f099289`, the Step 5 acceptance commit.
- Step 5 evidence read: `evaluation/step5_offline_acceptance/`. It contains `step5_acceptance_report.md`, `app_build_results.md`, `unresolved_blockers.md`, `release_compatibility_manifest.json`, `full_replay_results.csv`, `test_commands_and_logs.md`, and `step4b_safeguards/`.
- Baseline SHA-256 of protected files (models, raw XLSX, labels, R1 candidate): `logs/baseline_protected_hashes.txt`.

Paths below are relative to `Semester 2 Final Exam (三下-期末)/`.

## 1. Service entry points (actual files)

| Service | File | Entry point | Port in code (base) | Bind host (base) | Step 5 status |
|---|---|---|---|---|---|
| **Gateway v2** (App API, accepted) | `pineapple_app_gateway/app_gateway_v2.py` | `__main__` → `app.run(...)` | **5000** | **0.0.0.0** | Accepted |
| Safety layer | `pineapple_final/pinenose_safety.py` | Imported by the Gateway and the CLI | — | — | Accepted |
| Web inference CLI | `pineapple_final/inference_30s.py` | `main()` | — | — | Accepted |
| AIR calibration CLI | `pineapple_final/calibrate_air_30s.py` | `main()` | — | — | Accepted |
| Web ripeness page | `pineapple_final/app_local.py` | `__main__` → `app.run(...)` | **5000** (conflicts with the Gateway) | **0.0.0.0** | Accepted. Runs the CLI over **SSH** with paramiko, credentials from env; the Step 5 tests replaced SSH |
| Unified web | `整合網頁/pineapple_unified_web/app.py` (+ `templates/index.html`, `static/style.css`) | `__main__` → `app.run(...)` | **8000** | **0.0.0.0**, **`debug=True`** | Iframe container only. URLs hard-coded to `192.168.0.152:5000` and `:5002` |
| **Gateway v1 (legacy)** | `pineapple_app_gateway/app_gateway.py` | `__main__` | **8000** (conflicts with unified web; the README says 5002) | 0.0.0.0 | **Not accepted.** Photo/variety recognition proxy to `http://192.168.0.176:5001/predict`, plus old `/ripeness/*` routes through the old CLI |
| Arduino firmware | `pineapple_deployment_system/use_this/use_this.ino` | Flashed to the Arduino | — | — | Column mapping verified (R01) |

## 2. Existing start / stop scripts

| Script | What it does (base commit) | Problems |
|---|---|---|
| `整合網頁/start_pineapple_system.sh` | `cd ~/pineapple` → `nohup python app_local.py &`; `cd ~/pineapple_app_gateway` → `nohup python app_gateway.py &` (**v1**); `cd ~/pineapple_unified_web` → `nohup python app.py &` | Starts **v1**, not v2. 8000 conflict (v1 vs unified). Absolute `~/…` paths. No PID tracking. No health check. No port check |
| `整合網頁/stop_pineapple_system.sh` | `pkill -f "app_local.py"`, `pkill -f "app_gateway.py"`, `pkill -f "pineapple_unified_web"`, `pkill -f "app.py"` | **Broad pattern kills**: any process whose command line contains `app.py` |
| `pineapple_app_gateway/start_server.sh` | Creates a venv, runs `pip install flask pyserial numpy` (unpinned), starts **v2** on 0.0.0.0:5000, then starts an **ngrok public tunnel** | Unpinned install. **Public exposure.** Tracks only a PID variable |

No systemd units, backup, restore, install or deployment scripts exist in the repository.

## 3. "0～9" program structure

**Not found.** No tracked file or folder outside `node_modules` has a numbered 0–9 program name. The only numbered folders are UML documentation (`UML/04…08`). The 0–9 structure is therefore **unconfirmed**: it may live on the Pi or in another repository. Nothing in this release claims to include it. The existing folder layout (`pineapple_final/`, `pineapple_app_gateway/`, `整合網頁/`, `app/`) is preserved.

## 4. Apps

| App | Path | Version (`app.json`) | Lockfile | API base URL (base commit) |
|---|---|---|---|---|
| Consumer | `app/Consumer_pineapple-ripeness-main/expo` | 1.0.0 | `package-lock.json` (+ `bun.lock`) | Hard-coded `DEFAULT_API_URL = 'http://192.168.43.251:5000'`; can be changed in the app's settings |
| Farmer | `app/Farmer_pineapple-ripeness-main` | 1.0.0 | `package-lock.json`, **generated in Step 5** (needs review) | Hard-coded `http://172.20.10.2:5000` (only `/ping` is used; Farmer has no scan contract) |

## 5. Model and feature schema

- Feature schema: `pineapple_final/feature_columns.json`, which is FIXED11 (`FIXED11-C2-W0/sha256:…`, see the Step 5 manifest). Also `deploy_meta.json`.
- Model registry: `pineapple_final/model_registry.json`, shipped as `{"models": {}}` — **no approved model**.
- Unapproved model files:
  - `pineapple_final/deploy_student.pkl` (sha256 `a57dbbbf…16a1`; status engineering-only in tests);
  - the R1 candidate (`88e0598b…`, kept in the R1 worktree and never packaged);
  - 7 more `.pkl` files under `enose_model_training/orkspace/deploy_rpi_*`.
- Model path: hard-coded `PINEAPPLE_DIR/deploy_student.pkl` in the Gateway; relative to the current directory in the CLI.

## 6. Data and config locations (base commit)

- AIR: `pineapple_final/air_base.json` (formal) and `air_base_test.json` (engineering). Both sit in the **code directory**; the repository copy is the legacy file without `_meta`.
- Scan history: `pineapple_app_gateway/scan_history/*.jsonl`, also in the **code directory**.
- Runtime config: `pineapple_final/pinenose_runtime.json`, or the path in `PINENOSE_RUNTIME_CONFIG`. Not shipped; `pinenose_runtime.example.json` is the template.
- Demo data: `pineapple_final/demo_data/*.xlsx` — **22 raw pineapple/AIR recordings**. The web page lists them on every page render.

## 7. Python requirements

- `pineapple_final/requirements_rpi.txt` pins numpy 2.4.3, pandas 3.0.1, scikit-learn 1.8.0, scipy 1.17.1, pyserial 3.5, joblib 1.5.3 and threadpoolctl 3.6.0. **It does not list Flask, Werkzeug or Jinja2**, although Gateway v2, the web page and the unified web all import Flask. **It does not list paramiko**, which `app_local.py` imports at the top.
- `pineapple_app_gateway/requirements_gateway.txt` pins Flask 3.1.3 and Werkzeug 3.1.8 (for v1).

## 8. To package (planned)

- Gateway v2.
- Safety layer.
- Inference CLI and AIR calibration CLI.
- Web page (`app_local.py`).
- Unified web (`app.py`, template, CSS).
- `feature_columns.json`, `deploy_meta.json`, and an empty `model_registry.json`.
- Firmware source, for reference.
- New ops tools:
  - service manager;
  - `rpi3_preflight.py`;
  - backup/rollback tool.
- Start/stop wrappers.
- Formal and engineering config templates.
- Release requirements.
- Manifests: release, API contract, app versions.
- `SHA256SUMS`.
- Operations documentation.

## 9. Not to package

- Every `.pkl`, including `deploy_student.pkl` (not approved) and the R1 candidate.
- `demo_data/` (raw xlsx), all raw XLSX, labels, training data, `enose_model_training/`, `evaluation/`.
- `air_base*.json` (legacy, no provenance) and any `scan_history/`.
- `pinenose_runtime.json` and `.env` (none exist).
- Gateway v1 (`app_gateway.py`), `start_server.sh` (ngrok), `pineapple_deployment_system/` (legacy app_local), `app_local_demo_early_corrected_v4.py`, `debug_features.py`, `inference_from_csv_updated.py`, `calibrate_air_from_csv.py`.
- The app source trees. The apps are tracked by version and API contract in the manifest; native binaries were never built (BLOCKED).
- `node_modules`, `__pycache__`, `.git`.
- README files that contain historical credentials. The `README_pineapple_final.md` credential was redacted in Step 5, but its history still holds the value, so the README is not packaged.

## 10. Missing or unconfirmed

- The 0–9 program structure (section 3).
- The photo/variety page on port 5002 and the model server at `192.168.0.176:5001`: not in this repository's accepted scope.
- The Pi's actual OS, architecture and Python version, and its current deployed files: unknown, and not checked (no Pi access).
- `requirements_rpi.txt` completeness: Flask is missing (section 7).
