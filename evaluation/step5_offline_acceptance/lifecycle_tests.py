"""
Step 5B：掃描生命週期與失敗案例（真實 Gateway／CLI／app_local 進入點；假序列埠）＋ Gateway API 契約（HTTP 狀態與錯誤碼）

補充 Step 4B 回歸測試沒有涵蓋的案例：
- Inf ADC；header 欄位錯誤或缺欄；
- AIR／歷史檔案實際損毀或無法寫入（真實檔案系統）；
- CLI 特徵順序錯誤；
- 正式／工程模式切換；
- 每個端點在各種情況下的 HTTP 狀態與錯誤碼。

輸出：scan_lifecycle_results.csv、storage_integrity_results.csv、_gateway_contract_rows.json（由 run_step5.py 併入 api_contract_results.csv）。
"""
import contextlib
import importlib.util
import io
import json
import os
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

import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
FINAL = WT / "pineapple_final"
GWD = WT / "pineapple_app_gateway"
RAW = WT / "enose_model_training/orkspace/data/raw"
TMP = HERE / "_tmp_lifecycle"
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]
DEPLOY_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
FEATS = json.loads((FINAL / "feature_columns.json").read_text(encoding="utf-8"))
NET = []
socket.socket.connect = lambda self, addr: (NET.append(str(addr)), (_ for _ in ()).throw(OSError("network disabled")))[1]
os.environ.pop("PINENOSE_RUNTIME_CONFIG", None)
os.environ["ARDUINO_PORT"] = "FAKE0"


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
    lines, header_line, gate_after = [], ",".join(HEADER), None
    gate = threading.Event()
    instances = []

    def __init__(self, port, baud, timeout=1):
        self.buf = ([FakeSerial.header_line] if FakeSerial.header_line else []) + list(FakeSerial.lines)
        self.calls, self.closed = 0, threading.Event()
        FakeSerial.instances.append(self)

    def readline(self):
        self.calls += 1
        CLOCK.t += 1.0
        if self.closed.is_set():
            raise serial_stub.SerialException("closed")
        if FakeSerial.gate_after is not None and self.calls > FakeSerial.gate_after:
            while not FakeSerial.gate.is_set():
                if self.closed.wait(0.005):
                    raise serial_stub.SerialException("closed")
        return (self.buf.pop(0) + "\n").encode() if self.buf else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed.set()


def serial_reset(lines, header_line=",".join(HEADER), gate_after=None):
    FakeSerial.lines, FakeSerial.header_line, FakeSerial.gate_after = list(lines), header_line, gate_after
    FakeSerial.gate, FakeSerial.instances = threading.Event(), []


serial_stub = types.ModuleType("serial")
serial_stub.Serial = FakeSerial
serial_stub.SerialException = type("SerialException", (OSError,), {})
sys.modules["serial"] = serial_stub
paramiko_stub = types.ModuleType("paramiko")
paramiko_stub.SSHClient = object
paramiko_stub.AutoAddPolicy = lambda: None
sys.modules["paramiko"] = paramiko_stub

sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402
pbd = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
R0 = pbd[pbd.in_S99].iloc[0]
_f = read_raw_xlsx_fixed(str(RAW / R0.fruit_file))
_f = _f[_f[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True)
LINES = [",".join("" if pd.isna(row.get(c)) else str(row.get(c)) for c in HEADER) for _, row in _f.iloc[:40].iterrows()]
AIR = {s: float(R0[f"air_A0_{s}"]) for s in SENS}

RESULTS, CONTRACT, STORAGE = [], [], []


def rec(group, tid, name, ok, ev, entry="Gateway v2 (Flask test client)", kind="RUNTIME (fake serial)"):
    (STORAGE if group == "STORAGE" else RESULTS).append({"group": group, "id": tid, "test": name, "entrypoint": entry, "kind": kind,
                                                         "verdict": "PASS" if ok else "FAIL", "evidence": str(ev)[:400]})
    print(f"[{'PASS' if ok else 'FAIL'}] {tid} {name} — {str(ev)[:170]}")


def check(group, tid, name, fn, entry="Gateway v2 (Flask test client)"):
    try:
        ok, ev = fn()
    except Exception as e:  # noqa: BLE001
        ok, ev = False, f"TEST ERROR {e!r}"
    rec(group, tid, name, ok, ev, entry)


def air_doc(mode="formal", **over):
    return {**AIR, **over, "_meta": {"source": "live", "calibration_id": "fixture" + "0" * 25, "created_at": datetime.now(timezone.utc).isoformat(),
                                     "mode": mode, "device_id": None, "sample_count": 30, "test_fixture_note": "test fixture — NOT a real measurement"}}


_env_n = [0]


def env(mode="engineering", registry="engineering", air="auto", features=None):
    # 每個測試環境用自己的資料夾（Windows 上前一個測試的執行緒可能仍持有檔案）
    _env_n[0] += 1
    R = TMP / f"e{_env_n[0]:03d}"
    (R / "pineapple_app_gateway").mkdir(parents=True)
    P = R / "pineapple_final"
    P.mkdir(parents=True)
    shutil.copy(GWD / "app_gateway_v2.py", R / "pineapple_app_gateway/app_gateway_v2.py")
    for f in ("pinenose_safety.py", "feature_columns.json", "deploy_meta.json", "deploy_student.pkl", "inference_30s.py", "app_local.py", "model_registry.json"):
        shutil.copy(FINAL / f, P / f)
    if features is not None:
        (P / "feature_columns.json").write_text(json.dumps(features), encoding="utf-8")
    if registry == "engineering":
        (P / "model_registry.json").write_text(json.dumps({"models": {DEPLOY_SHA: {"status": "engineering", "feature_columns": FEATS}}}), encoding="utf-8")
    cfg = {"mode": mode, "device_id": None, "model_registry": "model_registry.json"}
    cfg[mode] = {"air_max_age_sec": 3600, **({"allowed_client_hosts": ["127.0.0.1"], "allow_demo_air": False} if mode == "engineering" else {})}
    (P / "pinenose_runtime.json").write_text(json.dumps(cfg), encoding="utf-8")
    if air == "auto":
        (P / ("air_base.json" if mode == "formal" else "air_base_test.json")).write_text(json.dumps(air_doc(mode)), encoding="utf-8")
    elif air is not None:
        (P / ("air_base.json" if mode == "formal" else "air_base_test.json")).write_text(air, encoding="utf-8")
    return P


_n = [0]


def gateway(**kw):
    P = env(**kw)
    _n[0] += 1
    sys.modules.pop("pinenose_safety", None)
    spec = importlib.util.spec_from_file_location(f"gw{_n[0]}", str(P.parent / "pineapple_app_gateway/app_gateway_v2.py"))
    g = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(g)
        g._init_runtime()
    g.time = CLOCK
    return g, g.app.test_client(), P


def done(g, c, sid):
    end = time.time() + 30
    while time.time() < end:
        s = g._registry.scans.get(sid)
        if s and s["released"]:
            return c.get(f"/status?scan_id={sid}").get_json()
        time.sleep(0.002)
    raise TimeoutError


def scan(g, c, lines, header_line=",".join(HEADER)):
    serial_reset(lines, header_line)
    r = c.post("/scan", json={})
    if r.status_code != 200:
        return {"status": "rejected", "http": r.status_code, **r.get_json()}
    return done(g, c, r.get_json()["scan_id"])


def bad(kind):
    out = list(LINES)
    v = out[5].split(",")
    v[3] = {"inf": "inf", "-inf": "-inf", "text": "abc"}[kind]
    out[5] = ",".join(v)
    return out


def run_cli(P, lines, argv=(), header_line=",".join(HEADER)):
    sys.modules.pop("pinenose_safety", None)
    spec = importlib.util.spec_from_file_location(f"cli{time.time_ns()}", str(P / "inference_30s.py"))
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m)
    m.time = CLOCK
    serial_reset(lines, header_line)
    old, cwd, buf, code = sys.argv, os.getcwd(), io.StringIO(), 0
    try:
        sys.argv = ["inference_30s.py", "--port", "FAKE0", *argv]
        os.chdir(P)
        with contextlib.redirect_stdout(buf):
            m.main()
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = old
        os.chdir(cwd)
    return code, buf.getvalue()


