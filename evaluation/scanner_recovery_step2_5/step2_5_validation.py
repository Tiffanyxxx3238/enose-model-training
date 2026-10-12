"""
Scanner Recovery Step 2.5 — 修正版網頁 CLI 的離線重播（C0～C3）與自動化測試（T1～T10）

- 只使用固定部署模型 pineapple_final/deploy_student.pkl（不訓練、不匯出）
- 序列埠、paramiko 皆以假模組取代；不連線、不登入 Pi、不啟動 server
- 舊密碼只在記憶體中取得其雜湊，用來檢查新檔案是否仍含相同字串；不印出、不寫入

Run:  python -u step2_5_validation.py > run_log.txt
"""
import ast
import hashlib
import importlib.util
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
SEM = HERE.parent.parent
ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=HERE).stdout.strip())
FINAL = SEM / "pineapple_final"
ORK = SEM / "enose_model_training/orkspace"
RAW = ORK / "data/raw"
BASE_REV = "799552c15529cba204442c4b1168947a61c14322"
TMP = HERE / "_tmp"
SEN = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B", 5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}
ANOM = {(3, 20260214), (4, 20260206)}            # Step 1+2 已知：鳳梨檔＝空氣檔
NEWLY_READABLE = {(11, 20260214), (13, 20260304)}  # 先前讀檔只掃前 10 列而被排除；表頭在第 349 列
NEW_ANOM = {(11, 20260214)}                        # 本輪新發現：鳳梨檔＝空氣檔（900 筆逐筆相同）
TOL = 1e-9
TESTS = []
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def test(tid, name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    TESTS.append((tid, name, status, detail))
    print(f"[{status}] {tid} {name} {detail}")


def section(t):
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


WORKTREES = [Path("c:/Users/user/electronic-nose-pineapple-ripeness-assessment"), Path("c:/Users/user/enose-gateway-fix"),
             Path("c:/Users/user/enose-fingerprint-study"), Path("c:/Users/user/enose-scanner-recovery"), ROOT]


def git_state(p):
    g = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, cwd=p).stdout.strip()  # noqa: E731
    return {"branch": g("branch", "--show-current"), "head": g("rev-parse", "HEAD"), "status": g("status", "--porcelain")}


GIT_BEFORE = {str(p): git_state(p) for p in WORKTREES if p.exists()}
MODEL_PATH = FINAL / "deploy_student.pkl"
MODEL_SHA_BEFORE = sha(MODEL_PATH)
PROTECTED = sorted(list(RAW.glob("*.xlsx")) + [ORK / "labeling.xlsx", ORK / "data_label_audit_report.xlsx",
                   FINAL / "deploy_student.pkl", FINAL / "feature_columns.json", FINAL / "deploy_meta.json"])
SNAP = {str(p): sha(p) for p in PROTECTED}
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir()

# ─────────────────────────────────────────
# 假模組（禁止任何實際連線）
# ─────────────────────────────────────────
serial_stub = types.ModuleType("serial")
serial_stub.Serial = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("serial disabled in validation"))
sys.modules["serial"] = serial_stub
CONNECT_CALLS = []


class FakeSSHClient:
    def set_missing_host_key_policy(self, *a):
        pass

    def connect(self, **kw):
        CONNECT_CALLS.append(kw)
        raise RuntimeError("network disabled in validation")

    def close(self):
        pass


paramiko_stub = types.ModuleType("paramiko")
paramiko_stub.SSHClient = FakeSSHClient
paramiko_stub.AutoAddPolicy = lambda: None
sys.modules["paramiko"] = paramiko_stub


def load_source(name, src, origin):
    spec = importlib.util.spec_from_loader(name, loader=None, origin=origin)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = origin
    exec(compile(src, origin, "exec"), mod.__dict__)
    return mod


def git_show(path):
    return subprocess.run(["git", "show", f"{BASE_REV}:{path}"], capture_output=True, cwd=ROOT).stdout.decode("utf-8")


