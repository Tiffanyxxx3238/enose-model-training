"""
Step 5 受控本機後端（測試用）：以「真實修改後的 Gateway v2」在 127.0.0.1 提供 HTTP 服務，序列埠為假序列埠。

- Gateway 程式、安全層、模型、特徵檔都從本 worktree 複製到暫存資料夾後載入（不修改原檔）。
- 另開一個測試控制埠（只綁 127.0.0.1）讓 Node 端 App 測試切換情境：模式、核准清單、AIR、假序列埠資料、閘門、時鐘。
- 控制埠另有 /bad/* 路由，模擬「後端回傳無效資料／不回應」以測試 App 的錯誤處理。
- 只綁 loopback；不連接任何設備或外部網路。

用法：python backend_harness.py --port 5810 --ctl-port 5811 --workdir <temp dir>
"""
import argparse
import importlib.util
import io
import contextlib
import json
import os
import shutil
import sys
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
FINAL = WT / "pineapple_final"
GWD = WT / "pineapple_app_gateway"
RAW = WT / "enose_model_training/orkspace/data/raw"
SENS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
HEADER = ["timestamp_ms", "timestamp_s", "MQ2_raw", "MQ3_raw", "MQ9_raw", "MQ135_raw", "TGS2602_raw", "Temp_C", "Humidity_pct", "Pressure_hPa"]
DEPLOY_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
# 測試專用 AIR 期限（工程測試設定，不是正式建議值；沒有科學驗證）
TEST_ONLY_AIR_MAX_AGE_SEC = 3600


# ── 假序列埠 ──
class FakeSerialState:
    lines, header, gate_after, hang_after, raise_on_open = [], True, None, None, None
    gate = threading.Event()
    instances = []


class FakeSerial:
    def __init__(self, port, baud, timeout=1):
        if FakeSerialState.raise_on_open:
            raise FakeSerialState.raise_on_open
        self.buf = ([",".join(HEADER)] if FakeSerialState.header else []) + list(FakeSerialState.lines)
        self.calls, self.closed = 0, threading.Event()
        FakeSerialState.instances.append(self)

    def readline(self):
        self.calls += 1
        if self.closed.is_set():
            raise serial_stub.SerialException("port closed")
        if FakeSerialState.hang_after is not None and self.calls > FakeSerialState.hang_after:
            self.closed.wait(60)
            raise serial_stub.SerialException("read aborted by close()")
        if FakeSerialState.gate_after is not None and self.calls > FakeSerialState.gate_after:
            while not FakeSerialState.gate.is_set():
                if self.closed.wait(0.005):
                    raise serial_stub.SerialException("read aborted by close()")
        return (self.buf.pop(0) + "\n").encode() if self.buf else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed.set()


serial_stub = types.ModuleType("serial")
serial_stub.Serial = FakeSerial
serial_stub.SerialException = type("SerialException", (OSError,), {})
sys.modules["serial"] = serial_stub


class FakeTime:
    def __init__(self, step=0.3):
        self.t, self.step, self._l = 1_000_000.0, step, threading.Lock()

    def time(self):
        with self._l:
            self.t += self.step
            return self.t

    def sleep(self, s):
        pass

    def __getattr__(self, k):
        return getattr(time, k)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ── 歷史資料（R1 修正讀檔） ──
sys.path.insert(0, str(EVAL / "r1_controlled_retraining"))
from repaired_parser import read_raw_xlsx_fixed  # noqa: E402

pb = pd.read_csv(EVAL / "r1_controlled_retraining/pipeline_b_corrected_training.csv", encoding="utf-8-sig")
pb = pb[pb["in_S99"]].reset_index(drop=True)
_DAY_CACHE = {}


def day(i):
    if i not in _DAY_CACHE:
        r = pb.iloc[i]
        fdf = read_raw_xlsx_fixed(str(RAW / r.fruit_file))
        fdf = fdf[fdf[[f"{s}_raw" for s in SENS]].notna().all(axis=1)].reset_index(drop=True).iloc[:50]
        lines = [",".join("" if pd.isna(row.get(c)) else str(row.get(c)) for c in HEADER) for _, row in fdf.iterrows()]
        _DAY_CACHE[i] = {"lines": lines, "air": {s: float(r[f"air_A0_{s}"]) for s in SENS}}
    return _DAY_CACHE[i]


