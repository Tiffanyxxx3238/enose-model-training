"""
Step 5B：完整歷史重播（真實修改後的 Gateway、網頁 CLI、網頁 app_local、整合網頁）

依 step5_protocol.md（已先 commit）：
- S99 的 99 個水果日，每天只算一次。
- AIR：同日 AIR xlsx 經 Gateway /calibrate（工程模式）重播。
- 水果：同日水果 xlsx 經假序列埠以 1 Hz 列時鐘重播：
  - Gateway /scan（重複執行兩次）；
  - CLI inference_30s.main()（重複執行兩次，輸出 trace）；
  - 網頁 app_local /infer（以 CLI 實際輸出作為遠端輸出）。
- 與 R1 訓練管線的 FIXED11 特徵、AIR_A0 比對；也用 Consumer App 真實的 validateRpiResult 驗證每一筆 API 結果（由 run_step5.py 呼叫 Node 執行）。

測試替身：假序列埠（1 Hz 列時鐘）、SSH 由 run_remote_script 替換為回傳 CLI 實際輸出。不連接任何設備、不開網路。
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import pickle
import re
import shutil
import socket
import sys
import threading
import time
import types
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
T0 = time.time()
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
FINAL = WT / "pineapple_final"
GWD = WT / "pineapple_app_gateway"
WEB = WT / "整合網頁/pineapple_unified_web"
RAW = WT / "enose_model_training/orkspace/data/raw"
TAG = os.environ.get("REPLAY_TAG", "")          # 不同執行環境的輸出檔後綴
TMP = HERE / f"_tmp_replay{TAG}"
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]
DEPLOY_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
TOL_FEAT, TOL_AIR_REL, TOL_PROBA_API, TOL_PROBA_WEB = 1e-9, 1e-9, 5e-7, 5e-5
TEST_ONLY_AIR_MAX_AGE_SEC = 3600

NET = []
socket.socket.connect = lambda self, addr: (NET.append(str(addr)), (_ for _ in ()).throw(OSError("network disabled")))[1]


# ── 1 Hz 列時鐘＋假序列埠 ──
class RowClock:
    """time() 不會自己前進；每讀一列序列資料前進 1 秒（模擬 Arduino 1 Hz 輸出）。"""

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
    lines = []
    instances = []

    def __init__(self, port, baud, timeout=1):
        self.buf = [",".join(HEADER)] + list(FakeSerial.lines)
        self.closed = False
        FakeSerial.instances.append(self)

    def readline(self):
        CLOCK.t += 1.0
        return (self.buf.pop(0) + "\n").encode() if self.buf else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


serial_stub = types.ModuleType("serial")
serial_stub.Serial = FakeSerial
serial_stub.SerialException = type("SerialException", (OSError,), {})
sys.modules["serial"] = serial_stub
paramiko_stub = types.ModuleType("paramiko")
paramiko_stub.SSHClient = type("SSH", (), {"set_missing_host_key_policy": lambda *a: None,
                                           "connect": lambda *a, **k: (_ for _ in ()).throw(OSError("SSH disabled")), "close": lambda *a: None})
paramiko_stub.AutoAddPolicy = lambda: None
sys.modules["paramiko"] = paramiko_stub

# ── 資料 ──
sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402
pbd = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
exc = pd.read_csv(EVAL / "r1_controlled_retraining/excluded_samples.csv", encoding="utf-8-sig")
FEATS = json.loads((FINAL / "feature_columns.json").read_text(encoding="utf-8"))


def to_lines(df):
    return [",".join("" if pd.isna(row.get(c)) else str(row.get(c)) for c in HEADER) for _, row in df.iterrows()]


def complete(df):
    return df[df[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)


# ── 暫存環境（工程測試模式）──
if TMP.exists():
    shutil.rmtree(TMP)
P = TMP / "pineapple_final"
(TMP / "pineapple_app_gateway").mkdir(parents=True)
P.mkdir(parents=True)
shutil.copy(GWD / "app_gateway_v2.py", TMP / "pineapple_app_gateway/app_gateway_v2.py")
for f in ("pinenose_safety.py", "feature_columns.json", "deploy_meta.json", "deploy_student.pkl", "inference_30s.py", "app_local.py"):
    shutil.copy(FINAL / f, P / f)
(P / "model_registry.json").write_text(json.dumps({"_note": "TEST FIXTURE ONLY — engineering replay, not an approval",
                                                   "models": {DEPLOY_SHA: {"status": "engineering", "feature_columns": FEATS}}}), encoding="utf-8")
(P / "pinenose_runtime.json").write_text(json.dumps({"_note": "TEST-ONLY configuration", "mode": "engineering", "device_id": None,
                                                     "model_registry": "model_registry.json",
                                                     "engineering": {"air_max_age_sec": TEST_ONLY_AIR_MAX_AGE_SEC, "allowed_client_hosts": ["127.0.0.1"],
                                                                     "allow_demo_air": False}}), encoding="utf-8")
os.environ.pop("PINENOSE_RUNTIME_CONFIG", None)
os.environ["ARDUINO_PORT"] = "FAKE0"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m          # Flask 依模組名稱找 templates 資料夾
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m)
    return m


sys.modules.pop("pinenose_safety", None)
g = load(TMP / "pineapple_app_gateway/app_gateway_v2.py", "gw_replay")
g.time = CLOCK
with contextlib.redirect_stdout(io.StringIO()):
    g._init_runtime()
assert g._handle is not None and g._handle.status == "engineering", g._model_error
client = g.app.test_client()
cli = load(P / "inference_30s.py", "cli_replay")
cli.time = CLOCK
web = load(P / "app_local.py", "app_local_replay")
uweb = load(WEB / "app.py", "unified_web")
REF_MODEL = pickle.load(open(FINAL / "deploy_student.pkl", "rb"))
REF_MODEL.set_params(n_jobs=1)


def wait_done(sid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = g._registry.scans.get(sid)
        if s and s["released"]:
            return client.get(f"/status?scan_id={sid}").get_json()
        time.sleep(0.002)
    raise TimeoutError(sid)


def gw_calibrate(lines):
    FakeSerial.lines = lines
    r = client.post("/calibrate", json={})
    assert r.status_code == 200, r.get_json()
    return wait_done(r.get_json()["scan_id"])


def gw_scan(lines):
    FakeSerial.lines = lines
    r = client.post("/scan", json={})
    if r.status_code != 200:
        return {"status": "rejected", "http": r.status_code, **(r.get_json() or {})}
    return wait_done(r.get_json()["scan_id"])


def run_cli(lines, trace):
    FakeSerial.lines = lines
    old_argv, old_cwd, buf, code = sys.argv, os.getcwd(), io.StringIO(), 0
    try:
        sys.argv = ["inference_30s.py", "--port", "FAKE0", "--trace-json", str(trace)]
        os.chdir(P)
        with contextlib.redirect_stdout(buf):
            cli.main()
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv, _ = old_argv, os.chdir(old_cwd)
    return code, buf.getvalue()


def schema_errors(st, sid):
    e = []
    r = st.get("result") or {}
    if st.get("scan_id") != sid or st.get("status") != "done" or st.get("result_kind") != "TEST" or st.get("mode") != "engineering":
        e.append("envelope")
    if r.get("scan_id") != sid or r.get("status") != "SUCCESS" or r.get("result_kind") != "TEST" or r.get("measurement_valid") is not True:
        e.append("result header")
    if r.get("stage") not in (0, 1, 2, 3) or r.get("ripeness") not in ("unripe", "transition", "ripe", "overripe"):
        e.append("stage")
    p = [r.get("probabilities", {}).get(f"stage{i}") for i in range(4)]
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in p) or abs(sum(p) - 1) > 1e-5 or int(np.argmax(p)) != r.get("stage"):
        e.append("probabilities")
    if not re.fullmatch(r"[0-9a-f]{64}", str(r.get("model_sha256"))) or r.get("model_status") != "engineering":
        e.append("model")
    if not r.get("air_calibration_id") or r.get("air_source") != "live" or r.get("air_mode") != "engineering":
        e.append("air provenance")
    fv = r.get("debug", {}).get("feature_values", {})
    # JSON 物件不保留鍵順序（Flask jsonify 會排序）；順序由 load_model_handle 在載入時強制檢查，這裡檢查名稱集合與數值
    if sorted(fv) != sorted(FEATS) or any(not math.isfinite(v) for v in fv.values()):
        e.append("features")
    return e


rows = []
payloads = []
S99 = pbd[pbd.in_S99].reset_index(drop=True)
print(f"S99 fruit-days: {len(S99)} (unique pineapple-days: {S99[['pineapple_id', 'date']].drop_duplicates().shape[0]})")
for k, r in S99.iterrows():
    key = f"{int(r.pineapple_id):02d}/{r.date}"
    out = {"fruit_day": key, "pineapple_id": int(r.pineapple_id), "date": str(r.date), "fruit_file": r.fruit_file, "air_file": r.air_file}
    try:
        air_df = complete(read_raw_xlsx_fixed(str(RAW / r.air_file)))
        fruit_df = complete(read_raw_xlsx_fixed(str(RAW / r.fruit_file)))
        out.update(air_rows=len(air_df), fruit_rows=len(fruit_df))
        # AIR：真實 /calibrate
        cal = gw_calibrate(to_lines(air_df))
        out["calibration_status"] = cal["status"]
        airf = json.loads((P / "air_base_test.json").read_text(encoding="utf-8"))
        airf["_meta"]["test_fixture_note"] = "historical AIR replayed offline via fake serial — NOT a real measurement"
        (P / "air_base_test.json").write_text(json.dumps(airf), encoding="utf-8")
        out["air_rel_diff_vs_R1"] = max(abs(airf[s] - r[f"air_A0_{s}"]) / abs(r[f"air_A0_{s}"]) for s in SENS)
        # Gateway 兩次
        lines = to_lines(fruit_df)
        st1, st2 = gw_scan(lines), gw_scan(lines)
        out["gateway_status"] = st1.get("status")
        if st1.get("status") != "done":
            out["gateway_reason"] = st1.get("reason_code") or st1.get("error")
            rows.append(out)
            print(f"[{k + 1:3d}/{len(S99)}] {key} gateway {st1.get('status')} {out['gateway_reason']}")
            continue
        g1 = st1["result"]
        gp1 = np.array([g1["probabilities"][f"stage{i}"] for i in range(4)])
        gp2 = np.array([st2["result"]["probabilities"][f"stage{i}"] for i in range(4)])
        gfeat = g1["debug"]["feature_values"]
        out.update(gateway_stage=g1["stage"], gateway_ripeness=g1["ripeness"], gateway_repeat_identical=bool(np.array_equal(gp1, gp2) and st2["result"]["stage"] == g1["stage"]),
                   schema_errors=";".join(schema_errors(st1, st1["scan_id"])) or "none", air_calibration_id=g1["air_calibration_id"])
        payloads.append({"fruit_day": key, "scan_id": st1["scan_id"], "result_kind": st1["result_kind"], "status": st1})
        # R1 訓練管線特徵
        out["feat_diff_vs_R1"] = max(abs(gfeat[f] - float(r[f])) for f in FEATS)
        # 參考模型（同一個 pkl、n_jobs=1）作交叉檢查（不是替代測試）
        rp = REF_MODEL.predict_proba(pd.DataFrame([[float(r[f]) for f in FEATS]], columns=FEATS))[0]
        out["proba_diff_vs_model_on_R1_features"] = float(np.abs(np.round(rp, 6) - gp1).max())
        # CLI 兩次
        t1, t2 = TMP / "trace1.json", TMP / "trace2.json"
        c1, o1 = run_cli(lines, t1)
        c2, o2 = run_cli(lines, t2)
        out["cli_exit"] = c1
        if c1 != 0:
            out["cli_reason"] = (re.search(r"❌ 無法推論：(.+)", o1) or [None, o1[-200:]])[1]
            rows.append(out)
            print(f"[{k + 1:3d}/{len(S99)}] {key} CLI exit {c1} {out['cli_reason']}")
            continue
        tr1, tr2 = json.loads(t1.read_text(encoding="utf-8")), json.loads(t2.read_text(encoding="utf-8"))
        cp1 = np.array(tr1["proba"], dtype=float)
        out.update(cli_stage=int(tr1["raw_pred"]), cli_displayed_stage=int(tr1["displayed_pred"]), cli_result_kind=tr1["result_kind"],
                   cli_repeat_identical=bool(tr1["proba"] == tr2["proba"] and tr1["raw_pred"] == tr2["raw_pred"]),
                   feat_diff_gateway_vs_cli=max(abs(gfeat[f] - float(tr1["features"][f])) for f in FEATS),
                   proba_diff_gateway_vs_cli=float(np.abs(gp1 - cp1).max()),
                   cli_rows_equal_W0=bool([{s: float(x[s]) for s in SENS} for x in tr1["rows"]] ==
                                          [{s: float(v) for s, v in zip(SENS, row)} for row in fruit_df[[f"{s}_raw" for s in SENS]].to_numpy(float)[:30]]),
                   cli_air_equals_gateway_air=bool(all(abs(tr1["air"][s] - airf[s]) == 0 for s in SENS)),
                   cli_air_calibration_id=tr1["air_provenance"]["calibration_id"])
        # 網頁 app_local /infer（遠端輸出＝CLI 實際輸出）
        web.run_remote_script = lambda script, args="", _o=o1: _o
        html = web.app.test_client().post("/infer", data={"warmup_sec": "0"}).get_data(as_text=True)
        pw = web.parse_infer_output(o1)
        wp = np.array([x["prob"] for x in sorted(pw["probabilities"], key=lambda x: x["stage"])])
        out.update(web_success=pw["success"], web_raw_stage=pw["raw_stage"], web_result_kind=pw["result_kind"],
                   web_display_text=pw["display_text"], web_proba_diff_vs_cli=float(np.abs(wp - cp1).max()) if len(wp) == 4 else None,
                   web_html_shows_stage=bool(pw["display_text"] and pw["display_text"] in html), web_html_test_banner="TEST（工程測試結果" in html)
        rows.append(out)
        print(f"[{k + 1:3d}/{len(S99)}] {key} G{out['gateway_stage']} C{out['cli_stage']} W{out['web_raw_stage']} "
              f"dF={out['feat_diff_gateway_vs_cli']:.1e} dP={out['proba_diff_gateway_vs_cli']:.1e} dR1={out['feat_diff_vs_R1']:.1e}")
    except Exception as e:  # noqa: BLE001
        out["harness_error"] = repr(e)[:300]
        rows.append(out)
        print(f"[{k + 1:3d}/{len(S99)}] {key} HARNESS ERROR {e!r}")

df = pd.DataFrame(rows)


def ok_row(x):
    return (x.get("gateway_status") == "done" and x.get("cli_exit") == 0 and x.get("schema_errors") == "none"
            and x["gateway_stage"] == x["cli_stage"] == x["web_raw_stage"] and x["cli_displayed_stage"] == x["cli_stage"]
            and x["feat_diff_gateway_vs_cli"] <= TOL_FEAT and x["feat_diff_vs_R1"] <= TOL_FEAT and x["air_rel_diff_vs_R1"] <= TOL_AIR_REL
            and x["proba_diff_gateway_vs_cli"] <= TOL_PROBA_API and x["web_proba_diff_vs_cli"] is not None and x["web_proba_diff_vs_cli"] <= TOL_PROBA_WEB
            and x["gateway_repeat_identical"] and x["cli_repeat_identical"] and x["cli_rows_equal_W0"] and x["cli_air_equals_gateway_air"]
            and x["web_success"] and x["web_result_kind"] == "TEST" and x["cli_result_kind"] == "TEST" and x["web_html_shows_stage"] and x["web_html_test_banner"]
            and x["cli_air_calibration_id"] == x["air_calibration_id"])


df["replay_verdict"] = ["PASS" if ok_row(x) else "FAIL" for x in df.to_dict("records")]
df.to_csv(HERE / f"full_replay_results{TAG}.csv", index=False, encoding="utf-8-sig")
(HERE / f"_replay_payloads{TAG}.json").write_text(json.dumps(payloads, ensure_ascii=False), encoding="utf-8")

# 排除清單
excl = [{"fruit_day": f"{int(x.pineapple_id):02d}/{x.date}", "set": "S100 only (not S99)", "reason": "fruit file identical to AIR file (R1 FRUIT_EQ_AIR rule)"}
        for x in pbd[~pbd.in_S99].itertuples()]
excl += [{"fruit_day": f"{int(x.pineapple_id):02d}/{x.date}", "set": "R1 excluded_samples.csv", "reason": x.exclusion_reason} for x in exc.itertuples()]
pd.DataFrame(excl).to_csv(HERE / "replay_exclusions.csv", index=False, encoding="utf-8-sig")
# 整合網頁
uw = uweb.app.test_client().get("/").get_data(as_text=True)
summary = {
    "eligible_S99_fruit_days": int(len(S99)), "unique_pineapples": int(S99.pineapple_id.nunique()), "replayed_rows": int(len(df)),
    "replay_PASS": int((df.replay_verdict == "PASS").sum()), "replay_FAIL": int((df.replay_verdict == "FAIL").sum()),
    "gateway_not_done": df[df.gateway_status != "done"][["fruit_day", "gateway_status"]].to_dict("records") if "gateway_status" in df else [],
    "max_feat_diff_gateway_vs_cli": float(df.feat_diff_gateway_vs_cli.max()), "max_feat_diff_vs_R1": float(df.feat_diff_vs_R1.max()),
    "max_air_rel_diff_vs_R1": float(df.air_rel_diff_vs_R1.max()), "max_proba_diff_gateway_vs_cli": float(df.proba_diff_gateway_vs_cli.max()),
    "max_web_proba_diff_vs_cli": float(df.web_proba_diff_vs_cli.max()), "max_proba_diff_vs_model_on_R1_features": float(df.proba_diff_vs_model_on_R1_features.max()),
    "stage_agreement_gateway_cli_web": int(((df.gateway_stage == df.cli_stage) & (df.cli_stage == df.web_raw_stage)).sum()),
    "excluded_rows_reported": len(excl),
    "unified_web_iframe_targets": re.findall(r'src="([^"]+)"', uw),
    "network_attempts": NET, "seconds": round(time.time() - T0, 1),
    "runtime": {"python": sys.version.split()[0], "sklearn": __import__("sklearn").__version__, "numpy": np.__version__, "pandas": pd.__version__},
    "stage_distribution_gateway": df.gateway_stage.value_counts().sort_index().to_dict(),
}
(HERE / f"_replay_summary{TAG}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if summary["replay_FAIL"] == 0 else 1)
