"""
Step 3 — AIR Calibration Sensitivity Audit（離線 counterfactual 分析）

規格：evaluation_protocol.md（commit 422fda2，先於結果）。
條件（相對 B0 = Fruit F0 + 同日 AIR A0）：
  同日 AIR：A0+10、A0+20、A1(300–329)、A2(870–899)
  相鄰日期 AIR（stress test）：PREV、NEXT
  Fruit 窗口（AIR A0 固定）：F1(10–39)、F2(20–49)
E1 固定部署模型；E2 嚴格 LOGO（同折同模型，訓練定義不變）。
不寫出模型檔、不連接任何設備。

Run（在 evaluation/ 目錄）：python -u air_sensitivity_audit/air_sensitivity_audit.py
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
WT = EVAL.parent
ROOT = WT.parent
sys.path.insert(0, str(EVAL))
os.chdir(EVAL)
sys.stdout.reconfigure(encoding="utf-8")


class Tee:
    def __init__(self, *s):
        self.s = s

    def write(self, x):
        for s in self.s:
            s.write(x)

    def flush(self):
        for s in self.s:
            s.flush()


LOG = open(HERE / "run_log.txt", "w", encoding="utf-8")
sys.stdout = Tee(sys.__stdout__, LOG)
T0 = time.time()
pd.set_option("display.width", 260)


def section(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


OTHER_WT = [Path("c:/Users/user/electronic-nose-pineapple-ripeness-assessment"), Path("c:/Users/user/enose-gateway-fix"),
            Path("c:/Users/user/enose-fingerprint-study"), Path("c:/Users/user/enose-scanner-recovery"),
            Path("c:/Users/user/enose-scanner-recovery-step2-5"), Path("c:/Users/user/enose-scanner-accuracy-validation"),
            Path("c:/Users/user/enose-single-scan-audit")]


def git_state(p):
    g = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True).stdout.decode("utf-8", "replace").strip()  # noqa: E731
    return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "head": g("rev-parse", "HEAD"), "status": g("status", "--porcelain")}


MODEL_PATH = WT / "pineapple_final/deploy_student.pkl"
EXPECTED_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
STATE_BEFORE = {str(p): git_state(p) for p in OTHER_WT}
PKL_BEFORE = sha_file(MODEL_PATH)

section("載入既有流程（Round 2／Step 2.6／2.7）")
import retrain_round2 as r2  # noqa: E402
from eval_common import FEATURES, MODEL, ORK, RAW, SCAN_ROWS, SENSORS, STEP, WINDOW, extended_features  # noqa: E402
from sklearn.ensemble import ExtraTreesClassifier  # noqa: E402

ET_PARAMS = r2.ET_PARAMS
AUG_IDX = r2.AUG_IDX
RAW_FILES = sorted(p.name for p in RAW.iterdir() if p.is_file())
RAW_HASH_BEFORE = {fn: sha_file(RAW / fn) for fn in RAW_FILES}
print(f"原始檔案 {len(RAW_FILES)} 個；ET {ET_PARAMS['n_estimators']} trees rs={ET_PARAMS['random_state']}；FIXED11={FEATURES}")
AIR_DEP = [f for f in FEATURES if f not in ("MQ9_slope", "MQ9_delta_mean")]
OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B", 5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}
STAGES = [0, 1, 2, 3]
KEY = lambda d: (d["pid"], d["date"])  # noqa: E731
K101 = {KEY(d) for d in r2.days}

# ─────────────────────────────────────────
# 資料
# ─────────────────────────────────────────
section("資料與品質盤點")


def read_full(path):
    raw = pd.read_excel(path, header=None)
    hdr = [i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip() == "timestamp_ms"]
    if not hdr:
        return None, None, len(raw)
    df = raw.iloc[hdr[0] + 1:].copy()
    df.columns = raw.iloc[hdr[0]].tolist()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all").reset_index(drop=True), hdr[0], len(raw)


def dhash(arr):
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
lab = audit[(audit.has_raw_fruit == 1) & audit.stage.notna()]
FILES = {}


def info(fn):
    if fn not in FILES:
        df, hdr, nraw = read_full(RAW / fn)
        sc = [f"{s}_raw" for s in SENSORS]
        comp = df[df[sc].notna().all(axis=1)].reset_index(drop=True)
        arr = comp[sc].to_numpy(float)
        FILES[fn] = {"arr": arr, "hdr": hdr, "nraw": nraw, "n_rows": len(df), "n_complete": len(comp),
                     "dh": dhash(arr), "missing": int(df[sc].isna().sum().sum()),
                     "oor": int(((df[sc] < 10) | (df[sc] > 1000)).sum().sum()),
                     "dup_consecutive_rows": int((np.diff(arr, axis=0) == 0).all(axis=1).sum()),
                     "ts_monotonic": bool(np.all(np.diff(comp["timestamp_ms"].to_numpy(float)) > 0))}
    return FILES[fn]


META = {}
for a in lab.itertuples():
    k = (int(a.pid), int(a.date))
    META[k] = {"fruit_file": a.fruit_file, "air_file": a.air_file, "stage": int(a.stage), "fruit": info(a.fruit_file), "air": info(a.air_file)}
FRUIT_EQ_AIR = {k for k, m in META.items() if m["fruit"]["dh"] == m["air"]["dh"]}
users = {}
for k, m in META.items():
    users.setdefault(m["air"]["dh"], []).append(k)
SAME_PID_AIR_DUP = {k for us in users.values() for k in us if sum(1 for u in us if u[0] == k[0]) > 1}
CROSS_PID_AIR_SHARE = {k for us in users.values() if len({u[0] for u in us}) > 1 for k in us}
SPECIAL_HEADER = {k for k, m in META.items() if m["fruit"]["hdr"] > 1 or m["air"]["hdr"] > 1}
assert FRUIT_EQ_AIR == {(3, 20260214), (4, 20260206), (11, 20260214)}
assert SAME_PID_AIR_DUP == {(4, 20260203), (4, 20260206), (13, 20260311), (13, 20260312)}
print("fruit==air：", sorted(FRUIT_EQ_AIR))
print("同一顆鳳梨跨日共用 AIR：", sorted(SAME_PID_AIR_DUP))
print("不同鳳梨同日共用 AIR（只標記）：", sorted(CROSS_PID_AIR_SHARE))
print("表頭在第 2 列之後：", sorted(SPECIAL_HEADER))


def flags_of(k):
    return " ".join(n for n, s in (("FRUIT_EQ_AIR", FRUIT_EQ_AIR), ("SAME_PID_AIR_DUP", SAME_PID_AIR_DUP),
                                    ("CROSS_PID_AIR_SHARE", CROSS_PID_AIR_SHARE), ("SPECIAL_HEADER", SPECIAL_HEADER)) if k in s)


def rows_from(arr):
    return [{s: float(v) for s, v in zip(SENSORS, r)} for r in arr]


DAYS = {KEY(d): d for d in r2.days}
for k, m in META.items():
    if k in DAYS:
        continue
    rows = rows_from(m["fruit"]["arr"])
    air = {s: float(m["air"]["arr"][:WINDOW, i].mean()) for i, s in enumerate(SENSORS)}
    DAYS[k] = {"pid": k[0], "date": k[1], "y": m["stage"], "rows": rows, "air": air,
               "feats": [extended_features(rows[s:s + WINDOW], air)[0] for s in range(0, len(rows) - WINDOW + 1, STEP)]}
for k, d in DAYS.items():
    d["group"] = OWNER[d["pid"]]
    d["flags"] = flags_of(k)
    d["air_arr"] = META[k]["air"]["arr"]
    d["air_file"], d["fruit_file"] = META[k]["air_file"], META[k]["fruit_file"]
    # 停止條件：A0 必須等於既有 baseline
    for i, s in enumerate(SENSORS):
        assert abs(d["air_arr"][:WINDOW, i].mean() - d["air"][s]) < 1e-9, f"{k} A0 與既有 baseline 不一致"
    assert np.allclose([[r[s] for s in SENSORS] for r in d["rows"][:WINDOW]], META[k]["fruit"]["arr"][:WINDOW]), f"{k} 鳳梨列不一致"

SETS = {"QA96": sorted(K101 - FRUIT_EQ_AIR - SAME_PID_AIR_DUP), "S99": sorted(K101 - FRUIT_EQ_AIR),
        "S101": sorted(K101), "S100": sorted(set(DAYS) - FRUIT_EQ_AIR)}
for n, ks in SETS.items():
    print(f"{n}: {len(ks)} 天、{len({k[0] for k in ks})} 顆，Stage {pd.Series([DAYS[k]['y'] for k in ks]).value_counts().sort_index().to_dict()}")
assert [len(SETS[s]) for s in ("QA96", "S99", "S101", "S100")] == [96, 99, 101, 100]

# ─────────────────────────────────────────
# 窗口與條件
# ─────────────────────────────────────────
AIR_WIN = {"A0": 0, "A0+10": 10, "A0+20": 20, "A1": 300, "A2": 870}
FRUIT_WIN = {"F0": 0, "F1": 10, "F2": 20}


def air_window(arr, start):
    if len(arr) < start + WINDOW:
        return None
    return {s: float(arr[start:start + WINDOW, i].mean()) for i, s in enumerate(SENSORS)}


def air_qc_ok(k):
    """相鄰日期 AIR 的資格（規格第 3 節）。"""
    if k not in META:
        return False, "not a labelled day"
    if k in FRUIT_EQ_AIR:
        return False, "fruit==air day"
    if k in SAME_PID_AIR_DUP:
        return False, "same-pid cross-date shared AIR"
    a = META[k]["air"]["arr"]
    if len(a) < WINDOW:
        return False, "AIR < 30 rows"
    b = a[:WINDOW].mean(axis=0)
    if np.any(b < 10) or np.any(b > 1000):
        return False, "AIR A0 out of 10-1000"
    return True, ""


def adjacent(k, direction):
    pid, date = k
    cands = sorted(dt for (p, dt) in META if p == pid and (dt < date if direction == "PREV" else dt > date))
    if direction == "PREV":
        cands = cands[::-1]
    skipped = []
    for dt in cands:
        ok, why = air_qc_ok((pid, dt))
        if ok and META[(pid, dt)]["air"]["dh"] == META[k]["air"]["dh"]:
            ok, why = False, "identical AIR data to current day"
        if ok:
            gap = (pd.Timestamp(str(dt)) - pd.Timestamp(str(date))).days
            return (pid, dt), gap, "; ".join(skipped)
        skipped.append(f"{dt}:{why}")
    return None, None, "; ".join(skipped) or f"no {direction.lower()} labelled date for this pineapple"


CONDS = ["B0", "A0+10", "A0+20", "A1", "A2", "PREV", "NEXT", "F1", "F2"]
COND_DESC = {"B0": "F0 + same-day AIR A0 (original pairing)", "A0+10": "F0 + same-day AIR rows 10-39",
             "A0+20": "F0 + same-day AIR rows 20-49", "A1": "F0 + same-day AIR rows 300-329", "A2": "F0 + same-day AIR rows 870-899",
             "PREV": "F0 + previous valid date AIR A0 (COUNTERFACTUAL STRESS TEST)",
             "NEXT": "F0 + next valid date AIR A0 (COUNTERFACTUAL STRESS TEST)",
             "F1": "fruit rows 10-39 + same-day AIR A0", "F2": "fruit rows 20-49 + same-day AIR A0"}
COND = {}  # k -> cond -> dict(features vector, air baseline, fruit_start, air_source)
SKIP = []
for k, d in DAYS.items():
    COND[k] = {}
    for c in CONDS:
        if c in ("B0", "A0+10", "A0+20", "A1", "A2"):
            air = air_window(d["air_arr"], AIR_WIN["A0" if c == "B0" else c])
            fs, src, gap = 0, f"{d['air_file']} rows {AIR_WIN['A0' if c == 'B0' else c]}-{AIR_WIN['A0' if c == 'B0' else c] + 29}", 0
            if air is None:
                SKIP.append({"pineapple_id": k[0], "date": k[1], "condition": c, "reason": f"AIR has {len(d['air_arr'])} rows"})
                continue
        elif c in ("PREV", "NEXT"):
            k2, gap, skipped = adjacent(k, c)
            if k2 is None:
                SKIP.append({"pineapple_id": k[0], "date": k[1], "condition": c, "reason": skipped})
                continue
            air = air_window(META[k2]["air"]["arr"], 0)
            fs, src = 0, f"{META[k2]['air_file']} rows 0-29 (date {k2[1]}; gap {gap:+d} d){'; skipped ' + skipped if skipped else ''}"
        else:
            air, fs, src, gap = d["air"], FRUIT_WIN[c], f"{d['air_file']} rows 0-29", 0
        feat = extended_features(d["rows"][fs:fs + WINDOW], air)[0]
        COND[k][c] = {"x": np.array([feat[f] for f in FEATURES], float), "air": air, "fruit_start": fs, "air_source": src, "gap_days": gap}
    # 停止條件：B0 特徵＝既有 feats[0]；F1／F2＝feats[1]／feats[2]
    for c, i in (("B0", 0), ("F1", 1), ("F2", 2)):
        assert np.allclose(COND[k][c]["x"], [d["feats"][i][f] for f in FEATURES], rtol=0, atol=1e-12), f"{k} {c} 特徵不一致"
print("B0／F1／F2 特徵與既有流程逐日一致（停止條件通過）")
skip = pd.DataFrame(SKIP)
print("無法建立的條件：", skip.groupby("condition").size().to_dict() if len(skip) else {})

INTER = {k for k in DAYS if all(c in COND[k] for c in ("B0", "A0+10", "A0+20", "A1", "A2", "F1", "F2"))}
print(f"同日交集日：{len(INTER)}／{len(DAYS)}；不在交集：{sorted(set(DAYS) - INTER)}")

# ═════════════════════════════════════════
# Part A：AIR 穩定性
# ═════════════════════════════════════════
section("Part A｜AIR baseline 穩定性（描述性）")
AS, PV = [], []
seen = set()
for k in sorted(DAYS):
    d = DAYS[k]
    arr = d["air_arr"]
    dh = META[k]["air"]["dh"]
    first = dh not in seen
    seen.add(dh)
    for i, s in enumerate(SENSORS):
        x = arr[:, i]
        row = {"pineapple_id": k[0], "date": k[1], "group": d["group"], "stage": d["y"], "air_file": d["air_file"],
               "first_occurrence_of_this_AIR_data": first, "data_flags": d["flags"], "sensor": s, "n_rows": len(x),
               "n_unique_adc_values": int(len(np.unique(x))),
               "slope_adc_per_100rows": float(np.polyfit(np.arange(len(x)), x, 1)[0] * 100) if len(x) > 2 else np.nan}
        for w, st in (("A0", 0), ("A1", 300), ("A2", 870)):
            seg = x[st:st + WINDOW] if len(x) >= st + WINDOW else None
            row.update({f"{w}_mean": float(seg.mean()) if seg is not None else np.nan,
                        f"{w}_median": float(np.median(seg)) if seg is not None else np.nan,
                        f"{w}_std": float(seg.std()) if seg is not None else np.nan})
        for w in ("A1", "A2"):
            row[f"A0_to_{w}_abs"] = row[f"{w}_mean"] - row["A0_mean"]
            row[f"A0_to_{w}_rel"] = row[f"A0_to_{w}_abs"] / row["A0_mean"] if row["A0_mean"] >= 10 else np.nan
        row["A0_cv"] = row["A0_std"] / row["A0_mean"] if row["A0_mean"] >= 10 else np.nan
        AS.append(row)
    for c in ("A0+10", "A0+20", "A1", "A2", "PREV", "NEXT"):
        if c not in COND[k]:
            continue
        a = COND[k][c]["air"]
        PV.append({"pineapple_id": k[0], "date": k[1], "group": d["group"], "stage": d["y"], "condition": c,
                   "label": "COUNTERFACTUAL STRESS TEST (not a physical pairing)" if c in ("PREV", "NEXT") else "same-day AIR window (offline counterfactual)",
                   "air_source": COND[k][c]["air_source"], "gap_days": COND[k][c]["gap_days"],
                   **{f"A0_{s}": d["air"][s] for s in SENSORS}, **{f"cond_{s}": a[s] for s in SENSORS},
                   **{f"abs_diff_{s}": a[s] - d["air"][s] for s in SENSORS},
                   **{f"rel_diff_{s}": (a[s] - d["air"][s]) / d["air"][s] for s in SENSORS},
                   "max_abs_rel_diff": max(abs((a[s] - d["air"][s]) / d["air"][s]) for s in SENSORS)})
ast_ = pd.DataFrame(AS)
pv = pd.DataFrame(PV)
ast_.to_csv(HERE / "air_stability.csv", index=False, encoding="utf-8-sig")
pv.to_csv(HERE / "paired_air_variations.csv", index=False, encoding="utf-8-sig")
uq = ast_[ast_.first_occurrence_of_this_AIR_data]
print(f"獨立 AIR 資料份數：{uq[['pineapple_id', 'date']].drop_duplicates().shape[0]}")
summ = uq.groupby("sensor").agg(A0_mean_median=("A0_mean", "median"),
                                rel_A1_median=("A0_to_A1_rel", "median"), rel_A1_p90abs=("A0_to_A1_rel", lambda v: np.nanpercentile(np.abs(v), 90)),
                                rel_A2_median=("A0_to_A2_rel", "median"), rel_A2_p90abs=("A0_to_A2_rel", lambda v: np.nanpercentile(np.abs(v), 90)),
                                rel_A2_maxabs=("A0_to_A2_rel", lambda v: np.nanmax(np.abs(v))),
                                abs_A2_median=("A0_to_A2_abs", "median"), slope_median=("slope_adc_per_100rows", "median"),
                                A0_cv_median=("A0_cv", "median"), n_unique_median=("n_unique_adc_values", "median")).reindex(SENSORS)
print(summ.round(4).to_string())
drift = uq.groupby(["pineapple_id", "date", "group"]).A0_to_A2_rel.apply(lambda v: np.nanmax(np.abs(v))).rename("max_abs_rel_A0_A2").reset_index()
print("明顯漂移（任一感測器 |A0→A2| ≥ 10%）的 AIR：", drift[drift.max_abs_rel_A0_A2 >= 0.10].values.tolist())
print("各群組 A0→A2 最大相對漂移的中位數：", drift.groupby("group").max_abs_rel_A0_A2.median().round(4).to_dict())
print("各群組 A0 平均（中位數）：\n", uq.pivot_table(index="group", columns="sensor", values="A0_mean", aggfunc="median")[SENSORS].round(1).to_string())
print("各階段 A0 平均（中位數）：\n", uq.pivot_table(index="stage", columns="sensor", values="A0_mean", aggfunc="median")[SENSORS].round(1).to_string())
adjd = pv[pv.condition.isin(["PREV", "NEXT"])]
print("相鄰日期 AIR A0 的最大相對差（中位數／90 百分位）：",
      adjd.groupby("condition").max_abs_rel_diff.agg(["median", lambda v: np.percentile(v, 90)]).round(3).to_dict())
print("同日窗口最大相對差（中位數／90 百分位）：",
      pv[~pv.condition.isin(["PREV", "NEXT"])].groupby("condition").max_abs_rel_diff.agg(["median", lambda v: np.percentile(v, 90)]).round(4).to_dict())

# ═════════════════════════════════════════
# 預測：E1 固定模型、E2 LOGO
# ═════════════════════════════════════════
section("E1 固定部署模型／E2 嚴格 LOGO")


def proba(m, X, med=None):
    X = np.asarray(X, float)
    if med is not None:
        X = np.where(np.isnan(X), med, X)
    P = np.zeros((len(X), 4))
    P[:, m.classes_.astype(int)] = m.predict_proba(X)
    return P


def records(k, P_by_cond, extra):
    d = DAYS[k]
    pb = P_by_cond["B0"]
    rb = int(pb.argmax())
    out = []
    for c, p in P_by_cond.items():
        r = int(p.argmax())
        ci = COND[k][c]
        out.append({**extra, "pineapple_id": k[0], "date": k[1], "group": d["group"], "true_stage": d["y"], "data_flags": d["flags"],
                    "in_same_day_intersection": k in INTER, "condition": c, "condition_desc": COND_DESC[c],
                    "fruit_file": d["fruit_file"], "fruit_rows": f"{ci['fruit_start']}-{ci['fruit_start'] + 29}",
                    "air_source": ci["air_source"], "gap_days": ci["gap_days"],
                    **{f"air_{s}": ci["air"][s] for s in SENSORS}, **{f"f_{f}": v for f, v in zip(FEATURES, ci["x"])},
                    **{f"p{j}": float(p[j]) for j in range(4)}, "pred": r, "correct": r == d["y"],
                    "abs_error": abs(r - d["y"]), "severe_error": abs(r - d["y"]) >= 2,
                    "B0_pred": rb, "B0_correct": rb == d["y"], "flip": r != rb, "stage_jump": abs(r - rb),
                    "severe_jump": abs(r - rb) >= 2, "prob_L1_vs_B0": float(np.abs(p - pb).sum()),
                    "prob_maxabs_vs_B0": float(np.abs(p - pb).max())})
    return out


E1 = []
for k in sorted(DAYS):
    E1 += records(k, {c: proba(MODEL, [COND[k][c]["x"]])[0] for c in COND[k]},
                  {"model": "E1 deploy_student.pkl (FIXED-MODEL DIAGNOSTIC, not generalization)"})
e1 = pd.DataFrame(E1)
for s, ks in SETS.items():
    e1[f"in_{s}"] = [(p, dt) in set(ks) for p, dt in zip(e1.pineapple_id, e1.date)]


def logo(keys):
    ds = [DAYS[k] for k in keys]
    out = []
    for fold_id, pid in enumerate(sorted({d["pid"] for d in ds})):
        tr = [d for d in ds if d["pid"] != pid]
        te = [k for k in keys if k[0] == pid]
        assert not any(t["pid"] == pid for t in tr)
        X = np.array([[d["feats"][i][c] for c in FEATURES] for d in tr for i in AUG_IDX], dtype=float)
        yl = np.array([d["y"] for d in tr for _ in AUG_IDX])
        w = np.full(len(yl), 1.0 / len(AUG_IDX))
        med = np.nanmedian(X, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        X = np.where(np.isnan(X), med, X)
        m = ExtraTreesClassifier(**ET_PARAMS).fit(X, yl, sample_weight=w)
        tp = " ".join(map(str, sorted({t["pid"] for t in tr})))
        for k in te:
            cs = list(COND[k])
            P = proba(m, [COND[k][c]["x"] for c in cs], med)
            out += records(k, dict(zip(cs, P)), {"model": "E2 LOGO", "fold_id": fold_id, "test_pid": pid, "train_pids": tp})
    return pd.DataFrame(out)


LOGO = {}
for s in ("QA96", "S99", "S101", "S100"):
    LOGO[s] = logo(SETS[s]).assign(dataset=s)
    print(f"  LOGO {s} 完成（{time.time() - T0:.0f}s）")
# 停止條件：B0＝Step 2.7 Strategy A
s27 = pd.read_csv(EVAL / "single_scan_decision_audit/logo_window_predictions.csv", encoding="utf-8-sig")
for s in ("QA96", "S99", "S101", "S100"):
    b0 = LOGO[s][LOGO[s].condition == "B0"].merge(s27[s27.dataset == s][["pineapple_id", "date", "A_pred"]], on=["pineapple_id", "date"])
    assert len(b0) == len(SETS[s]) and (b0.pred == b0.A_pred).all(), f"{s} B0 與 Step 2.7 Strategy A 不一致"
print("LOGO B0 與 Step 2.7 Strategy A 逐日一致（停止條件通過）")
logo_all = pd.concat(LOGO.values(), ignore_index=True)
logo_all.to_csv(HERE / "logo_air_sensitivity_predictions.csv", index=False, encoding="utf-8-sig")

e1_sets = pd.concat([e1[e1[f"in_{s}"]].assign(dataset=s) for s in ("QA96", "S99", "S101", "S100")], ignore_index=True)
ALLP = pd.concat([logo_all, e1_sets], ignore_index=True)
ALLP["source"] = np.where(ALLP.model.str.startswith("E2"), "E2 LOGO", "E1 FIXED")
cols_ff = [c for c in ALLP.columns if c not in ("in_QA96", "in_S99", "in_S101", "in_S100")]
ALLP[ALLP.condition.isin(["B0", "A0+10", "A0+20", "A1", "A2"])][cols_ff].to_csv(HERE / "fixed_fruit_air_replay.csv", index=False, encoding="utf-8-sig")
ALLP[ALLP.condition.isin(["B0", "F1", "F2"])][cols_ff].to_csv(HERE / "fixed_air_fruit_window_replay.csv", index=False, encoding="utf-8-sig")
adj_out = ALLP[ALLP.condition.isin(["PREV", "NEXT"])][cols_ff].assign(note="COUNTERFACTUAL STRESS TEST — not a physical AIR pairing or a calibration method")
adj_out = adj_out.merge(pv[pv.condition.isin(["PREV", "NEXT"])][["pineapple_id", "date", "condition", "max_abs_rel_diff"]
                                                                  + [f"rel_diff_{s}" for s in SENSORS]],
                        on=["pineapple_id", "date", "condition"], how="left")
pd.concat([adj_out, skip[skip.condition.isin(["PREV", "NEXT"])].assign(note="SKIPPED")], ignore_index=True).to_csv(
    HERE / "adjacent_day_air_stress.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 比較指標
# ═════════════════════════════════════════
section("比較：翻轉、對錯轉換、階段")
VARS = ["A0+10", "A0+20", "A1", "A2", "PREV", "NEXT", "F1", "F2"]


def subset(src, ds, cond, inter=True):
    g = ALLP[(ALLP.source == src) & (ALLP.dataset == ds) & (ALLP.condition == cond)]
    if inter and cond not in ("PREV", "NEXT"):
        g = g[g.in_same_day_intersection]
    return g


def compare(g):
    ca, cb = g.B0_correct, g.correct
    n = len(g)
    return {"n_days": n, "n_pids": g.pineapple_id.nunique(), "flip_rate": g.flip.mean(), "n_flips": int(g.flip.sum()),
            "severe_jump_rate": g.severe_jump.mean(), "n_severe_jumps": int(g.severe_jump.sum()),
            "prob_L1_mean": g.prob_L1_vs_B0.mean(), "prob_L1_median": g.prob_L1_vs_B0.median(),
            "prob_maxabs_mean": g.prob_maxabs_vs_B0.mean(), "B0_accuracy": ca.mean(), "cond_accuracy": cb.mean(),
            "accuracy_diff": cb.mean() - ca.mean(), "correct_to_incorrect": int((ca & ~cb).sum()),
            "incorrect_to_correct": int((~ca & cb).sum()), "incorrect_to_different_incorrect": int((~ca & ~cb & g.flip).sum()),
            "unchanged_incorrect": int((~ca & ~g.flip).sum()), "unchanged_correct": int((ca & ~g.flip).sum()),
            "B0_severe_errors": int((np.abs(g.B0_pred - g.true_stage) >= 2).sum()), "cond_severe_errors": int(g.severe_error.sum()),
            "S2_or_S3_to_S0_B0": int((g.true_stage.isin([2, 3]) & (g.B0_pred == 0)).sum()),
            "S2_or_S3_to_S0_cond": int((g.true_stage.isin([2, 3]) & (g.pred == 0)).sum()),
            "S2S3_switch_to_S0_due_to_cond": int((g.true_stage.isin([2, 3]) & (g.B0_pred != 0) & (g.pred == 0)).sum()),
            "S2S3_leave_S0_due_to_cond": int((g.true_stage.isin([2, 3]) & (g.B0_pred == 0) & (g.pred != 0)).sum())}


SUM, FLIPM, STG = [], [], []
for src in ("E2 LOGO", "E1 FIXED"):
    for ds in ("QA96", "S99", "S101", "S100"):
        for c in VARS:
            g = subset(src, ds, c)
            if not len(g):
                continue
            SUM.append({"source": src, "dataset": ds, "condition": c, "condition_desc": COND_DESC[c],
                        "sample": "same-day intersection" if c not in ("PREV", "NEXT") else "days with a QC-valid adjacent AIR", **compare(g)})
            fm = pd.crosstab(g.B0_pred, g.pred).reindex(index=STAGES, columns=STAGES, fill_value=0)
            FLIPM.append({"source": src, "dataset": ds, "condition": c, "n_days": len(g),
                          **{f"B0_S{i}->S{j}": int(fm.loc[i, j]) for i in STAGES for j in STAGES}})
            for st in STAGES:
                gs = g[g.true_stage == st]
                if len(gs):
                    STG.append({"source": src, "dataset": ds, "condition": c, "true_stage": st, **compare(gs),
                                "B0_recall": gs.B0_correct.mean(), "cond_recall": gs.correct.mean(),
                                "B0_to_S0": int((gs.B0_pred == 0).sum()), "cond_to_S0": int((gs.pred == 0).sum())})
summary = pd.DataFrame(SUM)
summary.to_csv(HERE / "condition_summary.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(FLIPM).to_csv(HERE / "air_flip_matrix.csv", index=False, encoding="utf-8-sig")
stg = pd.DataFrame(STG)
show = ["source", "dataset", "condition", "n_days", "flip_rate", "n_flips", "severe_jump_rate", "prob_L1_mean", "B0_accuracy",
        "cond_accuracy", "correct_to_incorrect", "incorrect_to_correct", "incorrect_to_different_incorrect", "unchanged_incorrect",
        "S2S3_switch_to_S0_due_to_cond", "S2S3_leave_S0_due_to_cond"]
print(summary[summary.dataset.isin(["QA96", "S99"])][show].round(3).to_string(index=False))

# 事後可救回（oracle，描述性）與 S2/3→S0
section("錯誤可救回性（oracle，只描述）與 Stage 2／3 → Stage 0")
REC = []
for src in ("E2 LOGO", "E1 FIXED"):
    for ds in ("QA96", "S99", "S101", "S100"):
        g = ALLP[(ALLP.source == src) & (ALLP.dataset == ds) & ALLP.in_same_day_intersection]
        wide = g.pivot_table(index=["pineapple_id", "date", "true_stage", "group"], columns="condition", values="pred").reset_index()
        y = wide.true_stage
        b0w = wide.B0 != y
        any_A12 = (wide.A1 == y) | (wide.A2 == y)
        all_same = ["B0", "A0+10", "A0+20", "A1", "A2"]
        all_wrong = np.all([wide[c] != y for c in all_same], axis=0)
        s23_s0 = y.isin([2, 3]) & (wide.B0 == 0)
        changes = np.any([wide[c] != wide.B0 for c in ["A0+10", "A0+20", "A1", "A2"]], axis=0)
        fixed_any = np.any([wide[c] == y for c in ["A0+10", "A0+20", "A1", "A2"]], axis=0)
        REC.append({"source": src, "dataset": ds, "n_days": len(wide), "B0_wrong": int(b0w.sum()),
                    "B0_wrong_correct_in_A1_or_A2(oracle)": int((b0w & any_A12).sum()),
                    "B0_wrong_wrong_in_all_same_day_AIR_windows": int((b0w & all_wrong).sum()),
                    "B0_correct_made_wrong_by_A1": int(((wide.B0 == y) & (wide.A1 != y)).sum()),
                    "B0_correct_made_wrong_by_A2": int(((wide.B0 == y) & (wide.A2 != y)).sum()),
                    "B0_correct_made_wrong_by_A1_or_A2": int(((wide.B0 == y) & ((wide.A1 != y) | (wide.A2 != y))).sum()),
                    "oracle_accuracy_best_of_A0_A1_A2(NOT a system metric)": float(((wide.B0 == y) | any_A12).mean()),
                    "B0_S2S3_predicted_S0": int(s23_s0.sum()),
                    "of_which_change_under_any_same_day_AIR": int((s23_s0 & changes).sum()),
                    "of_which_become_correct_under_any_same_day_AIR": int((s23_s0 & fixed_any).sum()),
                    "share_S2S3_S0_that_change": float((s23_s0 & changes).sum() / max(s23_s0.sum(), 1)),
                    "S2S3_S0_days": " ".join(f"{p}/{dt}(S{t}):" + "".join(str(int(wide.loc[i, c])) for c in all_same)
                                             for i, (p, dt, t) in enumerate(zip(wide.pineapple_id, wide.date, wide.true_stage)) if s23_s0.iloc[i])})
rec = pd.DataFrame(REC)
print(rec.round(3).to_string(index=False))
stg_out = pd.concat([stg.assign(table="per true stage"), rec.assign(table="error recoverability (descriptive, oracle)")], ignore_index=True)
stg_out.to_csv(HERE / "stage_error_attribution.csv", index=False, encoding="utf-8-sig")
print(stg[(stg.source == "E2 LOGO") & (stg.dataset == "QA96") & stg.condition.isin(["A1", "A2", "F2", "PREV", "NEXT"])][
    ["condition", "true_stage", "n_days", "flip_rate", "B0_recall", "cond_recall", "B0_to_S0", "cond_to_S0", "n_severe_jumps"]].round(3).to_string(index=False))

# 逐鳳梨、逐群組
PF, PG = [], []
for src in ("E2 LOGO", "E1 FIXED"):
    for ds in ("QA96", "S99"):
        for c in VARS:
            g = subset(src, ds, c)
            for u, gg in g.groupby("pineapple_id"):
                PF.append({"source": src, "dataset": ds, "condition": c, "pineapple_id": u, "group": OWNER[u], **compare(gg)})
            for u, gg in g.groupby("group"):
                PG.append({"source": src, "dataset": ds, "condition": c, "group": u, **compare(gg)})
pf, pg = pd.DataFrame(PF), pd.DataFrame(PG)
pf.to_csv(HERE / "per_fruit_sensitivity.csv", index=False, encoding="utf-8-sig")
pg.to_csv(HERE / "per_group_sensitivity.csv", index=False, encoding="utf-8-sig")
print(pg[(pg.source == "E2 LOGO") & (pg.dataset == "QA96") & pg.condition.isin(["A1", "A2", "F2"])][
    ["condition", "group", "n_days", "flip_rate", "n_flips", "accuracy_diff"]].round(3).to_string(index=False))
print("逐鳳梨翻轉數（LOGO QA96，A1／A2）：", pf[(pf.source == "E2 LOGO") & (pf.dataset == "QA96") & pf.condition.isin(["A1", "A2"])]
      .pivot_table(index="pineapple_id", columns="condition", values="n_flips").astype(int).to_dict())

# ═════════════════════════════════════════
# Bootstrap
# ═════════════════════════════════════════
section("Paired cluster bootstrap（pineapple ID；B=2000；seed=0）")
B_N, B_SEED = 2000, 0


def wide_of(src, ds, conds, inter=True):
    g = ALLP[(ALLP.source == src) & (ALLP.dataset == ds) & ALLP.condition.isin(conds)]
    if inter:
        g = g[g.in_same_day_intersection]
    keys = ["pineapple_id", "date", "true_stage"]
    w = g.pivot_table(index=keys, columns="condition", values="pred").dropna().reset_index()
    return w


def boot(w, stat_fns, name, src, ds, sample):
    pids = w.pineapple_id.to_numpy()
    groups = [np.flatnonzero(pids == p) for p in np.unique(pids)]
    rng = np.random.default_rng(B_SEED)
    pts = {n: f(w) for n, f in stat_fns.items()}
    res = {n: [] for n in stat_fns}
    for _ in range(B_N):
        ix = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        ww = w.iloc[ix]
        for n, f in stat_fns.items():
            res[n].append(f(ww))
    out = []
    for n in stat_fns:
        v = np.array(res[n], float)
        v = v[~np.isnan(v)]
        out.append({"source": src, "dataset": ds, "sample": sample, "metric": n, "point": pts[n],
                    "ci_low": np.percentile(v, 2.5) if len(v) else np.nan, "ci_high": np.percentile(v, 97.5) if len(v) else np.nan,
                    "n_valid_resamples": len(v), "n_days": len(w), "n_clusters": len(groups), "B": B_N, "seed": B_SEED,
                    "ci_method": "percentile", "interpretation": "EXPLORATORY (~13 clusters)"})
    return out


fr = lambda c: (lambda w: float(np.mean(w[c] != w.B0)))  # noqa: E731
ad = lambda c: (lambda w: float(np.mean(w[c] == w.true_stage) - np.mean(w.B0 == w.true_stage)))  # noqa: E731


def sev23(c):
    def f(w):
        m = w.true_stage.isin([2, 3])
        if not m.any():
            return np.nan
        return float(np.mean(np.abs(w[c][m] - w.true_stage[m]) >= 2) - np.mean(np.abs(w.B0[m] - w.true_stage[m]) >= 2))
    return f


BOOT = []
for src in ("E2 LOGO", "E1 FIXED"):
    for ds in ("QA96", "S99"):
        w = wide_of(src, ds, ["B0", "A0+10", "A0+20", "A1", "A2", "F1", "F2"])
        fns = {f"flip rate {c}": fr(c) for c in ("A0+10", "A0+20", "A1", "A2", "F1", "F2")}
        fns.update({f"accuracy diff {c} - B0": ad(c) for c in ("A0+10", "A0+20", "A1", "A2", "F1", "F2")})
        fns["matched: flip(AIR A0+10) - flip(Fruit F1)"] = lambda w: float(np.mean(w["A0+10"] != w.B0) - np.mean(w.F1 != w.B0))
        fns["matched: flip(AIR A0+20) - flip(Fruit F2)"] = lambda w: float(np.mean(w["A0+20"] != w.B0) - np.mean(w.F2 != w.B0))
        fns["flip_same = max(flip A1, flip A2)"] = lambda w: float(max(np.mean(w.A1 != w.B0), np.mean(w.A2 != w.B0)))
        fns["S2/3 severe-error rate change A1 - B0"] = sev23("A1")
        fns["S2/3 severe-error rate change A2 - B0"] = sev23("A2")
        BOOT += boot(w, fns, "", src, ds, "same-day intersection")
        for c in ("PREV", "NEXT"):
            wa = wide_of(src, ds, ["B0", c], inter=False)
            BOOT += boot(wa, {f"flip rate {c} (stress test)": fr(c), f"accuracy diff {c} - B0 (stress test)": ad(c)}, "", src, ds,
                         f"days with QC-valid {c} AIR")
bt = pd.DataFrame(BOOT)
bt.to_csv(HERE / "bootstrap_uncertainty.csv", index=False, encoding="utf-8-sig")
print(bt[bt.source == "E2 LOGO"][["dataset", "sample", "metric", "point", "ci_low", "ci_high", "n_days"]].round(3).to_string(index=False))

# ═════════════════════════════════════════
# AIR 品質指標（不使用標籤）
# ═════════════════════════════════════════
section("AIR 品質指標與 B0 錯誤（Part H；不使用標籤定義指標）")
qi = []
for k in DAYS:
    d = DAYS[k]
    a0 = d["air_arr"][:WINDOW]
    q1 = (max(abs((COND[k]["A2"]["air"][s] - d["air"][s]) / d["air"][s]) for s in SENSORS) if "A2" in COND[k] else np.nan)
    q2 = float(np.max(a0.std(axis=0) / a0.mean(axis=0)))
    qi.append({"pineapple_id": k[0], "date": k[1], "q1_max_rel_drift_A0_A2": q1, "q2_max_cv_A0": q2, "q3_any_flag": bool(d["flags"])})
qi = pd.DataFrame(qi)
QIND = []
for ds in ("QA96", "S99"):
    b0 = ALLP[(ALLP.source == "E2 LOGO") & (ALLP.dataset == ds) & (ALLP.condition == "B0")].merge(qi, on=["pineapple_id", "date"])
    for q in ("q1_max_rel_drift_A0_A2", "q2_max_cv_A0", "q3_any_flag"):
        bb = b0.dropna(subset=[q]).copy()
        if q == "q3_any_flag":
            bb["high"] = bb[q].astype(bool)
            thr = "flag present"
        else:
            t = np.percentile(bb[q], 75)
            bb["high"] = bb[q] >= t
            thr = f">= 75th pct ({t:.4f}, AIR values only)"
        if bb.high.sum() == 0 or (~bb.high).sum() == 0:
            QIND.append({"dataset": ds, "indicator": q, "threshold": thr, "note": "no contrast"})
            continue
        ww = bb.rename(columns={"B0_correct": "ok"})[["pineapple_id", "ok", "high", "true_stage", "pred"]]

        def diff(w):
            h, o = w[w.high], w[~w.high]
            if not len(h) or not len(o):
                return np.nan
            return float((1 - h.ok.mean()) - (1 - o.ok.mean()))

        def diff23(w):
            w = w[w.true_stage.isin([2, 3])]
            h, o = w[w.high], w[~w.high]
            if not len(h) or not len(o):
                return np.nan
            return float((1 - h.ok.mean()) - (1 - o.ok.mean()))
        b = boot(ww, {"error-rate diff (high - other)": diff, "S2/3 error-rate diff (high - other)": diff23}, "", "E2 LOGO", ds, q)
        QIND.append({"dataset": ds, "indicator": q, "threshold": thr, "n_high": int(bb.high.sum()), "n_other": int((~bb.high).sum()),
                     "err_high": 1 - bb[bb.high].B0_correct.mean(), "err_other": 1 - bb[~bb.high].B0_correct.mean(),
                     "diff": b[0]["point"], "diff_ci_low": b[0]["ci_low"], "diff_ci_high": b[0]["ci_high"],
                     "S23_diff": b[1]["point"], "S23_diff_ci_low": b[1]["ci_low"], "S23_diff_ci_high": b[1]["ci_high"],
                     "high_days": " ".join(f"{p}/{dt}" for p, dt in zip(bb[bb.high].pineapple_id, bb[bb.high].date))})
qind = pd.DataFrame(QIND)
qind.to_csv(HERE / "air_quality_indicator_analysis.csv", index=False, encoding="utf-8-sig")
print(qind.drop(columns=["high_days"], errors="ignore").round(3).to_string(index=False))

# ═════════════════════════════════════════
# 資料品質盤點
# ═════════════════════════════════════════
DQ = []
for k, m in sorted(META.items()):
    DQ.append({"pineapple_id": k[0], "date": k[1], "group": OWNER[k[0]], "stage": m["stage"], "fruit_file": m["fruit_file"], "air_file": m["air_file"],
               "fruit_header_row(1-based)": m["fruit"]["hdr"] + 1, "air_header_row(1-based)": m["air"]["hdr"] + 1,
               "fruit_preheat_rows_before_header": m["fruit"]["hdr"], "air_preheat_rows_before_header": m["air"]["hdr"],
               "fruit_rows": m["fruit"]["n_rows"], "air_rows": m["air"]["n_rows"], "fruit_complete_rows": m["fruit"]["n_complete"],
               "air_complete_rows": m["air"]["n_complete"], "fruit_missing": m["fruit"]["missing"], "air_missing": m["air"]["missing"],
               "fruit_out_of_10_1000": m["fruit"]["oor"], "air_out_of_10_1000": m["air"]["oor"],
               "air_identical_consecutive_rows": m["air"]["dup_consecutive_rows"], "air_timestamp_monotonic": m["air"]["ts_monotonic"],
               "flags": flags_of(k), "A1_available": k in DAYS and "A1" in COND[k], "A2_available": k in DAYS and "A2" in COND[k],
               "PREV_air": COND[k]["PREV"]["air_source"] if k in DAYS and "PREV" in COND[k] else "",
               "NEXT_air": COND[k]["NEXT"]["air_source"] if k in DAYS and "NEXT" in COND[k] else "",
               "skip_reasons": "; ".join(f"{r['condition']}: {r['reason']}" for r in SKIP if (r["pineapple_id"], r["date"]) == k),
               **{f"in_{s}": k in set(ks) for s, ks in SETS.items()}, "in_same_day_intersection": k in INTER})
dq = pd.DataFrame(DQ)
dq.to_csv(HERE / "data_quality_inventory.csv", index=False, encoding="utf-8-sig")
print("\n資料盤點：AIR 列數", dq.air_rows.value_counts().to_dict(), "；鳳梨列數", dq.fruit_rows.value_counts().to_dict(),
      "；AIR 缺值", int(dq.air_missing.sum()), "；AIR 超出 10–1000", int(dq.air_out_of_10_1000.sum()),
      "；AIR 連續相同列（中位數）", float(dq.air_identical_consecutive_rows.median()))

# ═════════════════════════════════════════
# 決策
# ═════════════════════════════════════════
section("決策（規格第 8 節）")


def decide(ds):
    b = bt[(bt.source == "E2 LOGO") & (bt.dataset == ds) & (bt["sample"] == "same-day intersection")].set_index("metric")
    f1_, f2_ = b.loc["flip rate A1", "point"], b.loc["flip rate A2", "point"]
    cmax = "A1" if f1_ >= f2_ else "A2"
    flip_same = max(f1_, f2_)
    ci_low = b.loc[f"flip rate {cmax}", "ci_low"]
    g = subset("E2 LOGO", ds, cmax)
    gu = pd.concat([subset("E2 LOGO", ds, "A1"), subset("E2 LOGO", ds, "A2")])
    pids_flip = gu[gu.flip].pineapple_id.nunique()
    top_share = g[g.flip].pineapple_id.value_counts().max() / max(g.flip.sum(), 1) if g.flip.any() else 0.0
    g_nf = [subset("E2 LOGO", ds, c) for c in ("A1", "A2")]
    flip_noflag = max(x[x.data_flags == ""].flip.mean() for x in g_nf)
    r = rec[(rec.source == "E2 LOGO") & (rec.dataset == ds)].iloc[0]
    E = r.share_S2S3_S0_that_change >= 0.25
    I = flip_same >= 0.25 and ci_low >= 0.15 and pids_flip >= 8 and top_share <= 0.30 and flip_noflag >= 0.25
    if flip_same < 0.10:
        cat = "B. AIR VARIATION HAS LIMITED PREDICTIVE IMPACT"
    elif I and E:
        cat = "A. AIR VARIATION IS A MAJOR PREDICTION INSTABILITY FACTOR"
    elif not E:
        cat = "C. AIR EFFECT EXISTS BUT DOES NOT EXPLAIN MAIN ERRORS"
    else:
        cat = "D. EVALUATION INCONCLUSIVE"
    det = {"flip_A1": f1_, "flip_A2": f2_, "flip_same": flip_same, "flip_same_cond": cmax, "flip_same_ci_low": ci_low,
           "pids_with_flip(A1 or A2)": int(pids_flip), "top_pid_share": float(top_share), "flip_same_excluding_flagged_days": float(flip_noflag),
           "S2S3_S0_B0": int(r.B0_S2S3_predicted_S0), "S2S3_S0_change_share": float(r.share_S2S3_S0_that_change),
           "I_met": bool(I), "E_met": bool(E), "category": cat}
    return det


DEC = {ds: decide(ds) for ds in ("QA96", "S99")}
for ds, det in DEC.items():
    print(ds, json.dumps(det, ensure_ascii=False, default=float))
FINAL = DEC["QA96"]["category"] if DEC["QA96"]["category"] == DEC["S99"]["category"] else "D. EVALUATION INCONCLUSIVE (QA96 and S99 disagree)"
worth = []
for q in ("q1_max_rel_drift_A0_A2", "q2_max_cv_A0", "q3_any_flag"):
    a = qind[(qind.dataset == "QA96") & (qind.indicator == q)]
    b = qind[(qind.dataset == "S99") & (qind.indicator == q)]
    if len(a) and "diff" in a and pd.notna(a.iloc[0].get("diff")):
        if a.iloc[0]["diff"] >= 0.15 and a.iloc[0]["diff_ci_low"] > 0 and b.iloc[0]["diff"] > 0:
            worth.append(q)
DEPLOY = "AIR QUALITY CHANGE WORTH FUTURE VALIDATION" if worth else "DO NOT ADD NEW AIR DECISION RULES"
print(f"\n最終決策：{FINAL}")
print(f"部署建議：{DEPLOY}（符合條件的指標：{worth}）")
json.dump({"final_decision": FINAL, "deployment_recommendation": DEPLOY, "qualifying_indicators": worth, "per_dataset": DEC},
          open(HERE / "decision.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=float)

# ═════════════════════════════════════════
# 圖
# ═════════════════════════════════════════
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

fig, axes = plt.subplots(2, 3, figsize=(17, 10))
ax = axes[0, 0]
data1 = [uq[uq.sensor == s].A0_to_A1_rel.dropna() * 100 for s in SENSORS]
data2 = [uq[uq.sensor == s].A0_to_A2_rel.dropna() * 100 for s in SENSORS]
pos = np.arange(len(SENSORS))
ax.boxplot(data1, positions=pos - 0.18, widths=0.3, patch_artist=True, boxprops=dict(facecolor="#9ecae1"), showfliers=True)
ax.boxplot(data2, positions=pos + 0.18, widths=0.3, patch_artist=True, boxprops=dict(facecolor="#fdae6b"), showfliers=True)
ax.axhline(0, color="k", lw=0.8)
ax.set_xticks(pos, SENSORS)
ax.set_ylabel("relative change of AIR baseline (%)")
ax.set_title(f"Same-day AIR drift: A0(0-29) -> A1(300-329) [blue], -> A2(870-899) [orange]\nunique AIR recordings n={uq[['pineapple_id','date']].drop_duplicates().shape[0]}", fontsize=9)
ax = axes[0, 1]
for gi, (g, gg) in enumerate(drift.groupby("group")):
    ax.scatter(np.full(len(gg), gi) + np.random.default_rng(0).uniform(-0.15, 0.15, len(gg)), gg.max_abs_rel_A0_A2 * 100, s=18)
ax.axhline(10, color="r", ls="--", lw=1, label="10% (pre-specified 'notable drift')")
ax.set_xticks(range(drift.group.nunique()), sorted(drift.group.unique()))
ax.set_xlabel("collection group (NOT a device ID)")
ax.set_ylabel("max |A0->A2| relative change over 5 sensors (%)")
ax.set_title("AIR drift by collection group", fontsize=9)
ax.legend(fontsize=8)
ax = axes[0, 2]
base = uq.pivot_table(index=["pineapple_id", "date", "group"], columns="sensor", values="A0_mean").reset_index()
for g, gg in base.groupby("group"):
    ax.scatter(gg.MQ2, gg.TGS2602, label=f"group {g} (n={len(gg)})", s=18)
ax.set_xlabel("AIR A0 MQ2 (ADC)")
ax.set_ylabel("AIR A0 TGS2602 (ADC)")
ax.set_title("AIR A0 baselines differ mainly between groups", fontsize=9)
ax.legend(fontsize=8)
for ax, s in zip(axes[1], ("MQ2", "MQ3", "TGS2602")):
    i = SENSORS.index(s)
    curves = []
    for k in DAYS:
        a = DAYS[k]["air_arr"][:, i]
        if len(a) >= 900:
            curves.append(pd.Series(a[:900] / a[:WINDOW].mean()).rolling(30, min_periods=1).mean().to_numpy())
    C = np.array(curves) * 100 - 100
    t = np.arange(900)
    ax.fill_between(t, np.percentile(C, 10, axis=0), np.percentile(C, 90, axis=0), alpha=0.3, label="10-90 pct")
    ax.plot(t, np.median(C, axis=0), color="k", label="median")
    for st, lab_ in ((0, "A0"), (300, "A1"), (870, "A2")):
        ax.axvspan(st, st + 29, color="orange", alpha=0.3)
        ax.text(st, np.percentile(C, 95), lab_, fontsize=8)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_xlabel("AIR row (1 Hz, parsed ADC rows)")
    ax.set_ylabel("% change vs A0 (30-row rolling mean)")
    ax.set_title(f"{s}: AIR trace relative to A0 (n={len(C)} recordings, all labelled days)", fontsize=9)
    ax.legend(fontsize=8)
fig.suptitle("PineNose Step 3 — AIR baseline stability (descriptive; same-day windows are not independent re-calibrations)", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "air_drift_plots.png", dpi=120)
plt.close(fig)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6.5))
order = [("A0+10", "AIR rows 10-39\n(~10 s)"), ("F1", "Fruit rows 10-39\n(~10 s)"), ("A0+20", "AIR rows 20-49\n(~20 s)"),
         ("F2", "Fruit rows 20-49\n(~20 s)"), ("A1", "AIR rows 300-329\n(~5 min)"), ("A2", "AIR rows 870-899\n(~15 min)"),
         ("PREV", "previous-date AIR\n(stress test)"), ("NEXT", "next-date AIR\n(stress test)")]
x = np.arange(len(order))
for off, (ds, col) in ((-0.2, ("QA96", "C0")), (0.2, ("S99", "C1"))):
    for metric, ax, lab_ in (("flip rate", ax1, "flip rate vs B0"), ("accuracy diff", ax2, "accuracy(cond) - accuracy(B0)")):
        pts, lo, hi, ns = [], [], [], []
        for c, _ in order:
            name = f"{metric} {c}" + (" - B0" if metric == "accuracy diff" else "") + (" (stress test)" if c in ("PREV", "NEXT") else "")
            r_ = bt[(bt.source == "E2 LOGO") & (bt.dataset == ds) & (bt.metric == name)].iloc[0]
            pts.append(r_.point)
            lo.append(r_.point - r_.ci_low)
            hi.append(r_.ci_high - r_.point)
            ns.append(r_.n_days)
        ax.bar(x + off, pts, 0.38, yerr=[lo, hi], capsize=3, color=col, alpha=0.8, label=f"LOGO {ds} (n={ns[0]} same-day / {ns[-2]},{ns[-1]} adjacent)")
        ax.set_xticks(x, [o[1] for o in order], fontsize=8)
        ax.set_ylabel(lab_)
ax1.axhline(0.10, color="gray", ls=":", lw=1)
ax1.axhline(0.25, color="r", ls="--", lw=1, label="pre-specified 0.25 (criterion I)")
ax1.set_title("Prediction flips when only AIR or only Fruit window changes (strict LOGO)\nerror bars: cluster-bootstrap 95% CI (exploratory)", fontsize=9)
ax2.axhline(0, color="k", lw=0.8)
ax2.set_title("Accuracy change vs original pairing B0 (F0 + AIR A0)\n(a higher point estimate is NOT evidence of a better AIR baseline)", fontsize=9)
ax1.legend(fontsize=8)
ax2.legend(fontsize=8)
fig.tight_layout()
fig.savefig(HERE / "air_vs_fruit_sensitivity.png", dpi=120)
plt.close(fig)

# ═════════════════════════════════════════
# 安全檢查
# ═════════════════════════════════════════
section("Git／部署安全檢查")
STATE_AFTER = {str(p): git_state(p) for p in OTHER_WT}
SELF = git_state(ROOT)
PKL_AFTER = sha_file(MODEL_PATH)
raw_after = sorted(p.name for p in RAW.iterdir() if p.is_file())
raw_changed = [fn for fn in RAW_FILES if sha_file(RAW / fn) != RAW_HASH_BEFORE[fn]]
outside = [ln for ln in SELF["status"].splitlines() if ln.strip() and "air_sensitivity_audit" not in ln]
lines = [f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"deploy_student.pkl sha256 before: {PKL_BEFORE}", f"deploy_student.pkl sha256 after : {PKL_AFTER}",
         f"expected                        : {EXPECTED_SHA}", f"model unchanged: {PKL_BEFORE == PKL_AFTER == EXPECTED_SHA}",
         f"raw files before/after: {len(RAW_FILES)}/{len(raw_after)}; content changed: {len(raw_changed)}", ""]
ok_other = True
for p in OTHER_WT:
    b, a = STATE_BEFORE[str(p)], STATE_AFTER[str(p)]
    ok_other &= b == a
    lines += [f"{p}", f"  before: {b['branch']} {b['head'][:12]} status_lines={len(b['status'].splitlines())}",
              f"  after : {a['branch']} {a['head'][:12]} status_lines={len(a['status'].splitlines())}  unchanged={b == a}"]
lines += ["", f"this worktree: {ROOT} ({SELF['branch']} {SELF['head'][:12]})",
          f"  changed paths outside evaluation/air_sensitivity_audit/: {len(outside)}"] + [f"    {x}" for x in outside]
lines += ["", f"other worktrees unchanged: {ok_other}", "no model file written (fold models in memory only)",
          "no serial port, no SSH/paramiko, no credentials used, no server, no network call; Raspberry Pi NOT CONTACTED",
          "Gateway / App / Arduino not modified; no push / merge / deploy"]
(HERE / "git_safety_check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
assert PKL_BEFORE == PKL_AFTER == EXPECTED_SHA and ok_other and not outside and not raw_changed and raw_after == RAW_FILES
print(f"\n完成，耗時 {time.time() - T0:.0f}s")
sys.stdout = sys.__stdout__
LOG.close()