def air_lines(d, n=60):
    return [",".join([str(1000 * i), str(i), *[f"{d['air'][s] + (i % 3 - 1) * 0.5:.2f}" for s in SENS], "25.0", "60.0", "1013.0"]) for i in range(n)]


def blank_env(lines):
    return [",".join(x.split(",")[:7] + ["", "", ""]) for x in lines]


# ── 暫存環境＋Gateway ──
class Backend:
    def __init__(self, workdir):
        self.W = Path(workdir)
        self.lock = threading.Lock()
        self.g = None
        self.clock = Clock()

    def build(self, mode="formal", registry="shipped", air="none", device_id=None):
        if self.W.exists():
            shutil.rmtree(self.W)
        (self.W / "pineapple_app_gateway").mkdir(parents=True)
        P = self.W / "pineapple_final"
        P.mkdir(parents=True)
        shutil.copy(GWD / "app_gateway_v2.py", self.W / "pineapple_app_gateway/app_gateway_v2.py")
        for f in ("pinenose_safety.py", "feature_columns.json", "deploy_meta.json", "deploy_student.pkl", "model_registry.json"):
            shutil.copy(FINAL / f, P / f)
        feats = json.loads((P / "feature_columns.json").read_text(encoding="utf-8"))
        if registry == "engineering":
            (P / "model_registry.json").write_text(json.dumps({"_note": "TEST FIXTURE ONLY — engineering replay, not an approval",
                                                               "models": {DEPLOY_SHA: {"status": "engineering", "feature_columns": feats}}}), encoding="utf-8")
        cfg = {"_note": "TEST-ONLY configuration (air_max_age_sec is a test value, not a production recommendation)",
               "mode": mode, "device_id": device_id, "model_registry": "model_registry.json"}
        if mode == "formal":
            cfg["formal"] = {"air_max_age_sec": TEST_ONLY_AIR_MAX_AGE_SEC}
        else:
            cfg["engineering"] = {"air_max_age_sec": TEST_ONLY_AIR_MAX_AGE_SEC, "allowed_client_hosts": ["127.0.0.1"], "allow_demo_air": False}
        (P / "pinenose_runtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        if air != "none":
            m = "formal" if air == "formal_live" else "engineering"
            a = {**day(0)["air"], "_meta": {"source": "live", "calibration_id": "fixture" + "0" * 25, "created_at": datetime.now(timezone.utc).isoformat(),
                                            "mode": m, "device_id": device_id, "sample_count": 30,
                                            "test_fixture_note": "historical AIR replayed offline — NOT a real measurement"}}
            (P / ("air_base.json" if m == "formal" else "air_base_test.json")).write_text(json.dumps(a), encoding="utf-8")
        sys.modules.pop("pinenose_safety", None)
        spec = importlib.util.spec_from_file_location(f"gw_{time.time_ns()}", str(self.W / "pineapple_app_gateway/app_gateway_v2.py"))
        g = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(g)
        g.time = FakeTime()
        os.environ["ARDUINO_PORT"] = "FAKE0"
        with contextlib.redirect_stdout(io.StringIO()):
            g._init_runtime()
        self.clock = Clock()
        g._registry = g.safety.ScanRegistry(g._history, clock=self.clock)
        self.g = g
        set_serial({"lines": "day:0"})
        return {"mode": mode, "registry": registry, "air": air, "model_loaded": g._handle is not None,
                "error": None if g._model_error is None else g._model_error.code}


def set_serial(spec):
    src = spec.get("lines", "day:0")
    kind, _, arg = src.partition(":")
    if kind == "day":
        lines = list(day(int(arg))["lines"])
    elif kind == "air":
        lines = air_lines(day(int(arg)))
    elif kind == "none":
        lines = []
    else:
        raise ValueError(src)
    n = spec.get("n_lines")
    if n is not None:
        lines = lines[:n]
    if spec.get("blank_env"):
        lines = blank_env(lines)
    bad = spec.get("bad")
    if bad:
        v = lines[5].split(",")
        v[{"nan": 3, "inf": 3, "range": 4, "missing": 6}[bad]] = {"nan": "nan", "inf": "inf", "range": "1500", "missing": ""}[bad]
        lines[5] = ",".join(v)
    FakeSerialState.lines = lines
    FakeSerialState.header = spec.get("header", True)
    FakeSerialState.gate_after = spec.get("gate_after")
    FakeSerialState.hang_after = spec.get("hang_after")
    FakeSerialState.gate = threading.Event()
    FakeSerialState.instances = []


def control_app(B):
    from flask import Flask, jsonify, request
    app = Flask("ctl")

    @app.post("/__ctl/reset")
    def reset():
        return jsonify(B.build(**(request.get_json() or {})))

    @app.post("/__ctl/serial")
    def serial_():
        set_serial(request.get_json() or {})
        return jsonify({"ok": True, "n_lines": len(FakeSerialState.lines)})

    @app.post("/__ctl/gate")
    def gate():
        FakeSerialState.gate.set()
        return jsonify({"ok": True})

    @app.get("/__ctl/serial_state")
    def serial_state():
        return jsonify({"instances": len(FakeSerialState.instances), "calls": [s.calls for s in FakeSerialState.instances],
                        "closed": [s.closed.is_set() for s in FakeSerialState.instances]})

    @app.post("/__ctl/clock")
    def clock():
        B.clock.t += float((request.get_json() or {}).get("advance", 0))
        return jsonify({"t": B.clock.t})

    @app.get("/__ctl/history")
    def history():
        return jsonify(B.g._history.read(request.args["kind"]))

    @app.get("/__ctl/scan")
    def scan_state():
        s = B.g._registry.scans.get(request.args["scan_id"])
        return jsonify(None if s is None else {"status": s["status"], "released": s["released"]})

    # ── 無效後端（App 錯誤處理測試）──
    @app.route("/bad/<variant>/<path:rest>", methods=["GET", "POST"])
    def bad(variant, rest):
        if variant == "noid":
            return jsonify({"ok": True})                       # 缺 scan_id
        if variant == "html":
            return "<html>proxy error</html>", 200, {"Content-Type": "text/html"}
        if variant == "slow":
            time.sleep(15)
            return jsonify({"ok": True})
        if variant == "wrongid":                              # /status 回傳別的 scan_id
            return jsonify({"scan_id": "someone-else", "status": "done", "result": {"scan_id": "someone-else"}, "result_kind": "TEST",
                            "ok": True, "mode": "engineering"})
        if variant == "fakedone":                             # 結果欄位不完整
            sid = request.args.get("scan_id", "x")
            if rest == "scan":
                return jsonify({"ok": True, "scan_id": "fake-1", "result_kind": "TEST", "mode": "engineering"})
            return jsonify({"scan_id": "fake-1", "status": "done", "result_kind": "TEST", "mode": "engineering",
                            "result": {"scan_id": "fake-1", "result_kind": "TEST", "measurement_valid": True, "ripeness": "ripe",
                                       "probabilities": {"stage0": 0.1, "stage1": 0.1}}})
        return jsonify({"error": "unknown variant"}), 404
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--ctl-port", type=int, required=True)
    ap.add_argument("--workdir", required=True)
    a = ap.parse_args()
    from werkzeug.serving import make_server
    B = Backend(a.workdir)
    B.build()

    class Proxy:
        """Gateway 會因 reset 而重新載入；HTTP 伺服器透過這個代理永遠轉給最新的 Gateway app。"""

        def __call__(self, environ, start_response):
            return B.g.app(environ, start_response)
    gw_srv = make_server("127.0.0.1", a.port, Proxy(), threaded=True)
    ctl_srv = make_server("127.0.0.1", a.ctl_port, control_app(B), threaded=True)
    threading.Thread(target=ctl_srv.serve_forever, daemon=True).start()
    print(f"READY gateway=127.0.0.1:{a.port} ctl=127.0.0.1:{a.ctl_port}", flush=True)
    try:
        gw_srv.serve_forever()
    finally:
        shutil.rmtree(a.workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
