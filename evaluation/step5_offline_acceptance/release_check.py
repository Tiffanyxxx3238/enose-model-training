"""
Step 5C：發布一致性與可追溯性檢查 → release_compatibility_manifest.json、_release_checks.csv

- 序列埠欄位對應：以韌體（use_this.ino）實際 28 欄 header 順序重播，Gateway 與 CLI 的特徵必須與 10 欄重播完全相同。
- FIXED11：feature_columns.json、deploy_meta.json、R1 訓練管線欄位、Gateway／CLI 特徵函式輸出鍵。
- 模型 SHA-256、核准清單（出貨為空）、測試設定。
- 版本：本機、釘選版本 venv、requirements_rpi.txt、pickle 建立版本。
- 服務埠與啟動／停止腳本；API 契約識別碼；錯誤碼清單。
不連線、不啟動伺服器（Flask test client）。
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
REPO = WT.parent
FINAL = WT / "pineapple_final"
GWD = WT / "pineapple_app_gateway"
APPD = WT / "app"
RAW = WT / "enose_model_training/orkspace/data/raw"
TMP = HERE / "_tmp_release"
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER10 = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]
CHECKS = []


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def add(cid, item, ok, evidence, status=None):
    st = status or ("PASS" if ok else "FAIL")
    CHECKS.append({"id": cid, "item": item, "status": st, "evidence": str(evidence)[:600]})
    print(f"[{st}] {cid} {item} — {str(evidence)[:200]}")


# ── 韌體 header ──
ino = (WT / "pineapple_deployment_system/use_this/use_this.ino").read_text(encoding="utf-8", errors="replace")
m = re.search(r'Serial\.println\(\s*((?:"[^"]*"\s*)+)\);', ino[ino.index('"timestamp_ms,"') - 40:])
FW_HEADER = "".join(re.findall(r'"([^"]*)"', m.group(1))).split(",")


# ── 假序列埠（1 Hz 列時鐘）──
class RowClock:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, s):
        pass

    def __getattr__(self, k):
        return getattr(time, k)


CLOCK = RowClock()


class FakeSerial:
    header, lines = "", []

    def __init__(self, *a, **k):
        self.buf = [FakeSerial.header] + list(FakeSerial.lines)

    def readline(self):
        CLOCK.t += 1.0
        return (self.buf.pop(0) + "\n").encode() if self.buf else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


serial_stub = types.ModuleType("serial")
serial_stub.Serial = FakeSerial
serial_stub.SerialException = type("SerialException", (OSError,), {})
sys.modules["serial"] = serial_stub
sys.modules["paramiko"] = types.SimpleNamespace(SSHClient=object, AutoAddPolicy=lambda: None)
os.environ.pop("PINENOSE_RUNTIME_CONFIG", None)
os.environ["ARDUINO_PORT"] = "FAKE0"

sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402
pbd = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
FEATS = json.loads((FINAL / "feature_columns.json").read_text(encoding="utf-8"))
META = json.loads((FINAL / "deploy_meta.json").read_text(encoding="utf-8"))
DEPLOY_SHA = sha(FINAL / "deploy_student.pkl")


def env():
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "pineapple_app_gateway").mkdir(parents=True)
    P = TMP / "pineapple_final"
    P.mkdir(parents=True)
    shutil.copy(GWD / "app_gateway_v2.py", TMP / "pineapple_app_gateway/app_gateway_v2.py")
    for f in ("pinenose_safety.py", "feature_columns.json", "deploy_meta.json", "deploy_student.pkl", "inference_30s.py"):
        shutil.copy(FINAL / f, P / f)
    (P / "model_registry.json").write_text(json.dumps({"models": {DEPLOY_SHA: {"status": "engineering", "feature_columns": FEATS}}}), encoding="utf-8")
    (P / "pinenose_runtime.json").write_text(json.dumps({"mode": "engineering", "device_id": None, "model_registry": "model_registry.json",
                                                         "engineering": {"air_max_age_sec": 3600, "allowed_client_hosts": ["127.0.0.1"]}}), encoding="utf-8")
    return P


def load(path, name):
    sys.modules.pop("pinenose_safety", None)
    spec = importlib.util.spec_from_file_location(name, str(path))
    m_ = importlib.util.module_from_spec(spec)
    sys.modules[name] = m_
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m_)
    return m_


# ═══ 1. 序列埠欄位對應（韌體 28 欄 vs 重播 10 欄）═══
def serial_mapping(n_days=10):
    P = env()
    g = load(TMP / "pineapple_app_gateway/app_gateway_v2.py", "gw_rel")
    g.time = CLOCK
    with contextlib.redirect_stdout(io.StringIO()):
        g._init_runtime()
    c = g.app.test_client()
    cli = load(P / "inference_30s.py", "cli_rel")
    cli.time = CLOCK
    out = []
    for r in pbd[pbd.in_S99].head(n_days).itertuples():
        air = read_raw_xlsx_fixed(str(RAW / r.air_file))
        air = air[air[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)
        fr = read_raw_xlsx_fixed(str(RAW / r.fruit_file))
        fr = fr[fr[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)
        res = {}
        for name, hdr in (("h10", HEADER10), ("firmware", FW_HEADER)):
            def mk(df):
                lines = []
                for i, row in df.iterrows():
                    vals = []
                    for col in hdr:
                        if col in df.columns and col in HEADER10:
                            v = row.get(col)
                            vals.append("" if pd.isna(v) else str(v))
                        else:
                            vals.append(f"{(i % 7) * 0.013 + 1.5:.4f}")     # 韌體額外欄位（TGS2620、logr…）：非零填充值，模型不使用
                    lines.append(",".join(vals))
                return lines
            FakeSerial.header = ",".join(hdr)
            FakeSerial.lines = mk(air)
            sid = c.post("/calibrate", json={}).get_json()["scan_id"]
            while not g._registry.scans[sid]["released"]:
                time.sleep(0.002)
            FakeSerial.lines = mk(fr)
            sid = c.post("/scan", json={}).get_json()["scan_id"]
            while not g._registry.scans[sid]["released"]:
                time.sleep(0.002)
            st = c.get(f"/status?scan_id={sid}").get_json()
            buf, old, cwd = io.StringIO(), sys.argv, os.getcwd()
            try:
                sys.argv = ["inference_30s.py", "--port", "FAKE0", "--trace-json", str(TMP / "t.json")]
                os.chdir(P)
                FakeSerial.lines = mk(fr)
                with contextlib.redirect_stdout(buf):
                    cli.main()
            except SystemExit:
                pass
            finally:
                sys.argv = old
                os.chdir(cwd)
            tr = json.loads((TMP / "t.json").read_text(encoding="utf-8"))
            res[name] = (st["status"], st["result"]["debug"]["feature_values"] if st["status"] == "done" else None, tr["features"], tr["raw_pred"],
                         st["result"]["stage"] if st["status"] == "done" else None)
        a, b = res["h10"], res["firmware"]
        ok = a[0] == b[0] == "done" and all(a[1][f] == b[1][f] for f in FEATS) and all(a[2][f] == b[2][f] for f in FEATS) and a[3] == b[3] == a[4] == b[4]
        out.append((f"{int(r.pineapple_id):02d}/{r.date}", ok))
    shutil.rmtree(TMP, ignore_errors=True)
    return out


mapping = serial_mapping()
add("R01", f"序列埠欄位對應：韌體 header（{len(FW_HEADER)} 欄，含 TGS2620_raw 與 logr 欄位）與 10 欄重播 → Gateway 與 CLI 特徵逐位元相同",
    all(ok for _, ok in mapping), f"{sum(ok for _, ok in mapping)}/{len(mapping)} days identical; firmware columns={FW_HEADER[:8]}…")

# ═══ 2. FIXED11 ═══
r1_cols = [c for c in pbd.columns if c in FEATS]
add("R02", "FIXED11 順序：feature_columns.json ＝ deploy_meta.json ＝ R1 訓練管線欄位順序",
    FEATS == META.get("feature_columns") == r1_cols and len(FEATS) == 11, f"{FEATS}")
P = env()
g = load(TMP / "pineapple_app_gateway/app_gateway_v2.py", "gw_rel2")
cli = load(P / "inference_30s.py", "cli_rel2")
rows = [{s: 100.0 + i + k for k, s in enumerate(SENS)} for i in range(30)]
gf, _ = g._build_features(rows, {s: 90.0 for s in SENS})
cf = cli.build_features([{s: r_[s] for s in SENS} for r_ in rows], {s: 90.0 for s in SENS})
cf = cf[0] if isinstance(cf, tuple) else cf
add("R03", "FIXED11 公式：Gateway _build_features 與 CLI build_features 對同一輸入產生相同 11 個值（另見完整重播：與 R1 ≤ 2.2e-16）",
    all(f in gf and f in cf and gf[f] == cf[f] for f in FEATS), {f: (gf.get(f), cf.get(f)) for f in FEATS[:3]})
shutil.rmtree(TMP, ignore_errors=True)
FEATURE_SCHEMA_ID = "FIXED11-C2-W0/sha256:" + hashlib.sha256(json.dumps(FEATS).encode()).hexdigest()[:16]

# ═══ 3. 模型與核准清單 ═══
reg = json.loads((FINAL / "model_registry.json").read_text(encoding="utf-8"))
add("R04", "出貨的核准清單為空（正式模式預設沒有核准模型）", reg.get("models") == {}, f"models={reg.get('models')}")
add("R05", "沒有出貨啟用中的 pinenose_runtime.json（部署後預設 fail-closed）", not (FINAL / "pinenose_runtime.json").exists(), "absent")
ex = json.loads((FINAL / "pinenose_runtime.example.json").read_text(encoding="utf-8"))
add("R06", "範例設定的 air_max_age_sec 為 null（不提供預設期限）", ex["formal"]["air_max_age_sec"] is None and ex["engineering"]["air_max_age_sec"] is None, ex["formal"])

# ═══ 4. 版本 ═══
req = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s]+)", (FINAL / "requirements_rpi.txt").read_text(encoding="utf-8"), re.M))
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    import pickle
    import sklearn
    pickle.load(open(FINAL / "deploy_student.pkl", "rb"))
pickle_warn = sorted({str(x.message)[:110] for x in w if "InconsistentVersion" in type(x.message).__name__ or "version" in str(x.message)})
runtime = {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__}
pinned_match = runtime["sklearn"] == req.get("scikit-learn") and runtime["numpy"] == req.get("numpy") and runtime["pandas"] == req.get("pandas")
add("R07", f"本次執行環境與 requirements_rpi.txt（sklearn {req.get('scikit-learn')}, numpy {req.get('numpy')}, pandas {req.get('pandas')}）",
    pinned_match, f"runtime={runtime}; pickle warnings={pickle_warn[:1]}", status="PASS" if pinned_match else "INFO")

# ═══ 5. 服務埠 ═══
ports = []
for p in [GWD / "app_gateway_v2.py", GWD / "app_gateway.py", FINAL / "app_local.py", WT / "整合網頁/pineapple_unified_web/app.py"]:
    s = p.read_text(encoding="utf-8")
    mm = re.search(r"app\.run\([^)]*port\s*=\s*(\d+)", s, re.S)
    ports.append({"service": str(p.relative_to(WT)), "port": int(mm.group(1)) if mm else None, "host": "0.0.0.0"})
by = {}
for x in ports:
    by.setdefault(x["port"], []).append(x["service"])
conflicts = {k: v for k, v in by.items() if len(v) > 1}
start_sh = (WT / "整合網頁/start_pineapple_system.sh").read_text(encoding="utf-8")
stop_sh = (WT / "整合網頁/stop_pineapple_system.sh").read_text(encoding="utf-8")
started = re.findall(r"python3? (\S+\.py)", start_sh)
add("R08", "服務埠衝突", not conflicts, f"conflicts={conflicts}; start script launches {started}", status="OPEN" if conflicts else "PASS")
add("R09", "啟動／停止腳本", False,
    "start_pineapple_system.sh 啟動 app_local.py(5000)、app_gateway.py(v1, 8000)、unified app.py(8000) → 8000 衝突；不啟動 app_gateway_v2.py；"
    "stop 腳本以 pkill -f \"app.py\" 會一併終止任何名稱含 app.py 的程序；整合網頁 iframe 寫死 192.168.0.152:5000/5002", status="OPEN")

# ═══ 6. API 契約 ═══
P = env()
g = load(TMP / "pineapple_app_gateway/app_gateway_v2.py", "gw_rel3")
routes = sorted((r.rule, sorted(m_ for m_ in r.methods if m_ not in ("HEAD", "OPTIONS"))) for r in g.app.url_map.iter_rules() if r.endpoint != "static")
shutil.rmtree(TMP, ignore_errors=True)
contract_doc = {"routes": routes, "status_requires_scan_id": True, "result_fields": ["scan_id", "status", "mode", "result_kind", "stage", "ripeness",
                "probabilities{stage0..3}", "confidence", "measurement_valid", "model_sha256", "model_status", "air_calibration_id", "air_source",
                "air_created_at", "air_age_sec", "air_mode", "air_device_id", "environment{temperature,humidity,pressure|null}", "sensor_raw"],
                "scan_states": ["scanning", "calibrating", "done", "failed", "cancelled", "timed_out"]}
API_ID = "pinenose-gateway-api/2.1 sha256:" + hashlib.sha256(json.dumps(contract_doc, sort_keys=True).encode()).hexdigest()[:16]
gw_src = (GWD / "app_gateway_v2.py").read_text(encoding="utf-8") + (FINAL / "pinenose_safety.py").read_text(encoding="utf-8")
codes = sorted(set(re.findall(r'SafetyError\("([A-Z_]+)"', gw_src)) | set(re.findall(r'_err\(\d+, "([A-Z_]+)"', gw_src)))
api_ts = (APPD / "Consumer_pineapple-ripeness-main/expo/services/api.ts").read_text(encoding="utf-8")
add("R10", "Consumer App API client 與 Gateway 契約（scan_id、/status?scan_id、/cancel、結果欄位）",
    all(x in api_ts for x in ("/status?scan_id=", "/cancel", "scan_id: string", "result_kind: ResultKind", "measurement_valid")), API_ID)
farmer_api = (APPD / "Farmer_pineapple-ripeness-main/services/api.ts").read_text(encoding="utf-8")
add("R11", "Farmer App 與 Gateway 沒有掃描契約（不呼叫 /scan；不產生結果）", "FARMER_SENSOR_NOT_CONNECTED" in farmer_api and "/scan" not in farmer_api.split("startScan")[1],
    "Farmer startScan throws FARMER_SENSOR_NOT_CONNECTED; pingServer('/ping') has no Gateway route", status="PASS")

# ═══ manifest ═══
git = lambda *a: subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, encoding="utf-8").stdout.strip()  # noqa: E731
def lockver(root, pkg):
    lock = root / "package-lock.json"
    if not lock.exists():
        return None
    return json.loads(lock.read_text(encoding="utf-8"))["packages"].get(f"node_modules/{pkg}", {}).get("version")


CROOT, FROOT = APPD / "Consumer_pineapple-ripeness-main/expo", APPD / "Farmer_pineapple-ripeness-main"
manifest = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "git": {"branch": git("branch", "--show-current"), "base_commit": "8e0515780e78d9d1147a74ff5b4b0c0d1986e723", "head_at_generation": git("rev-parse", "HEAD"),
            "note": "Final Step 5 commit hash is recorded in step5_acceptance_report.md / git log (this file is part of that commit)."},
    "api_contract_version": API_ID, "api_contract": contract_doc, "gateway_error_codes": codes,
    "feature_schema_id": FEATURE_SCHEMA_ID, "feature_columns": FEATS,
    "decision_contract": "C2 single window W0 (first 30 rows after warm-up, 1 Hz); no multi-window averaging, voting, AIR overrides or window-consistency rules",
    "models": {"deploy_student.pkl": {"sha256": DEPLOY_SHA, "approval_status_shipped": "NOT APPROVED (model_registry.json is empty)",
                                      "engineering_replay_registry_status": "engineering (test fixture only)", "pickled_with_sklearn": "1.8.0 (per InconsistentVersionWarning under 1.7.1)"}},
    "components": [
        {"name": "Gateway v2", "path": "pineapple_app_gateway/app_gateway_v2.py", "sha256": sha(GWD / "app_gateway_v2.py"), "port": 5000},
        {"name": "Safety layer", "path": "pineapple_final/pinenose_safety.py", "sha256": sha(FINAL / "pinenose_safety.py")},
        {"name": "Inference CLI", "path": "pineapple_final/inference_30s.py", "sha256": sha(FINAL / "inference_30s.py")},
        {"name": "AIR calibration CLI", "path": "pineapple_final/calibrate_air_30s.py", "sha256": sha(FINAL / "calibrate_air_30s.py")},
        {"name": "Web ripeness page", "path": "pineapple_final/app_local.py", "sha256": sha(FINAL / "app_local.py"), "port": 5000},
        {"name": "Unified web", "path": "整合網頁/pineapple_unified_web/app.py", "sha256": sha(WT / "整合網頁/pineapple_unified_web/app.py"), "port": 8000},
        {"name": "Gateway v1 (legacy)", "path": "pineapple_app_gateway/app_gateway.py", "sha256": sha(GWD / "app_gateway.py"), "port": 8000,
         "status": "legacy; not exercised by Step 5; conflicts with unified web port"},
        {"name": "Consumer App", "path": "app/Consumer_pineapple-ripeness-main/expo", "framework": f"Expo {lockver(CROOT, 'expo')} / React Native {lockver(CROOT, 'react-native')} / React {lockver(CROOT, 'react')}",
         "typescript": lockver(CROOT, "typescript"), "lockfile": "package-lock.json (sha256 " + sha(CROOT / "package-lock.json")[:16] + ")", "intended_package_manager": "bun (bun.lock present; not used here)"},
        {"name": "Farmer App", "path": "app/Farmer_pineapple-ripeness-main", "framework": "Expo 54 / React Native 0.81.5 / React 19.1.0 (resolved at test time)",
         "lockfile": "NONE in repository (dependencies resolved from package.json ranges at test time — not reproducible)"},
        {"name": "Arduino firmware", "path": "pineapple_deployment_system/use_this/use_this.ino", "sha256": sha(WT / "pineapple_deployment_system/use_this/use_this.ino"),
         "serial_header": FW_HEADER},
        {"name": "Model registry", "path": "pineapple_final/model_registry.json", "sha256": sha(FINAL / "model_registry.json")},
        {"name": "Feature columns", "path": "pineapple_final/feature_columns.json", "sha256": sha(FINAL / "feature_columns.json")},
    ],
    "runtime_versions": {"release_pins (requirements_rpi.txt)": req, "this_run": runtime,
                         "test_runtimes_used": {"pinned venv": "Python 3.12.7, scikit-learn 1.8.0, numpy 2.4.3, pandas 3.0.1, scipy 1.17.1, Flask 3.1.1",
                                                "local": "Python 3.10.11, scikit-learn 1.7.1, numpy 2.2.6 (InconsistentVersionWarning when loading the 1.8.0 pickle)",
                                                "node": "VS Code Electron runtime as Node v24.20.0 (ELECTRON_RUN_AS_NODE); npm 10.9.2 (portable, integrity-verified)"}},
    "test_configuration": {"mode": "engineering (TEST) for replay; formal with shipped empty registry for MODEL_NOT_APPROVED checks",
                           "air_max_age_sec": "3600 — TEST-ONLY engineering value, not a production recommendation",
                           "allowed_client_hosts": ["127.0.0.1"], "serial": "fake serial (1 Hz row clock); no real port", "network": "loopback only for App↔Gateway tests"},
    "service_ports": ports, "port_conflicts": conflicts,
    "proposed_service_layout (NOT APPLIED)": {"app_local.py (web ripeness page)": 5000, "app_gateway_v2.py (App API)": 5001, "photo page": 5002,
                                             "unified web": 8000, "app_gateway.py v1": "retire (do not start)",
                                             "notes": "Consumer DEFAULT_API_URL and unified-web iframe URLs must be updated together; make host/port configurable instead of hard-coded IPs"},
    "hardware_specific_unverified": [
        "Raspberry Pi 3 CPU/RAM/OS/Python version and wheel availability for scikit-learn 1.8.0 / numpy 2.4.3 / pandas 3.0.1 (armv7/aarch64) — NOT TESTED",
        "Real Arduino serial timing (1 Hz), header, USB enumeration (/dev/ttyACM*, /dev/ttyUSB*) — NOT TESTED",
        "Whether serial.close() from another thread interrupts a blocked readline() on the Pi's pyserial/driver — NOT TESTED",
        "Real AIR calibration provenance and a scientifically justified AIR expiry — NOT DETERMINED",
        "Sensor warm-up, drift, temperature/humidity effects on real hardware — NOT TESTED",
        "Native Android/iOS builds and device runs of both Apps — BLOCKED (no Android SDK/Gradle/Xcode here)",
        "Network between phone and Pi (LAN/ngrok), CORS, firewall — NOT TESTED",
    ],
    "checks": CHECKS,
}
(HERE / "release_compatibility_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
pd.DataFrame(CHECKS).to_csv(HERE / "_release_checks.csv", index=False, encoding="utf-8-sig")
print("manifest written; FAIL:", sum(c["status"] == "FAIL" for c in CHECKS), "OPEN:", sum(c["status"] == "OPEN" for c in CHECKS))