ORIG = load_source("cli_orig", git_show("Semester 2 Final Exam (三下-期末)/pineapple_final/inference_30s.py"), f"git:{BASE_REV[:7]}:inference_30s.py")
NEW = load_source("cli_new", (FINAL / "inference_30s.py").read_text(encoding="utf-8"), str(FINAL / "inference_30s.py"))
CAL_NEW = load_source("cal_new", (FINAL / "calibrate_air_30s.py").read_text(encoding="utf-8"), str(FINAL / "calibrate_air_30s.py"))
CAL_ORIG = load_source("cal_orig", git_show("Semester 2 Final Exam (三下-期末)/pineapple_final/calibrate_air_30s.py"), "git:calibrate_air_30s.py")

# 訓練參考：notebook 原始函式
nb = json.load(open(ORK / "labeling_perfect_final.ipynb", encoding="utf-8"))
TRAIN = {"np": np, "pd": pd, "sp_stats": sp_stats, "SENSORS": SEN, "RAW_COLS": {s: f"{s}_raw" for s in SEN}, "pid_fallback_baseline": {}}
WANT = {"compute_features_one_day", "add_cross_ratio_features", "build_baseline_from_air_or_fallback", "head_n_valid"}
found = set()
for ci, cell in enumerate(nb["cells"]):
    if cell["cell_type"] != "code":
        continue
    src = "".join(cell["source"])
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANT and node.name not in found:
            exec(compile(ast.get_source_segment(src, node), f"notebook cell {ci}", "exec"), TRAIN)
            found.add(node.name)
assert found == WANT

MODEL = pickle.load(open(MODEL_PATH, "rb"))
FEATS = json.load(open(FINAL / "feature_columns.json", encoding="utf-8"))
META = json.load(open(FINAL / "deploy_meta.json", encoding="utf-8"))


def proba_of(vec):
    p = np.zeros(4)
    p[MODEL.classes_.astype(int)] = MODEL.predict_proba(np.asarray(vec, float).reshape(1, -1))[0]
    return p


# ─────────────────────────────────────────
# 資料
# ─────────────────────────────────────────
aud = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
aud = aud[(aud.has_raw_fruit == 1) & aud.stage.notna()]
DAYS = []
for r in aud.itertuples():
    try:
        fdf = NEW.load_xlsx_sensor_df(str(RAW / r.fruit_file))
    except ValueError:
        continue  # 沒有表頭的檔案（與前幾輪相同的 2 個）
    adf = NEW.load_xlsx_sensor_df(str(RAW / r.air_file))
    rows_all = [NEW.parse_sensor_row({f"{s}_raw": row.get(f"{s}_raw") for s in SEN}) for _, row in fdf.iterrows()]
    DAYS.append({"pid": int(r.pid), "date": int(r.date), "stage": int(r.stage), "group": OWNER[int(r.pid)],
                 "fruit_file": r.fruit_file, "air_file": r.air_file, "fdf": fdf, "adf": adf, "rows_all": rows_all})
print(f"天數 {len(DAYS)}；鳳梨 {len({d['pid'] for d in DAYS})}；Stage {pd.Series([d['stage'] for d in DAYS]).value_counts().sort_index().to_dict()}")


def air_for(d):
    a = TRAIN["build_baseline_from_air_or_fallback"](d["pid"], d["adf"].iloc[:30])
    return {s: float(a[s]) for s in SEN}


def orig_post(raw_pred, proba, feat):
    """原版 inference_30s.py main() 的判斷順序（第 657–690 行）。"""
    guard, _ = ORIG.air_or_no_sample_guard(feat, proba=proba)
    ep, early, _ = ORIG.early_stage_override(raw_pred, proba, feat)
    if early:
        final, over = ep, False
    else:
        final, over, _ = ORIG.overripe_override(raw_pred, proba, feat)
    return final, early, over, guard