def stage_printed(out):
    return bool(re.search(r"成熟度判定：|原始模型分類：Stage", out))


print("=" * 70 + "\nLIFECYCLE / FAILURE CASES\n" + "=" * 70)
for kind in ("inf", "-inf", "text"):
    def _t(kind=kind):
        g, c, P = gateway()
        st = scan(g, c, bad(kind))
        code, out = run_cli(P, bad(kind))
        return (st["status"] == "failed" and st["reason_code"] == "ADC_INVALID" and st["result"] is None and code == 2 and "ADC_INVALID" in out
                and not stage_printed(out) and g._history.read("TEST") == []), f"Gateway {st['status']}/{st['reason_code']}; CLI exit {code}"
    check("LIFECYCLE", f"L01-ADC-{kind.upper()}", f"ADC {kind} → Gateway 與 CLI 都失敗、不寫入", _t, "Gateway v2 + CLI inference_30s.main()")

for tid, name, hdr, want in (("L02-HEADER-MISSING-COLUMN", "header 少一欄（資料列欄數不符）", ",".join(HEADER[:-1]), ("INSUFFICIENT_ROWS",)),
                             ("L03-HEADER-WRONG-NAMES", "header 欄位名稱錯誤（MQ2_raw→MQ2）", ",".join(h.replace("_raw", "") for h in HEADER), ("ADC_INVALID",)),
                             ("L04-HEADER-ABSENT", "沒有 header", None, ("SERIAL_HEADER_TIMEOUT",))):
    def _t(hdr=hdr, want=want):
        g, c, P = gateway()
        st = scan(g, c, LINES, header_line=hdr)
        code, out = run_cli(P, LINES, header_line=hdr)
        cli_reason = (re.search(r"無法推論：(\w+)", out) or [None, "?"])[1]
        return (st["status"] == "failed" and st["reason_code"] in want and st["result"] is None and code == 2 and not stage_printed(out)), \
            f"Gateway {st['status']}/{st['reason_code']}; CLI exit {code} {cli_reason}"
    check("LIFECYCLE", tid, f"{name} → 失敗、不產生 Stage", _t, "Gateway v2 + CLI inference_30s.main()")


def t_cli_feature_order():
    swapped = [FEATS[1], FEATS[0]] + FEATS[2:]
    P = env(features=swapped)
    code, out = run_cli(P, LINES)
    return code == 2 and "MODEL_FEATURE_MISMATCH" in out and not stage_printed(out), f"CLI exit {code} MODEL_FEATURE_MISMATCH={'MODEL_FEATURE_MISMATCH' in out}"


check("LIFECYCLE", "L05-CLI-FEATURE-ORDER", "CLI：feature_columns.json 順序錯誤 → MODEL_FEATURE_MISMATCH", t_cli_feature_order, "CLI inference_30s.main()")


def t_cli_checksum():
    P = env()
    with open(P / "deploy_student.pkl", "ab") as fh:
        fh.write(b"\x00")
    code, out = run_cli(P, LINES)
    return code == 2 and "MODEL_NOT_APPROVED" in out and not stage_printed(out), f"modified model file → CLI exit {code}"


check("LIFECYCLE", "L06-CLI-CHECKSUM", "CLI：模型檔 SHA-256 不在清單 → MODEL_NOT_APPROVED", t_cli_checksum, "CLI inference_30s.main()")


def t_formal_empty():
    g, c, P = gateway(mode="formal", registry="shipped")
    r = c.post("/scan", json={})
    code, out = run_cli(P, LINES)
    return r.status_code == 503 and r.get_json()["error"] == "MODEL_NOT_APPROVED" and code == 2 and "MODEL_NOT_APPROVED" in out, \
        f"Gateway /scan {r.status_code}/{r.get_json()['error']}; CLI exit {code}"