# ═════════════════════════════════════════
# Phase C：C0～C3
# ═════════════════════════════════════════
section("Phase C｜C0～C3 controlled replay")
FP, PV = [], []
for d in DAYS:
    air = air_for(d)
    w0 = d["rows_all"][:30]
    assert all(r is not None for r in w0)
    f_ref = TRAIN["add_cross_ratio_features"](pd.DataFrame([TRAIN["compute_features_one_day"](TRAIN["head_n_valid"](d["fdf"], 30), air)])).iloc[0].to_dict()
    f_orig, _ = ORIG.build_features(w0, air)
    res2 = NEW.infer(w0, air, MODEL, FEATS, META, postprocess="raw")
    f_new = res2["features"]
    for i, f in enumerate(FEATS):
        ref = float(f_ref[f])
        for impl, val in (("C0_original_cli", float(f_orig.get(f, 0.0))), ("repaired_cli", float(f_new[f]))):
            ad = abs(val - ref)
            rd = ad / abs(ref) if abs(ref) > 1e-12 else 0.0
            FP.append({"pineapple_id": d["pid"], "date": d["date"], "is_anomaly": (d["pid"], d["date"]) in ANOM,
                       "in_step2_set": (d["pid"], d["date"]) not in NEWLY_READABLE, "feature": f,
                       "order_index": i, "implementation": impl, "training_reference": ref, "value": val,
                       "abs_diff": ad, "rel_diff": rd, "within_tolerance": ad <= TOL or rd <= TOL})
    # C0：原始特徵＋原始後處理
    P0 = proba_of([f_orig.get(f, 0.0) for f in FEATS])
    r0 = int(np.argmax(P0))
    fin0, e0, o0, g0 = orig_post(r0, P0, f_orig)
    # C1：只修特徵（原始後處理直接作用在修正後特徵上）
    P1 = proba_of([f_new[f] for f in FEATS])
    r1 = int(np.argmax(P1))
    fin1, e1, o1, g1 = orig_post(r1, P1, {**res2["features"], **res2["diagnostic_features"]})
    # C2：修正特徵＋不改判（修正版 CLI raw 模式）
    r2, fin2, P2 = res2["raw_pred"], res2["final_pred"], res2["proba"]
    # C3：修正特徵＋不改判＋三窗口（0/10/20）機率平均
    Ps = [NEW.infer(d["rows_all"][s:s + 30], air, MODEL, FEATS, META, postprocess="raw")["proba"] for s in (0, 10, 20)]
    P3 = np.mean(Ps, axis=0)
    r3 = int(np.argmax(P3))
    wins = [int(np.argmax(p)) for p in Ps]
    Pref = proba_of([f_ref[f] for f in FEATS])
    PV.append({"pineapple_id": d["pid"], "date": d["date"], "group": d["group"], "true_stage(reference only)": d["stage"],
               "is_anomaly": (d["pid"], d["date"]) in ANOM, "in_step2_set": (d["pid"], d["date"]) not in NEWLY_READABLE,
               "newly_found_anomaly": (d["pid"], d["date"]) in NEW_ANOM, "fruit_file": d["fruit_file"], "air_file": d["air_file"],
               **{f"air_{s}": air[s] for s in SEN},
               "C0_raw": r0, "C0_final": fin0, "C0_override": "early" if e0 else ("overripe" if o0 else ""), "C0_guard": g0,
               "C1_raw": r1, "C1_final": fin1, "C1_override": "early" if e1 else ("overripe" if o1 else ""), "C1_guard": g1,
               "C2_raw": r2, "C2_final": fin2, "C3_raw": r3, "C3_final": r3, "C3_window_stages": str(wins),
               "C3_windows_agree": len(set(wins)) == 1,
               "ref_raw": int(np.argmax(Pref)), "maxabs_prob_C2_vs_ref": float(np.max(np.abs(P2 - Pref))),
               **{f"C0_p{k}": P0[k] for k in range(4)}, **{f"C2_p{k}": P2[k] for k in range(4)}, **{f"C3_p{k}": P3[k] for k in range(4)},
               **{f"C2_f{i:02d}_{f}": f_new[f] for i, f in enumerate(FEATS)}})
fp = pd.DataFrame(FP)
fp.to_csv(HERE / "feature_parity.csv", index=False, encoding="utf-8-sig")
pv = pd.DataFrame(PV)
pv.to_csv(HERE / "prediction_variant_comparison.csv", index=False, encoding="utf-8-sig")

print("特徵一致性（不一致天數）：")
print("（Step 2 的 101 天）")
print(fp[fp.in_step2_set].pivot_table(index="feature", columns="implementation", values="within_tolerance", aggfunc=lambda v: int((~v).sum())).reindex(FEATS).to_string())
print("（另 2 天新讀到的資料）不一致特徵數：", fp[~fp.in_step2_set].groupby("implementation").within_tolerance.apply(lambda v: int((~v).sum())).to_dict())


def metrics(df, col):
    yt = df["true_stage(reference only)"].to_numpy()
    yp = df[col].to_numpy()
    cm = pd.crosstab(pd.Series(yt, name="true"), pd.Series(yp, name="pred")).reindex(index=range(4), columns=range(4), fill_value=0)
    rec = [round(float(cm.loc[k, k] / cm.loc[k].sum()), 3) if cm.loc[k].sum() else np.nan for k in range(4)]
    return {"accuracy(ref only)": round(float(np.mean(yt == yp)), 3), "recall_S0": rec[0], "recall_S1": rec[1], "recall_S2": rec[2],
            "recall_S3": rec[3], "pred_dist": json.dumps(pd.Series(yp).value_counts().reindex(range(4), fill_value=0).tolist())}, cm


summary, cms = [], {}
for scope, df_ in (("101 days (Step 2 set)", pv[pv.in_step2_set]), ("99 days (Step 2 set minus 2 known anomalies)", pv[pv.in_step2_set & ~pv.is_anomaly]),
                    ("103 days (incl. 2 newly readable)", pv)):
    for v in ("C0", "C1", "C2", "C3"):
        m, cm = metrics(df_, f"{v}_final")
        mr, _ = metrics(df_, f"{v}_raw")
        summary.append({"scope": scope, "variant": v, "raw_pred_dist": mr["pred_dist"], "final_pred_dist": m["pred_dist"],
                        "override_count": int((df_[f"{v}_final"] != df_[f"{v}_raw"]).sum()), **{k: m[k] for k in m if k != "pred_dist"}})
        cms[(scope, v)] = cm
summ = pd.DataFrame(summary)
print("\n", summ.to_string(index=False))

# 歸因：C0→C1（特徵）、C1→C2（移除改判）、C2→C3（窗口策略）
attr = []
for scope, df_ in (("101 days (Step 2 set)", pv[pv.in_step2_set]), ("99 days (Step 2 set minus 2 known anomalies)", pv[pv.in_step2_set & ~pv.is_anomaly]),
                    ("103 days (incl. 2 newly readable)", pv)):
    for a, b, what in (("C0", "C1", "feature fix"), ("C1", "C2", "remove heuristic override"), ("C2", "C3", "3-window averaging")):
        for kind in ("raw", "final"):
            ca, cb = df_[f"{a}_{kind}"], df_[f"{b}_{kind}"]
            ch = df_[ca != cb]
            mat = pd.crosstab(ca, cb).reindex(index=range(4), columns=range(4), fill_value=0)
            attr.append({"scope": scope, "transition": f"{a}->{b}", "change": what, "level": kind, "n_changed": len(ch),
                         "flip_matrix(rows=from,cols=to)": json.dumps(mat.values.tolist()),
                         "changed_by_group": json.dumps(ch.group.value_counts().sort_index().to_dict()),
                         "changed_days": "; ".join(f"{p}/{dt}:{x}->{y}" for p, dt, x, y in zip(ch.pineapple_id, ch.date, ch[f"{a}_{kind}"], ch[f"{b}_{kind}"]))})
attrdf = pd.DataFrame(attr)
attrdf.to_csv(HERE / "class_flip_attribution.csv", index=False, encoding="utf-8-sig")
print("\n", attrdf[["scope", "transition", "level", "n_changed", "flip_matrix(rows=from,cols=to)", "changed_by_group"]].to_string(index=False))
with open(HERE / "confusion_matrices.json", "w", encoding="utf-8") as f:
    json.dump({f"{s}|{v}": cm.values.tolist() for (s, v), cm in cms.items()}, f, ensure_ascii=False, indent=1)
summ.to_csv(HERE / "variant_metrics.csv", index=False, encoding="utf-8-sig")