check("LIFECYCLE", "L07-FORMAL-NO-APPROVED-MODEL", "正式模式＋出貨核准清單（空）→ Gateway 與 CLI 都回 MODEL_NOT_APPROVED", t_formal_empty, "Gateway v2 + CLI")


def t_transition():
    g, c, P = gateway()
    st = scan(g, c, LINES)
    sid = st["scan_id"]
    (P / "pinenose_runtime.json").write_text(json.dumps({"mode": "formal", "device_id": None, "model_registry": "model_registry.json",
                                                         "formal": {"air_max_age_sec": 3600}}), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        g._init_runtime()
    r1 = c.post("/scan", json={})
    old = c.get(f"/status?scan_id={sid}").get_json()
    up = c.post("/scan_records", json={"scan_id": sid, "result_kind": "FORMAL"})
    code, out = run_cli(P, LINES)
    return (st["status"] == "done" and st["result_kind"] == "TEST" and r1.status_code == 503 and r1.get_json()["error"] == "MODEL_NOT_APPROVED"
            and old["result_kind"] == "TEST" and old["mode"] == "engineering" and old.get("backend_mode") == "formal"
            and old["result"]["result_kind"] == "TEST" and up.status_code == 409
            and code == 2 and [x["scan_id"] for x in g._history.read("TEST")] == [sid] and g._history.read("FORMAL") == []), \
        (f"engineering scan {st['result_kind']} → switch to formal: /scan {r1.status_code}/{r1.get_json()['error']}; old scan result_kind stays "
         f"{old['result']['result_kind']} (envelope mode={old['mode']}, backend_mode={old.get('backend_mode')}); FORMAL upload {up.status_code}; CLI exit {code}")


check("LIFECYCLE", "L08-MODE-TRANSITION", "工程→正式切換：TEST 紀錄不轉換；正式模式沒有核准模型時拒絕", t_transition, "Gateway v2 + CLI")


def t_late_after_reload():
    """掃描進行中後端重新載入設定：舊掃描的提交仍依自己的 result_kind 寫入，不會被改成 FORMAL。"""
    g, c, P = gateway()
    serial_reset(LINES, gate_after=12)
    sid = c.post("/scan", json={}).get_json()["scan_id"]
    end = time.time() + 10
    while time.time() < end and not (FakeSerial.instances and FakeSerial.instances[0].calls > 12):
        time.sleep(0.005)
    (P / "pinenose_runtime.json").write_text(json.dumps({"mode": "formal", "device_id": None, "model_registry": "model_registry.json",
                                                         "formal": {"air_max_age_sec": 3600}}), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        g._init_runtime()
    FakeSerial.gate.set()
    st = done(g, c, sid)
    f, t = g._history.read("FORMAL"), g._history.read("TEST")
    return f == [] and (st["status"] != "done" or (st["result"]["result_kind"] == "TEST" and [x["scan_id"] for x in t] == [sid])), \
        f"in-flight scan after reload → {st['status']} kind={(st.get('result') or {}).get('result_kind')} formal={len(f)} test={len(t)}"


check("LIFECYCLE", "L09-INFLIGHT-RELOAD", "掃描進行中切換設定：結果不會變成 FORMAL、不寫入正式歷史", t_late_after_reload)

print("=" * 70 + "\nSTORAGE INTEGRITY (real file system)\n" + "=" * 70)


def t_air_corrupt():
    g, c, P = gateway(air="{not json")
    h = c.get("/health")
    st = scan(g, c, LINES)
    return (h.status_code == 200 and h.get_json()["air"]["ok"] is False and h.get_json()["air"]["error"] == "AIR_INVALID_FILE"
            and st["status"] == "failed" and st["reason_code"] == "AIR_INVALID_FILE" and st["result"] is None), \
        f"/health {h.status_code} air={ (h.get_json() or {}).get('air') if h.status_code == 200 else h.data[:60]}; /scan {st['status']}/{st.get('reason_code')}"


check("STORAGE", "S01-AIR-FILE-CORRUPT", "AIR 檔損毀（非 JSON）→ /health 回報 AIR_INVALID_FILE（不當機）；掃描失敗", t_air_corrupt)


def t_air_corrupt_cli():
    P = env(air="{not json")
    code, out = run_cli(P, LINES)
    return code == 2 and "AIR_INVALID_FILE" in out and not stage_printed(out), f"CLI exit {code}"


check("STORAGE", "S02-AIR-FILE-CORRUPT-CLI", "AIR 檔損毀 → CLI exit 2 AIR_INVALID_FILE", t_air_corrupt_cli, "CLI inference_30s.main()")


def t_history_corrupt():
    g, c, P = gateway()
    hp = g._history.path("TEST")
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_bytes(b'{"scan_id": "old-1", "result_kind": "TEST"}\n\x00\xff garbage not json\n')
    before = hp.read_bytes()
    st = scan(g, c, LINES)
    after = hp.read_bytes()
    recs = g._history.read("TEST")
    return (st["status"] == "done" and after.startswith(before) and len(recs) == 3 and recs[1] == {"_corrupt_line": 2}
            and recs[2]["scan_id"] == st["scan_id"]), f"existing bytes preserved={after.startswith(before)} records={[list(x)[:1] for x in recs]}"


check("STORAGE", "S03-HISTORY-CORRUPT-LINES", "歷史檔含損毀行：保留原內容、只追加新紀錄", t_history_corrupt)


def t_history_unwritable():
    g, c, P = gateway()
    hp = g._history.path("TEST")
    hp.mkdir(parents=True, exist_ok=True)           # 以資料夾佔用檔名 → 真實寫入失敗
    st = scan(g, c, LINES)
    return st["status"] == "failed" and st["reason_code"] == "HISTORY_WRITE_FAILED" and st["result"] is None, f"{st['status']}/{st['reason_code']}"


check("STORAGE", "S04-HISTORY-UNWRITABLE", "歷史檔無法寫入（真實檔案系統錯誤）→ 掃描失敗、不回傳結果", t_history_unwritable)


def t_upload_store_unwritable():
    g, c, P = gateway()
    st = scan(g, c, LINES)
    g._history.path("UPLOAD_TEST").mkdir(parents=True, exist_ok=True)
    r = c.post("/scan_records", json={"scan_id": st["scan_id"], "result_kind": "TEST"})
    return r.status_code == 500 and r.get_json()["error"] == "HISTORY_WRITE_FAILED", f"/scan_records {r.status_code}/{r.get_json()['error']}"


check("STORAGE", "S05-UPLOAD-STORE-UNWRITABLE", "上傳紀錄無法寫入 → 500 HISTORY_WRITE_FAILED（不回報成功）", t_upload_store_unwritable)


def t_separation_files():
    gE, cE, PE = gateway()
    stE = scan(gE, cE, LINES)
    files = sorted(p.name for p in gE._history.root.iterdir())
    lines_test = gE._history.read("TEST")
    return (files == ["history_test.jsonl"] and len(lines_test) == 1 and lines_test[0]["result_kind"] == "TEST"
            and not gE._history.path("FORMAL").exists()), f"files after one engineering scan: {files}"


check("STORAGE", "S06-FILE-SEPARATION", "工程掃描只產生 history_test.jsonl（沒有 history_formal.jsonl）", t_separation_files)


def t_failure_records():
    g, c, P = gateway()
    st = scan(g, c, bad("inf"))
    f = g._history.read("FAILED")
    return len(f) == 1 and f[0]["stage"] is None and f[0]["reason_code"] == "ADC_INVALID" and g._history.read("TEST") == [], f"failure record={f}"


check("STORAGE", "S07-FAILURE-RECORDS", "失敗掃描只寫入 scan_failures.jsonl（stage=null），不出現在結果歷史", t_failure_records)

print("=" * 70 + "\nGATEWAY API CONTRACT (HTTP status × error code)\n" + "=" * 70)


def contract(endpoint, condition, method, path, body, want_http, want_err, setup):
    g, c, P = setup()
    serial_reset(LINES)
    kw = {"json": body} if method == "POST" else {}
    addr = {"environ_base": {"REMOTE_ADDR": "192.168.0.50"}} if "non-local" in condition else {}
    r = (c.post if method == "POST" else c.get)(path, **kw, **addr)
    js = r.get_json(silent=True) or {}
    if js.get("scan_id") and r.status_code == 200 and path in ("/scan", "/calibrate"):
        done(g, c, js["scan_id"])                       # 等背景掃描結束再進行下一個測試
    got_err = js.get("error")
    ok = r.status_code == want_http and (want_err is None or got_err == want_err)
    CONTRACT.append({"layer": "Gateway HTTP", "endpoint": endpoint, "condition": condition, "expected_http": want_http, "expected_error": want_err,
                     "actual_http": r.status_code, "actual_error": got_err, "result_kind_field": js.get("result_kind"), "verdict": "PASS" if ok else "FAIL"})
    print(f"[{'PASS' if ok else 'FAIL'}] {method} {path} [{condition}] → {r.status_code}/{got_err}")


E = lambda: gateway()                                                                # noqa: E731
F0 = lambda: gateway(mode="formal", registry="shipped")                               # noqa: E731
NOCFG = lambda: (lambda gcp: ((gcp[2] / "pinenose_runtime.json").unlink(), gcp[0]._init_runtime(), gcp)[-1])(gateway())  # noqa: E731
NOAIR = lambda: gateway(air=None)                                                    # noqa: E731
for args in [
    ("/health", "engineering, ready", "GET", "/health", None, 200, None, E),
    ("/health", "no runtime config", "GET", "/health", None, 200, None, NOCFG),
    ("/scan", "engineering, ready", "POST", "/scan", {}, 200, None, E),
    ("/scan", "formal, empty approval list", "POST", "/scan", {}, 503, "MODEL_NOT_APPROVED", F0),
    ("/scan", "no runtime config", "POST", "/scan", {}, 503, "CONFIG_MISSING", NOCFG),
    ("/scan", "AIR missing", "POST", "/scan", {}, 400, "AIR_MISSING", NOAIR),
    ("/scan", "client declares other mode", "POST", "/scan", {"mode": "formal"}, 400, "MODE_MISMATCH", E),
    ("/scan", "engineering, non-local client", "POST", "/scan", {}, 403, "CLIENT_NOT_ALLOWED", E),
    ("/scan", "bad warmup_sec", "POST", "/scan", {"warmup_sec": "x"}, 400, "BAD_REQUEST", E),
    ("/calibrate", "engineering, ready", "POST", "/calibrate", {}, 200, None, E),
    ("/calibrate", "no runtime config", "POST", "/calibrate", {}, 503, "CONFIG_MISSING", NOCFG),
    ("/status", "missing scan_id", "GET", "/status", None, 400, "SCAN_ID_REQUIRED", E),
    ("/status", "unknown scan_id", "GET", "/status?scan_id=nope", None, 404, "SCAN_NOT_FOUND", E),
    ("/status", "engineering, non-local client", "GET", "/status?scan_id=nope", None, 403, "CLIENT_NOT_ALLOWED", E),
    ("/cancel", "missing scan_id", "POST", "/cancel", {}, 400, "BAD_REQUEST", E),
    ("/cancel", "unknown scan_id", "POST", "/cancel", {"scan_id": "nope"}, 404, "SCAN_NOT_FOUND", E),
    ("/scan_records", "uncommitted scan_id", "POST", "/scan_records", {"scan_id": "nope"}, 409, "SCAN_NOT_COMMITTED", E),
    ("/scan_records", "legacy payload without scan_id", "POST", "/scan_records", {"timestamp_iso": "x", "ripeness_pred": "ripe"}, 409, "SCAN_NOT_COMMITTED", E),
    ("/scan_records/<id>/feedback", "unknown id", "POST", "/scan_records/nope/feedback", {}, 404, "SCAN_NOT_COMMITTED", E),
]:
    try:
        contract(*args)
    except Exception as e:  # noqa: BLE001
        CONTRACT.append({"layer": "Gateway HTTP", "endpoint": args[0], "condition": args[1], "expected_http": args[5], "expected_error": args[6],
                         "actual_http": None, "actual_error": f"TEST ERROR {e!r}", "verdict": "FAIL"})
        print(f"[FAIL] {args[0]} [{args[1]}] TEST ERROR {e!r}")


# 有狀態的契約（需要先有掃描）
def stateful():
    g, c, P = gateway()
    serial_reset(LINES, gate_after=12)
    sid = c.post("/scan", json={}).get_json()["scan_id"]
    end = time.time() + 10
    while time.time() < end and not (FakeSerial.instances and FakeSerial.instances[0].calls > 12):
        time.sleep(0.005)
    rows = []
    r = c.post("/scan", json={})
    rows.append(("/scan", "device busy", 409, "DEVICE_BUSY", r))
    r = c.post("/calibrate", json={})
    rows.append(("/calibrate", "device busy", 409, "DEVICE_BUSY", r))
    r = c.get(f"/status?scan_id={sid}")
    rows.append(("/status", "own scan in progress", 200, None, r))
    r = c.post("/cancel", json={"scan_id": sid})
    rows.append(("/cancel", "active scan", 200, None, r))
    r = c.post("/cancel", json={"scan_id": sid})
    rows.append(("/cancel", "repeated cancel", 200, None, r))
    FakeSerial.gate.set()
    done(g, c, sid)
    serial_reset(LINES)
    sid2 = c.post("/scan", json={}).get_json()["scan_id"]
    done(g, c, sid2)
    r = c.post("/cancel", json={"scan_id": sid2})
    rows.append(("/cancel", "already finished", 409, "SCAN_ALREADY_FINISHED", r))
    r = c.post("/scan_records", json={"scan_id": sid2, "result_kind": "FORMAL"})
    rows.append(("/scan_records", "TEST scan declared FORMAL", 409, "RESULT_KIND_MISMATCH", r))
    r = c.post("/scan_records", json={"scan_id": sid2, "result_kind": "TEST"})
    rows.append(("/scan_records", "committed TEST scan", 200, None, r))
    r = c.post(f"/scan_records/{sid2}/feedback", json={"is_correct": True})
    rows.append(("/scan_records/<id>/feedback", "committed scan", 200, None, r))
    r = c.post("/scan_records", json={"scan_id": sid, "result_kind": "TEST"})
    rows.append(("/scan_records", "cancelled scan", 409, "SCAN_NOT_COMMITTED", r))
    for ep, cond, h, e, r in rows:
        js = r.get_json(silent=True) or {}
        ok = r.status_code == h and (e is None or js.get("error") == e)
        CONTRACT.append({"layer": "Gateway HTTP", "endpoint": ep, "condition": cond, "expected_http": h, "expected_error": e, "actual_http": r.status_code,
                         "actual_error": js.get("error"), "result_kind_field": js.get("result_kind"), "verdict": "PASS" if ok else "FAIL"})
        print(f"[{'PASS' if ok else 'FAIL'}] {ep} [{cond}] → {r.status_code}/{js.get('error')}")


stateful()

shutil.rmtree(TMP, ignore_errors=True)
pd.DataFrame(RESULTS).to_csv(HERE / "scan_lifecycle_results.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(STORAGE).to_csv(HERE / "_storage_python.csv", index=False, encoding="utf-8-sig")
(HERE / "_gateway_contract_rows.json").write_text(json.dumps(CONTRACT, ensure_ascii=False, default=str), encoding="utf-8")
n_fail = sum(r["verdict"] != "PASS" for r in RESULTS + STORAGE + CONTRACT)
print(f"\nlifecycle {sum(r['verdict'] == 'PASS' for r in RESULTS)}/{len(RESULTS)}, storage {sum(r['verdict'] == 'PASS' for r in STORAGE)}/{len(STORAGE)}, "
      f"contract {sum(r['verdict'] == 'PASS' for r in CONTRACT)}/{len(CONTRACT)}; network attempts={NET}")
sys.exit(1 if n_fail or NET else 0)