# ═════════════════════════════════════════
# 測試 T1～T10
# ═════════════════════════════════════════
section("Tests T1–T10")
new_fp = fp[fp.implementation == "repaired_cli"]
test("T1", "Feature parity：修正版 CLI 的 11 特徵＝訓練參考（103 天，含 Step 2 的 101 天）", bool(new_fp.within_tolerance.all()),
     f"(max abs diff {new_fp.abs_diff.max():.2e})")
test("T2", "Probability parity：同模型、同 ADC、同 AIR、同窗口的四類機率＝訓練參考", float(pv.maxabs_prob_C2_vs_ref.max()) <= 1e-12,
     f"(max {pv.maxabs_prob_C2_vs_ref.max():.2e})")

# T3 決定性：模組層級 ＋ 真正 CLI subprocess
stub_dir = TMP / "stub"
stub_dir.mkdir()
(stub_dir / "serial.py").write_text("def Serial(*a, **k):\n    raise RuntimeError('serial disabled in validation')\n", encoding="utf-8")
demo = TMP / "demo_data"
demo.mkdir()
STZ = {0: "未熟", 1: "初熟", 2: "成熟", 3: "過熟"}
qa = [d for d in DAYS if (d["pid"], d["date"]) in ANOM | {(12, 20260309), (13, 20260307), (5, 20260203)}]
ENV = {**os.environ, "PYTHONPATH": str(stub_dir), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


def run_cli(args, cwd=TMP):
    return subprocess.run([sys.executable, str(FINAL / "inference_30s.py"), *args, "--model", str(MODEL_PATH),
                           "--features", str(FINAL / "feature_columns.json"), "--meta", str(FINAL / "deploy_meta.json")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, env=ENV)


det_rows, cli_match = [], []
for d in qa:
    case = f"pineapple_{d['pid']:02d}_{d['date']}"
    shutil.copy(RAW / d["fruit_file"], demo / f"{case}_{STZ[d['stage']]}.xlsx")
    airj = TMP / f"{case}_air.json"
    a = air_for(d)
    json.dump({**a, "_meta": {"source": "demo", "calibration_id": "test", "created_at": "2026-01-01T00:00:00+00:00"}}, open(airj, "w"))
    sigs = set()
    for rep in range(5):
        r = NEW.infer(d["rows_all"][:30], a, MODEL, FEATS, META, postprocess="raw")
        sigs.add(hashlib.sha256(json.dumps([r["features"], [float(x) for x in r["proba"]], r["raw_pred"], r["final_pred"]]).encode()).hexdigest())
    trace = TMP / f"{case}_trace.json"
    outs = set()
    for rep in range(5):
        o = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", case, "--demo-stage", STZ[d["stage"]], "--air", str(airj),
                     "--trace-json", str(trace)])
        t = json.load(open(trace, encoding="utf-8"))
        outs.add(hashlib.sha256(json.dumps([t["features"], t["proba"], t["raw_pred"], t["final_pred"]]).encode()).hexdigest())
    row = pv[(pv.pineapple_id == d["pid"]) & (pv.date == d["date"])].iloc[0]
    det_rows.append({"case": case, "module_distinct": len(sigs), "cli_distinct": len(outs), "returncode": o.returncode})
    cli_match.append({"case": case, "cli_raw": t["raw_pred"], "replay_C2_raw": int(row.C2_raw), "cli_final": t["final_pred"],
                      "replay_C2_final": int(row.C2_final),
                      "trace_has_chain": all(k in t for k in ("rows", "air", "air_provenance", "features", "proba", "raw_pred", "displayed_pred"))})
det = pd.DataFrame(det_rows)
cm_df = pd.DataFrame(cli_match)
print(det.to_string(index=False))
print(cm_df.to_string(index=False))
test("T3", "Deterministic replay：同輸入重跑 5 次（模組與真實 CLI）", bool((det.module_distinct == 1).all() and (det.cli_distinct == 1).all()
                                                                     and (det.returncode == 0).all()))

# T4 缺少 AIR
case = f"pineapple_{qa[0]['pid']:02d}_{qa[0]['date']}"
o_missing = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", case, "--demo-stage", STZ[qa[0]["stage"]], "--air", str(TMP / "nope.json")])
o_default_missing = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", case, "--demo-stage", STZ[qa[0]["stage"]]])
bad_air = TMP / "bad_air.json"
json.dump({"MQ2": 100, "MQ3": 1.0, "MQ9": 100, "MQ135": 100}, open(bad_air, "w"))
o_bad = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", case, "--demo-stage", STZ[qa[0]["stage"]], "--air", str(bad_air)])
live_demo_air = run_cli(["--air", str(TMP / f"{case}_air.json")])  # 實測模式（沒有 demo 參數）＋ demo 來源 baseline
cal_err = None
try:
    CAL_NEW.compute_baseline_from_rows([{"MQ2_raw": 100.0, "MQ3_raw": 100.0, "MQ9_raw": 100.0, "MQ135_raw": 100.0}])
except CAL_NEW.AirCalibrationError as e:
    cal_err = str(e)
orig_cal = CAL_ORIG.compute_baseline_from_rows([{"MQ2_raw": 100.0, "MQ3_raw": 100.0, "MQ9_raw": 100.0, "MQ135_raw": 100.0}])
ok4 = (o_missing.returncode == 2 and "找不到 AIR baseline" in o_missing.stdout and o_default_missing.returncode == 2
       and "air_base_demo.json" in o_default_missing.stdout and o_bad.returncode == 2 and "TGS2602 缺少 baseline" in o_bad.stdout
       and live_demo_air.returncode == 2 and "demo 空氣校正" in live_demo_air.stdout and "TGS2602" in (cal_err or ""))
test("T4", "Missing／invalid AIR：不以假 baseline 推論", ok4,
     f"(缺檔 rc={o_missing.returncode}；demo 預設檔不存在 rc={o_default_missing.returncode}；缺感測器/超範圍 rc={o_bad.returncode}；"
     f"實測用 demo baseline rc={live_demo_air.returncode}；校正缺值→錯誤；原版校正缺值時 TGS2602={orig_cal.get('TGS2602')}）")

# T5 無效輸入
good = qa[2]["rows_all"][:30]
air5 = air_for(qa[2])
cases5 = {}
cases5["parse_nan"] = NEW.parse_sensor_row({"MQ2_raw": "nan", "MQ3_raw": 1, "MQ9_raw": 1, "MQ135_raw": 1, "TGS2602_raw": 1}) is None
cases5["parse_inf"] = NEW.parse_sensor_row({"MQ2_raw": float("inf"), "MQ3_raw": 1, "MQ9_raw": 1, "MQ135_raw": 1, "TGS2602_raw": 1}) is None
cases5["parse_missing_sensor"] = NEW.parse_sensor_row({"MQ2_raw": 1, "MQ3_raw": 1, "MQ9_raw": 1, "MQ135_raw": 1}) is None
cases5["parse_adc_out_of_range"] = NEW.parse_sensor_row({"MQ2_raw": 1500, "MQ3_raw": 1, "MQ9_raw": 1, "MQ135_raw": 1, "TGS2602_raw": 1}) is None
cases5["parse_non_numeric"] = NEW.parse_sensor_row({"MQ2_raw": "abc", "MQ3_raw": 1, "MQ9_raw": 1, "MQ135_raw": 1, "TGS2602_raw": 1}) is None


def raises(fn):
    try:
        fn()
        return False
    except NEW.InputValidationError:
        return True


cases5["invalid_length_29"] = raises(lambda: NEW.infer(good[:29], air5, MODEL, FEATS, META))
cases5["invalid_length_31"] = raises(lambda: NEW.infer(good + good[:1], air5, MODEL, FEATS, META))
cases5["zero_baseline"] = raises(lambda: NEW.infer(good, {**air5, "MQ3": 0.0}, MODEL, FEATS, META))
cases5["nan_baseline"] = raises(lambda: NEW.infer(good, {**air5, "MQ9": float("nan")}, MODEL, FEATS, META))
cases5["missing_model_feature"] = raises(lambda: NEW.infer(good, air5, MODEL, FEATS + ["day_index"], META))
bad_rows = [dict(r) for r in good]
bad_rows[5]["MQ3"] = float("inf")
cases5["inf_in_rows_feature"] = raises(lambda: NEW.infer(bad_rows, air5, MODEL, FEATS, META))
nan_df = qa[2]["fdf"].copy()
nan_df.loc[3, "MQ2_raw"] = np.nan
nan_case = "pineapple_99_20990101"
nan_df_path = demo / f"{nan_case}_未熟.xlsx"
with pd.ExcelWriter(nan_df_path) as w:
    pd.DataFrame([["timestamp_ms"] + list(nan_df.columns[1:])]).to_excel(w, header=False, index=False, startrow=0)
    nan_df.to_excel(w, header=False, index=False, startrow=1)
o_nan = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", nan_case, "--demo-stage", "未熟", "--air", str(TMP / f"{case}_air.json")])
cases5["cli_demo_window_with_nan_row"] = o_nan.returncode == 2 and "無效" in o_nan.stdout
print(cases5)
test("T5", "Invalid inputs 有明確行為（拒絕或報錯）", all(cases5.values()), f"({sum(cases5.values())}/{len(cases5)})")

# T6 正式模式不改判
raw_default = NEW.POSTPROCESS_DEFAULT == "raw"
no_override = bool((pv.C2_final == pv.C2_raw).all())
would_override = int((pv.C1_final != pv.C1_raw).sum())
o_qa = run_cli(["--demo", "--demo-dir", str(demo), "--demo-case", f"pineapple_{qa[2]['pid']:02d}_{qa[2]['date']}",
                "--demo-stage", STZ[qa[2]["stage"]], "--air", str(TMP / f"pineapple_{qa[2]['pid']:02d}_{qa[2]['date']}_air.json")])
test("T6", "No silent override：預設 raw 模式不改判", raw_default and no_override and "Postprocess mode: raw" in o_qa.stdout,
     f"(C2 改判 0 次；舊規則若套用會改判 {would_override} 次，只輸出為診斷)")

# T7 模型完整性
test("T7", "Model integrity：部署 .pkl SHA-256 前後一致", sha(MODEL_PATH) == MODEL_SHA_BEFORE == "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1",
     f"({MODEL_SHA_BEFORE})")

# T9 憑證（在 T8 之前，因為 T8 要比對最終狀態）
old_src_lines = []
for rel in ("Semester 2 Final Exam (三下-期末)/pineapple_final/app_local.py",
            "Semester 2 Final Exam (三下-期末)/pineapple_deployment_system/app_local.py",
            "3rd Grade - Semester 2(三下-期中)/pineapple_deployment_system/app_local.py"):
    old_src_lines += git_show(rel).splitlines()
secret_vals = {m.group(1) for ln in old_src_lines for m in [re.match(r"^RPI_PASSWORD\s*=\s*['\"]([^'\"]+)['\"]", ln)] if m}
secret_hashes = {hashlib.sha256(v.encode()).hexdigest() for v in secret_vals}
leaks = []
scan_files = [p for p in list(SEM.rglob("*.py")) + list(HERE.glob("*")) + list((ROOT / "3rd Grade - Semester 2(三下-期中)").rglob("*.py"))
              if p.is_file() and "_tmp" not in str(p)]
for p in scan_files:
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    if any(v in txt for v in secret_vals):
        leaks.append(str(p.relative_to(ROOT)))
del secret_vals
app_results = {}
for rel in ("Semester 2 Final Exam (三下-期末)/pineapple_final/app_local.py",
            "Semester 2 Final Exam (三下-期末)/pineapple_deployment_system/app_local.py",
            "3rd Grade - Semester 2(三下-期中)/pineapple_deployment_system/app_local.py"):
    path = ROOT / rel
    for k in ("PINENOSE_RPI_KEY_FILE", "PINENOSE_RPI_PASSWORD"):
        os.environ.pop(k, None)
    mod = load_source(f"app_{len(app_results)}", path.read_text(encoding="utf-8"), str(path))
    try:
        mod._ssh_auth_kwargs()
        no_env = "no error"
    except RuntimeError as e:
        no_env = "RuntimeError" if "未設定 SSH 憑證" in str(e) else str(e)
    os.environ["PINENOSE_RPI_PASSWORD"] = "fake-test-password"
    pw = mod._ssh_auth_kwargs()
    os.environ["PINENOSE_RPI_KEY_FILE"] = str(TMP / "fake_key")
    key = mod._ssh_auth_kwargs()
    CONNECT_CALLS.clear()
    fn = getattr(mod, "run_remote_command", None) or getattr(mod, "run_remote_script")
    out = fn("echo test") if fn.__name__ == "run_remote_command" else fn("x.py")
    for k in ("PINENOSE_RPI_KEY_FILE", "PINENOSE_RPI_PASSWORD"):
        os.environ.pop(k, None)
    app_results[rel] = {"no_env": no_env, "password_env": pw == {"password": "fake-test-password"},
                        "key_env": key == {"key_filename": str(TMP / "fake_key")},
                        "connect_used_fake": bool(CONNECT_CALLS) and CONNECT_CALLS[0].get("key_filename") == str(TMP / "fake_key")
                        and "password" not in CONNECT_CALLS[0],
                        "has_RPI_PASSWORD_attr": hasattr(mod, "RPI_PASSWORD")}
print(json.dumps(app_results, ensure_ascii=False, indent=1))
ok9 = (not leaks) and len(secret_hashes) == 1 and all(v["no_env"] == "RuntimeError" and v["password_env"] and v["key_env"]
                                                       and v["connect_used_fake"] and not v["has_RPI_PASSWORD_attr"] for v in app_results.values())
test("T9", "Credential hygiene：修正版程式與新輸出不含舊密碼；缺少環境憑證時報錯；只用假憑證測試", ok9,
     f"(掃描 {len(scan_files)} 檔，含舊密碼的檔案 {len(leaks)}；3 個 app_local 皆通過)")

# T10 追溯
trace_ok = bool(cm_df.trace_has_chain.all()) and bool((cm_df.cli_raw == cm_df.replay_C2_raw).all()) and bool((cm_df.cli_final == cm_df.replay_C2_final).all())
test("T10", "Replay traceability：raw input → AIR → features → probabilities → raw → displayed", trace_ok,
     "(CLI --trace-json 含完整鏈；CLI 實跑＝重播 C2)")

# T8 最後檢查（其他工作區、受保護檔案）
shutil.rmtree(TMP)
GIT_AFTER = {str(p): git_state(p) for p in WORKTREES if p.exists()}
others_ok = all(GIT_BEFORE[k] == GIT_AFTER[k] for k in GIT_BEFORE if Path(k) != ROOT)
changed = [p for p in SNAP if sha(p) != SNAP[p]]
test("T8", "No deployment changes：main 與其他工作區未變、受保護檔案未變、未連線", others_ok and not changed and not CONNECT_CALLS[1:],
     f"(其他 {len(GIT_BEFORE) - 1} 個工作區 git 狀態不變；受保護檔案 {len(SNAP)} 個未變；假 SSH 連線紀錄只來自 T9 測試)")

with open(HERE / "test_results.txt", "w", encoding="utf-8") as f:
    for tid, name, status, detail in sorted(TESTS, key=lambda x: int(x[0][1:])):
        f.write(f"[{status}] {tid} {name} {detail}\n")
with open(HERE / "model_integrity_check.txt", "w", encoding="utf-8") as f:
    f.write(f"model: {MODEL_PATH.relative_to(ROOT)}\nsha256 before: {MODEL_SHA_BEFORE}\nsha256 after : {sha(MODEL_PATH)}\n"
            f"expected (Step 1+2): a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1\n"
            f"feature_columns.json sha256: {sha(FINAL / 'feature_columns.json')}\ndeploy_meta.json sha256: {sha(FINAL / 'deploy_meta.json')}\n"
            f"classes_: {list(map(int, MODEL.classes_))}\nn_features_in_: {MODEL.n_features_in_}\nfeature order: {FEATS}\n"
            "Raspberry Pi model: NOT VERIFIED\n")
with open(HERE / "git_safety_check.txt", "w", encoding="utf-8") as f:
    for k in GIT_BEFORE:
        f.write(f"{k}\n  before: {GIT_BEFORE[k]}\n  after : {GIT_AFTER[k]}\n")
print("\n測試統計：", pd.Series([t[2] for t in TESTS]).value_counts().to_dict())
