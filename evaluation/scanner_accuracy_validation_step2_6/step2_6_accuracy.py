"""
Scanner Recovery Step 2.6 — 修正後準確率與陌生鳳梨泛化評估（離線）

規格見 evaluation_protocol.md（先於本程式結果 commit）。
- 資料稽核（AIR／鳳梨配對、重複、缺值、預熱 log、表頭位置、異常成因）
- Part A：固定部署模型重播 C0～C3（歷史訓練資料，非泛化）
- Part B：LOGO（Round 2 實驗 C 訓練定義），同折同模型比較 C0／C1／C2／C3，並重現 LOGO-Reference
- Part C：day／fruit 指標、以鳳梨為群集的 bootstrap
- Part D：基準、錯誤結構、機率描述、同次記錄內窗口穩定性
- Part E：群組
不寫出任何模型檔；不連接任何設備。

Run（在 evaluation/ 目錄）：python -u scanner_accuracy_validation/step2_6_accuracy.py
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

sys.dont_write_bytecode = True  # 不在 pineapple_app_gateway/ 等受保護目錄留下 __pycache__
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


def section(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ─────────────────────────────────────────
# 安全快照（之前）
# ─────────────────────────────────────────
OTHER_WT = [Path("c:/Users/user/electronic-nose-pineapple-ripeness-assessment"), Path("c:/Users/user/enose-gateway-fix"),
            Path("c:/Users/user/enose-fingerprint-study"), Path("c:/Users/user/enose-scanner-recovery"),
            Path("c:/Users/user/enose-scanner-recovery-step2-5")]
OUT_REL = "Semester 2 Final Exam (三下-期末)/evaluation/scanner_accuracy_validation/"


def git_state(p):
    g = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True).stdout.decode("utf-8", "replace").strip()  # noqa: E731
    return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "head": g("rev-parse", "HEAD"), "status": g("status", "--porcelain")}


MODEL_PATH = WT / "pineapple_final/deploy_student.pkl"
EXPECTED_SHA = "a57dbbbf3a3dd7f27d59c3006d8319faf7e16431d6c06eaa3a55ec84d26f16a1"
STATE_BEFORE = {str(p): git_state(p) for p in OTHER_WT}
SELF_BEFORE = git_state(ROOT)
PKL_BEFORE = sha_file(MODEL_PATH)

# ─────────────────────────────────────────
# 既有流程（Round 2）：資料、特徵、模型參數
# ─────────────────────────────────────────
section("載入 Round 2 資料流程（retrain_round2 / eval_common）")
import retrain_round2 as r2  # noqa: E402
from eval_common import FEATURES, MODEL, ORK, RAW, SCAN_ROWS, SENSORS, STEP, WINDOW, extended_features, old  # noqa: E402
from sklearn.ensemble import ExtraTreesClassifier  # noqa: E402
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support  # noqa: E402

ET_PARAMS = r2.ET_PARAMS
AUG_IDX, K = r2.AUG_IDX, r2.K
print("ET 參數：", {k: ET_PARAMS[k] for k in ("n_estimators", "max_features", "random_state", "bootstrap", "criterion", "max_depth", "class_weight")})
print("FIXED11：", FEATURES)
print(f"WINDOW={WINDOW} STEP={STEP} SCAN_ROWS={SCAN_ROWS} 訓練窗口起點={r2.AUG_STARTS} 測試三窗口數 K={K}")
OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B", 5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}
STAGES = [0, 1, 2, 3]
SNAME = {0: "S0 unripe", 1: "S1 early", 2: "S2 ripe", 3: "S3 overripe"}

DAYS101 = r2.days
for d in DAYS101:
    d["group"] = OWNER[d["pid"]]
KEY = lambda d: (d["pid"], d["date"])  # noqa: E731
K101 = {KEY(d) for d in DAYS101}


# ═════════════════════════════════════════
# 資料稽核
# ═════════════════════════════════════════
section("資料稽核")


def read_full(path):
    """掃描整個檔案找 timestamp_ms 表頭（Round 2 只掃前 10 列）。"""
    raw = pd.read_excel(path, header=None)
    hdr = [i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip() == "timestamp_ms"]
    if not hdr:
        return None, None, len(raw)
    df = raw.iloc[hdr[0] + 1:].copy()
    df.columns = raw.iloc[hdr[0]].tolist()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all").reset_index(drop=True), hdr[0], len(raw)


def data_hash(df):
    cols = [f"{s}_raw" for s in SENSORS]
    return hashlib.sha256(df[cols].to_numpy(float).tobytes()).hexdigest()


def rows_of(df):
    out = []
    for _, r in df.iterrows():
        row = {s: r.get(f"{s}_raw") for s in SENSORS}
        if any(pd.isna(v) for v in row.values()):
            continue
        row = {k: float(v) for k, v in row.items()}
        ts = r.get("timestamp_ms")
        row["timestamp_ms"] = None if pd.isna(ts) else float(ts)
        out.append(row)
    return out


audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
lab = audit[audit.stage.notna()].copy()
print(f"標籤表：有 stage 的列 {len(lab)}；其中 has_raw_fruit==1：{int((lab.has_raw_fruit == 1).sum())}")
cache = {}


def load_file(fname):
    if not isinstance(fname, str) or not (RAW / fname).exists():
        return None
    if fname not in cache:
        df, hdr, nraw = read_full(RAW / fname)
        cache[fname] = {"df": df, "hdr": hdr, "nraw": nraw, "sha": sha_file(RAW / fname),
                        "dhash": data_hash(df) if df is not None else None}
    return cache[fname]


AUD = []
for a in lab.sort_values(["pid", "date"]).itertuples():
    f, ai = load_file(a.fruit_file), load_file(a.air_file)
    rec = {"pineapple_id": int(a.pid), "date": int(a.date), "group": OWNER.get(int(a.pid), "?"), "stage": int(a.stage),
           "has_raw_fruit(label table)": int(a.has_raw_fruit), "fruit_file": a.fruit_file, "air_file": a.air_file,
           "fruit_exists": f is not None, "air_exists": ai is not None}
    for role, x in (("fruit", f), ("air", ai)):
        if x is None or x["df"] is None:
            rec.update({f"{role}_header_row": None if x is None else "NOT FOUND"})
            continue
        df = x["df"]
        sc = [f"{s}_raw" for s in SENSORS]
        ts = df["timestamp_ms"].to_numpy(float)
        dts = np.diff(ts[np.isfinite(ts)])
        rec.update({
            f"{role}_header_row": x["hdr"] + 1,  # 1-based Excel 列號
            f"{role}_preheat_rows_before_header": x["hdr"],
            f"{role}_readable_by_round2_reader(first10)": x["hdr"] < 10,
            f"{role}_data_rows": len(df),
            f"{role}_complete_rows": int(df[sc].notna().all(axis=1).sum()),
            f"{role}_missing_values": int(df[sc].isna().sum().sum()),
            f"{role}_out_of_valid_range(10-1000)": int(((df[sc] < 10) | (df[sc] > 1000)).sum().sum()),
            f"{role}_timestamp_monotonic": bool(np.all(dts > 0)) if len(dts) else None,
            f"{role}_median_interval_ms": float(np.median(dts)) if len(dts) else None,
            f"{role}_file_sha256_prefix": x["sha"][:12],
            f"{role}_data_sha256_prefix": x["dhash"][:12],
        })
    rec["same_path(fruit_file==air_file)"] = a.fruit_file == a.air_file
    rec["same_file_bytes"] = bool(f and ai and f["sha"] == ai["sha"])
    rec["same_sensor_data(fruit==air)"] = bool(f and ai and f["dhash"] and f["dhash"] == ai["dhash"])
    AUD.append(rec)
aud = pd.DataFrame(AUD)

# 重複：同一份感測資料出現在其他鳳梨日（任一角色）
occ = {}
for r in aud.itertuples():
    for role, fn in (("fruit", r.fruit_file), ("air", r.air_file)):
        x = cache.get(fn)
        if x and x["dhash"]:
            occ.setdefault(x["dhash"], set()).add((role, r.pineapple_id, r.date, fn))
dup_f, dup_a, air_shared = [], [], []
for r in aud.itertuples():
    me = (r.pineapple_id, r.date)
    for role, fn, store in (("fruit", r.fruit_file, dup_f), ("air", r.air_file, dup_a)):
        x = cache.get(fn)
        others = sorted({f"{ro}:{p}/{dt}" for ro, p, dt, f2 in occ.get(x["dhash"], set()) if (p, dt) != me}) if x and x["dhash"] else []
        store.append(" ".join(others))
    air_shared.append(int(sum(1 for q in aud.itertuples() if q.air_file == r.air_file)) - 1)
aud["fruit_data_also_appears_as"] = dup_f
aud["air_data_also_appears_as"] = dup_a
aud["air_file_used_by_other_days"] = air_shared

RULE_EXCL = {(int(r["pineapple_id"]), int(r["date"])) for _, r in aud.iterrows() if r["same_sensor_data(fruit==air)"]}
print("符合排除規則（鳳梨感測資料＝同日空氣）的鳳梨日：", sorted(RULE_EXCL))
for k in sorted(RULE_EXCL):
    r = aud[(aud.pineapple_id == k[0]) & (aud.date == k[1])].iloc[0]
    cause = ("同一路徑被重複引用" if r["same_path(fruit_file==air_file)"] else
             ("不同路徑、檔案位元組完全相同（複製檔）" if r["same_file_bytes"] else "不同路徑、位元組不同但感測資料相同"))
    print(f"  {k}: fruit={r.fruit_file} air={r.air_file} → {cause}")
    aud.loc[(aud.pineapple_id == k[0]) & (aud.date == k[1]), "anomaly_cause"] = cause

# 擴充資料：所有可讀、列數足夠的有標籤鳳梨日
DAYS_ALL = {KEY(d): d for d in DAYS101}
for r in aud.itertuples():
    k = (r.pineapple_id, r.date)
    f = cache.get(r.fruit_file)
    if k in DAYS_ALL or f is None or f["df"] is None:
        continue
    rows = rows_of(f["df"])
    if len(rows) < SCAN_ROWS:
        continue
    ai = cache.get(r.air_file)
    air = ({s: float(ai["df"][f"{s}_raw"].iloc[:WINDOW].mean()) for s in SENSORS} if ai and ai["df"] is not None else None)
    assert air is not None, f"{k} 沒有空氣檔"
    DAYS_ALL[k] = {"pid": r.pineapple_id, "date": r.date, "y": r.stage, "rows": rows, "air": air, "group": OWNER[r.pineapple_id],
                   "feats": [extended_features(rows[s:s + WINDOW], air)[0] for s in range(0, len(rows) - WINDOW + 1, STEP)]}
    print(f"  擴充讀入：{k} stage={r.stage} 列數={len(rows)}")
# 101 天：全掃描讀檔結果與 Round 2 讀檔一致
for d in DAYS101:
    r = aud[(aud.pineapple_id == d["pid"]) & (aud.date == d["date"])].iloc[0]
    assert len(rows_of(cache[r.fruit_file]["df"])) == len(d["rows"])

SETS = {
    "S99": [DAYS_ALL[k] for k in sorted(K101 - RULE_EXCL)],
    "S101": [DAYS_ALL[k] for k in sorted(K101)],
    "S100": [DAYS_ALL[k] for k in sorted(set(DAYS_ALL) - RULE_EXCL)],
    "S103": [DAYS_ALL[k] for k in sorted(DAYS_ALL)],
}
SET_DESC = {"S99": "PRIMARY: Round-2 101 days minus fruit==air anomalies",
            "S101": "Round-2 original 101 days (incl. anomalies)",
            "S100": "EXTENDED: all readable labelled days minus fruit==air anomalies",
            "S103": "EXTENDED: all readable labelled days (incl. anomalies)"}
for name, ds in SETS.items():
    print(f"{name}: {len(ds)} 天，{len({d['pid'] for d in ds})} 顆鳳梨，Stage 分布 "
          f"{pd.Series([d['y'] for d in ds]).value_counts().sort_index().to_dict()} — {SET_DESC[name]}")
aud["in_S101"] = [(r.pineapple_id, r.date) in K101 for r in aud.itertuples()]
for n in ("S99", "S100", "S103"):
    ks = {KEY(d) for d in SETS[n]}
    aud[f"in_{n}"] = [(r.pineapple_id, r.date) in ks for r in aud.itertuples()]


def excl_reason(r):
    k = (r.pineapple_id, r.date)
    if k in RULE_EXCL:
        return "fruit sensor data identical to same-day air file (" + str(r.get("anomaly_cause")) + ")"
    if not r["fruit_exists"]:
        return "no raw fruit file"
    if k not in DAYS_ALL:
        return "unreadable or fewer than SCAN_ROWS rows"
    if k not in K101:
        return "included in extended sets only (header after row 10, missed by Round-2 reader)"
    return ""


aud["exclusion_or_note"] = [excl_reason(r) for _, r in aud.iterrows()]
aud.to_csv(HERE / "data_quality_audit.csv", index=False, encoding="utf-8-sig")
print("有預熱 log（表頭不在第 1–2 列）的鳳梨檔：",
      aud[aud.fruit_preheat_rows_before_header.fillna(0) > 1][["pineapple_id", "date", "fruit_header_row"]].values.tolist())
print("缺值總數（鳳梨檔）：", int(aud.fruit_missing_values.fillna(0).sum()), "；超出 10–1000 的值（鳳梨檔）：",
      int(aud["fruit_out_of_valid_range(10-1000)"].fillna(0).sum()))
print("感測資料在其他鳳梨日重複出現的鳳梨檔：", aud[aud.fruit_data_also_appears_as != ""][["pineapple_id", "date", "fruit_data_also_appears_as"]].values.tolist())


# ═════════════════════════════════════════
# 共用：指標
# ═════════════════════════════════════════
def mets(yt, yp):
    yt, yp = np.asarray(yt, int), np.asarray(yp, int)
    present = sorted(set(yt.tolist()))
    P, R, F, S = precision_recall_fscore_support(yt, yp, labels=STAGES, zero_division=0)
    out = {"n_days": len(yt), "accuracy": float(np.mean(yt == yp)),
           "macro_f1": float(np.mean([F[k] for k in present])), "balanced_accuracy": float(np.mean([R[k] for k in present])),
           "stages_present": ",".join(f"S{k}" for k in present)}
    for k in STAGES:
        out.update({f"precision_s{k}": float(P[k]), f"recall_s{k}": float(R[k]), f"f1_s{k}": float(F[k]), f"support_s{k}": int(S[k])})
    out["pred_dist"] = str(np.bincount(yp, minlength=4).tolist())
    return out


def cm_of(yt, yp):
    return confusion_matrix(yt, yp, labels=STAGES)


def fruit_table(df, scope, variant):
    rows = []
    for pid, g in df.groupby("pineapple_id"):
        err = g[g.true_stage != g.pred_stage]
        main = err.groupby(["true_stage", "pred_stage"]).size().sort_values(ascending=False)
        rows.append({"scope": scope, "variant": variant, "pineapple_id": pid, "group": OWNER[pid], "n_days": len(g),
                     "correct": int((g.true_stage == g.pred_stage).sum()), "wrong": len(err),
                     "accuracy": float(np.mean(g.true_stage == g.pred_stage)),
                     "stages_present": ",".join(f"S{k}" for k in sorted(g.true_stage.unique())),
                     "main_error": (f"S{main.index[0][0]}->S{main.index[0][1]} x{int(main.iloc[0])}" if len(main) else ""),
                     "all_errors": " ".join(f"S{a}->S{b}x{n}" for (a, b), n in main.items())})
    return rows


def old_post(raw_pred, proba, feat):
    """舊版 Gateway：early override 優先；未觸發才跑 overripe override。"""
    p, early = old._early_stage_override(raw_pred, proba, feat)
    if early:
        return int(p), "early"
    p, over = old._overripe_override(raw_pred, proba, feat)
    return int(p), ("overripe" if over else "")


STAB_STARTS = [0, 150, 300, 450, 600, 750]


# ═════════════════════════════════════════
# Part A：固定部署模型
# ═════════════════════════════════════════
section("Part A｜固定部署模型重播（歷史訓練資料，不是泛化測試）")


def proba_dep(x):
    p = np.zeros(4)
    p[MODEL.classes_.astype(int)] = MODEL.predict_proba(np.asarray(x, float).reshape(1, -1))[0]
    return p


def predict_variants(d, pfun):
    """回傳 C0～C3 的 (raw, final, override, proba)。pfun(list of feature rows) -> (n,4) proba。"""
    fo = old._build_features(d["rows"][:WINDOW], d["air"])[0]
    P0 = pfun([[fo.get(f, 0.0) for f in FEATURES]])[0]
    r0 = int(np.argmax(P0))
    f0, o0 = old_post(r0, P0, fo)
    Pw = pfun([[d["feats"][i][c] for c in FEATURES] for i in range(K)])
    P2 = Pw[0]
    r2_ = int(np.argmax(P2))
    f1, o1 = old_post(r2_, P2, d["feats"][0])
    P3 = Pw.mean(axis=0)
    r3 = int(np.argmax(P3))
    return {"C0": (r0, f0, o0, P0), "C1": (r2_, f1, o1, P2), "C2": (r2_, r2_, "", P2), "C3": (r3, r3, "", P3)}


dep_pfun = lambda X: np.vstack([proba_dep(x) for x in X])  # noqa: E731
PA = []
for k, d in sorted(DAYS_ALL.items()):
    v = predict_variants(d, dep_pfun)
    for name, (raw, fin, ov, P) in v.items():
        PA.append({"pineapple_id": d["pid"], "date": d["date"], "group": d["group"], "true_stage": d["y"], "variant": name,
                   "raw_pred": raw, "pred_stage": fin, "override": ov, **{f"p{j}": float(P[j]) for j in range(4)}})
pa = pd.DataFrame(PA)

# 與 Step 2.5 的逐日結果比對
s25 = pd.read_csv(EVAL / "scanner_recovery_step2_5/prediction_variant_comparison.csv", encoding="utf-8-sig")
chk = {}
for v, col in (("C0", "C0_final"), ("C1", "C1_final"), ("C2", "C2_final"), ("C3", "C3_final")):
    m = pa[pa.variant == v].merge(s25[["pineapple_id", "date", col]], on=["pineapple_id", "date"])
    chk[v] = f"{int((m.pred_stage == m[col]).sum())}/{len(m)}"
print("Part A 與 Step 2.5 逐日最終預測一致：", chk)

FMC, STAGE_ROWS, FRUIT_ROWS, GROUP_ROWS, CMS = [], [], [], [], {}
for scope, ds in SETS.items():
    ks = {KEY(d) for d in ds}
    sub = pa[[(p, dt) in ks for p, dt in zip(pa.pineapple_id, pa.date)]]
    for v in ("C0", "C1", "C2", "C3"):
        s = sub[sub.variant == v]
        m = mets(s.true_stage, s.pred_stage)
        fr = fruit_table(s, scope, f"A-{v}")
        FMC.append({"part": "A (deployed model, in-sample replay — NOT generalization)", "scope": scope, "variant": v,
                    "n_pids": s.pineapple_id.nunique(), "override_count": int((s.override != "").sum()),
                    "raw_pred_dist": str(np.bincount(s.raw_pred, minlength=4).tolist()),
                    "fruit_mean_accuracy": float(np.mean([r["accuracy"] for r in fr])), **m})
        CMS[f"A {scope} {v}"] = cm_of(s.true_stage, s.pred_stage)
        for k in STAGES:
            STAGE_ROWS.append({"part": "A", "scope": scope, "variant": v, "stage": k, "precision": m[f"precision_s{k}"],
                               "recall": m[f"recall_s{k}"], "f1": m[f"f1_s{k}"], "support": m[f"support_s{k}"],
                               "n_predicted": int((s.pred_stage == k).sum())})
        if scope in ("S99", "S101"):
            FRUIT_ROWS += fr
fmc = pd.DataFrame(FMC)
pd.set_option("display.width", 250)
print(fmc[["scope", "variant", "n_days", "accuracy", "macro_f1", "balanced_accuracy", "recall_s0", "recall_s1", "recall_s2",
           "recall_s3", "pred_dist", "override_count"]].round(3).to_string(index=False))


# ═════════════════════════════════════════
# Part B：LOGO
# ═════════════════════════════════════════
section("Part B｜嚴格 Leave-One-Pineapple-Out")


def logo(ds, unit="pid", params=None, stability=False, tag=""):
    params = params or ET_PARAMS
    rows, stab, folds = [], [], []
    units = sorted({(d["pid"] if unit == "pid" else d["group"]) for d in ds})
    for fold_id, u in enumerate(units):
        uf = (lambda d: d["pid"]) if unit == "pid" else (lambda d: d["group"])
        tr = [d for d in ds if uf(d) != u]
        te = [d for d in ds if uf(d) == u]
        test_pids = {d["pid"] for d in te}
        assert not any(t["pid"] in test_pids for t in tr), "測試鳳梨出現在訓練集"
        X = np.array([[d["feats"][i][c] for c in FEATURES] for d in tr for i in AUG_IDX], dtype=float)
        yl = np.array([d["y"] for d in tr for _ in AUG_IDX])
        w = np.full(len(yl), 1.0 / len(AUG_IDX))
        med = np.nanmedian(X, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        X = np.where(np.isnan(X), med, X)
        m = ExtraTreesClassifier(**params).fit(X, yl, sample_weight=w)
        cls = m.classes_.astype(int)

        def pfun(Xt):
            Xt = np.asarray(Xt, float)
            Xt = np.where(np.isnan(Xt), med, Xt)
            P = np.zeros((len(Xt), 4))
            P[:, cls] = m.predict_proba(Xt)
            return P

        train_pids = " ".join(map(str, sorted({t["pid"] for t in tr})))
        folds.append({"fold_id": fold_id, "held_out": u, "test_pids": " ".join(map(str, sorted(test_pids))),
                      "train_pids": train_pids, "n_train_days": len(tr), "n_test_days": len(te),
                      "train_classes": ",".join(f"S{k}" for k in cls)})
        for d in te:
            v = predict_variants(d, pfun)
            for name, (raw, fin, ov, P) in v.items():
                rows.append({"fold_id": fold_id, "held_out_unit": u, "train_pids": train_pids, "pineapple_id": d["pid"],
                             "date": d["date"], "group": d["group"], "true_stage": d["y"], "variant": name, "raw_pred": raw,
                             "pred_stage": fin, "override": ov, **{f"p{j}": float(P[j]) for j in range(4)},
                             "random_state": params["random_state"]})
            if stability:
                idx = [s // STEP for s in STAB_STARTS if s // STEP < len(d["feats"])]
                for model_name, pf in (("LOGO-C2 out-of-fold", pfun), ("deployed (in-sample)", dep_pfun)):
                    P = pf([[d["feats"][i][c] for c in FEATURES] for i in idx])
                    stab.append({"model": model_name, "pineapple_id": d["pid"], "date": d["date"], "group": d["group"],
                                 "true_stage": d["y"], "P": P, "starts": [i * STEP for i in idx]})
    return pd.DataFrame(rows), stab, pd.DataFrame(folds)


# LOGO-Reference：直接呼叫 Round 2 的 run()
ref_out, _ = r2.run(4, "multi", "FIXED11")
ref = pd.DataFrame({"pineapple_id": ref_out["pid"], "date": ref_out["date"], "true_stage": ref_out["y"], "pred_stage": ref_out["three"]})
ref_m = mets(ref.true_stage, ref.pred_stage)
print(f"LOGO-Reference（Round 2 run() 原樣重跑，S101）：accuracy={ref_m['accuracy']:.3f} macro-F1={ref_m['macro_f1']:.3f} "
      f"（歷史值 0.426／0.410）")

LOGO, STAB, FOLDS = {}, {}, {}
for scope in ("S99", "S101", "S100", "S103"):
    LOGO[scope], STAB[scope], FOLDS[scope] = logo(SETS[scope], stability=(scope == "S99"))
    print(f"  {scope} 完成（{time.time() - T0:.0f}s）")
c3_101 = LOGO["S101"][LOGO["S101"].variant == "C3"].merge(ref, on=["pineapple_id", "date", "true_stage"])
print(f"本程式 LOGO-C3（S101）與 Round 2 run() 逐日一致：{int((c3_101.pred_stage_x == c3_101.pred_stage_y).sum())}/{len(c3_101)}")

LOGO_MET = [{"scope": "S101", "variant": "LOGO-Reference (Round-2 run(), 3-window test)", "n_pids": 13, **ref_m,
             "fruit_mean_accuracy": float(np.mean([r["accuracy"] for r in fruit_table(ref.assign(group=""), "S101", "ref")])),
             "override_count": 0, "leakage_flag": ""}]
CMS["LOGO S101 Reference"] = cm_of(ref.true_stage, ref.pred_stage)
LEAK = "POTENTIAL LEAKAGE: legacy override thresholds hand-tuned on historical data — diagnostic only"
for scope, df in LOGO.items():
    for v in ("C0", "C1", "C2", "C3"):
        s = df[df.variant == v]
        m = mets(s.true_stage, s.pred_stage)
        fr = fruit_table(s, scope, f"LOGO-{v}")
        LOGO_MET.append({"scope": scope, "variant": f"LOGO-{v}", "n_pids": s.pineapple_id.nunique(), **m,
                         "fruit_mean_accuracy": float(np.mean([r["accuracy"] for r in fr])),
                         "override_count": int((s.override != "").sum()), "leakage_flag": LEAK if v in ("C0", "C1") else ""})
        CMS[f"LOGO {scope} {v}"] = cm_of(s.true_stage, s.pred_stage)
        for k in STAGES:
            STAGE_ROWS.append({"part": "B (LOGO)", "scope": scope, "variant": v, "stage": k, "precision": m[f"precision_s{k}"],
                               "recall": m[f"recall_s{k}"], "f1": m[f"f1_s{k}"], "support": m[f"support_s{k}"],
                               "n_predicted": int((s.pred_stage == k).sum())})
        FRUIT_ROWS += fr
lm = pd.DataFrame(LOGO_MET)
print(lm[["scope", "variant", "n_days", "accuracy", "macro_f1", "balanced_accuracy", "fruit_mean_accuracy", "recall_s0", "recall_s1",
          "recall_s2", "recall_s3", "pred_dist", "override_count"]].round(3).to_string(index=False))

# 事後診斷：種子 0～9（不用於選擇）
SEED_ROWS = []
for seed in range(10):
    df, _, _ = logo(SETS["S99"], params={**ET_PARAMS, "random_state": seed})
    for v in ("C0", "C2", "C3"):
        s = df[df.variant == v]
        mm = mets(s.true_stage, s.pred_stage)
        SEED_ROWS.append({"seed": seed, "variant": v, "accuracy": mm["accuracy"], "macro_f1": mm["macro_f1"],
                          "recall_s2": mm["recall_s2"], "recall_s3": mm["recall_s3"]})
seeds = pd.DataFrame(SEED_ROWS)
seed_sum = seeds.groupby("variant").agg(["mean", "std", "min", "max"]).round(3)
print("事後診斷：S99 LOGO，random_state 0～9（不用於選擇）\n", seed_sum.to_string())
dseed = seeds[seeds.variant == "C2"].set_index("seed").accuracy - seeds[seeds.variant == "C0"].set_index("seed").accuracy
print("每個種子 C2−C0 accuracy：", dseed.round(3).tolist())


# ═════════════════════════════════════════
# Part C：Bootstrap
# ═════════════════════════════════════════
section("Part C｜以鳳梨為群集的 bootstrap（B=2000, seed=0）")


def mf1_present(t, p):
    present = np.unique(t)
    _, _, F, _ = precision_recall_fscore_support(t, p, labels=STAGES, zero_division=0)
    return float(np.mean(F[present]))


def boot(scope, a="C0", b="C2", B=2000, seed=0):
    df = LOGO[scope]
    A = df[df.variant == a].sort_values(["pineapple_id", "date"]).reset_index(drop=True)
    Bv = df[df.variant == b].sort_values(["pineapple_id", "date"]).reset_index(drop=True)
    assert (A[["pineapple_id", "date"]].values == Bv[["pineapple_id", "date"]].values).all()
    yt, pa_, pb_ = A.true_stage.to_numpy(), A.pred_stage.to_numpy(), Bv.pred_stage.to_numpy()
    pids = A.pineapple_id.to_numpy()
    groups = [np.flatnonzero(pids == p) for p in np.unique(pids)]
    rng = np.random.default_rng(seed)
    res, missing = [], 0
    for _ in range(B):
        idx = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        t, x, y = yt[idx], pa_[idx], pb_[idx]
        missing += len(np.unique(t)) < 4
        res.append((np.mean(y == t), mf1_present(t, y), np.mean(x == t), mf1_present(t, x),
                    np.mean(y == t) - np.mean(x == t), mf1_present(t, y) - mf1_present(t, x)))
    r = np.array(res)
    names = [f"{b} accuracy", f"{b} macro-F1", f"{a} accuracy", f"{a} macro-F1", f"{b}-{a} accuracy diff", f"{b}-{a} macro-F1 diff"]
    point = [np.mean(pb_ == yt), mf1_present(yt, pb_), np.mean(pa_ == yt), mf1_present(yt, pa_),
             np.mean(pb_ == yt) - np.mean(pa_ == yt), mf1_present(yt, pb_) - mf1_present(yt, pa_)]
    out = []
    for i, n in enumerate(names):
        out.append({"scope": scope, "metric": f"LOGO {n}", "point": point[i], "ci_low": np.percentile(r[:, i], 2.5),
                    "ci_high": np.percentile(r[:, i], 97.5), "boot_mean": r[:, i].mean(),
                    "share_boot_ge_0": float(np.mean(r[:, i] >= 0)) if "diff" in n else None,
                    "resamples_missing_a_stage": f"{missing}/{B}", "n_clusters": len(groups), "B": B, "seed": seed,
                    "macro_f1_definition": "mean F1 over stages present in the resample's true labels"})
    return out


BOOT = []
for scope in ("S99", "S101", "S100"):
    BOOT += boot(scope)
BOOT += [r for r in boot("S99", a="C2", b="C3") if "diff" in r["metric"]]
bt = pd.DataFrame(BOOT)
print(bt[["scope", "metric", "point", "ci_low", "ci_high", "share_boot_ge_0", "resamples_missing_a_stage"]].round(3).to_string(index=False))


# ═════════════════════════════════════════
# Part D：基準、錯誤結構、機率、窗口穩定性
# ═════════════════════════════════════════
section("Part D｜基準與錯誤分析")
BASE = []
for scope in ("S99", "S101", "S100"):
    y = np.array([d["y"] for d in SETS[scope]])
    maj = int(np.bincount(y).argmax())
    mm = mets(y, np.full_like(y, maj))
    # LOGO 版多數類別：每折用訓練鳳梨的多數類別
    yp_logo = []
    for d in SETS[scope]:
        ytr = np.array([t["y"] for t in SETS[scope] if t["pid"] != d["pid"]])
        yp_logo.append(int(np.bincount(ytr, minlength=4).argmax()))
    ml = mets(y, yp_logo)
    prior = np.bincount(y, minlength=4) / len(y)
    rng = np.random.default_rng(0)
    sim = [(np.mean(p == y), mf1_present(y, p)) for p in (rng.choice(4, size=len(y), p=prior) for _ in range(10000))]
    sim = np.array(sim)
    BASE += [
        {"scope": scope, "baseline": f"majority (whole set, always S{maj})", "accuracy": mm["accuracy"], "macro_f1": mm["macro_f1"],
         "balanced_accuracy": mm["balanced_accuracy"]},
        {"scope": scope, "baseline": "majority of training fold (LOGO)", "accuracy": ml["accuracy"], "macro_f1": ml["macro_f1"],
         "balanced_accuracy": ml["balanced_accuracy"]},
        {"scope": scope, "baseline": "constant classifier (any stage)", "accuracy": None, "macro_f1": None, "balanced_accuracy": 0.25},
        {"scope": scope, "baseline": "stratified random (label prior), mean of 10000 sims", "accuracy": float(sim[:, 0].mean()),
         "macro_f1": float(sim[:, 1].mean()), "balanced_accuracy": 0.25,
         "note": f"97.5th pct acc={np.percentile(sim[:, 0], 97.5):.3f}, macroF1={np.percentile(sim[:, 1], 97.5):.3f}"},
    ]
base = pd.DataFrame(BASE)
print(base.round(3).to_string(index=False))

ERR = []
for part, scope, src in (("B", "S99", LOGO["S99"]), ("B", "S101", LOGO["S101"]), ("A", "S99", pa[pa.variant.notna()])):
    for v in ("C0", "C2", "C3"):
        s = src[src.variant == v]
        if part == "A":
            ks = {KEY(d) for d in SETS[scope]}
            s = s[[(p, dt) in ks for p, dt in zip(s.pineapple_id, s.date)]]
        e = s[s.true_stage != s.pred_stage]
        dist = (e.true_stage - e.pred_stage).abs()
        cm = cm_of(s.true_stage, s.pred_stage)
        pmax = s[["p0", "p1", "p2", "p3"]].max(axis=1)
        ok = s.true_stage == s.pred_stage
        # 描述性：最大機率區分對錯的 AUROC（Mann–Whitney）
        a_, b_ = pmax[ok].to_numpy(), pmax[~ok].to_numpy()
        auroc = float(np.mean([(x > y_) + 0.5 * (x == y_) for x in a_ for y_ in b_])) if len(a_) and len(b_) else None
        ERR.append({"part": part, "scope": scope, "variant": v, "n_days": len(s), "n_errors": len(e),
                    "S2->S0": int(cm[2, 0]), "S2->S1": int(cm[2, 1]), "S2->S3": int(cm[2, 3]), "S2 correct": int(cm[2, 2]),
                    "S3->S0": int(cm[3, 0]), "S3->S1": int(cm[3, 1]), "S3->S2": int(cm[3, 2]), "S3 correct": int(cm[3, 3]),
                    "adjacent_errors(|d|=1)": int((dist == 1).sum()), "far_errors(|d|>=2)": int((dist >= 2).sum()),
                    "share_far_among_errors": float((dist >= 2).mean()) if len(e) else None,
                    "maxprob_correct_median": float(np.median(a_)) if len(a_) else None,
                    "maxprob_correct_IQR": f"{np.percentile(a_, 25):.3f}-{np.percentile(a_, 75):.3f}" if len(a_) else "",
                    "maxprob_wrong_median": float(np.median(b_)) if len(b_) else None,
                    "maxprob_wrong_IQR": f"{np.percentile(b_, 25):.3f}-{np.percentile(b_, 75):.3f}" if len(b_) else "",
                    "maxprob_AUROC_correct_vs_wrong(descriptive)": auroc,
                    "wrong_with_maxprob>=0.6": int((b_ >= 0.6).sum())})
err = pd.DataFrame(ERR)
print(err.round(3).to_string(index=False))

# 窗口穩定性
section("Part D｜同一次記錄內的窗口穩定性（≠ 獨立重複掃描）")
WS = []
for s in STAB["S99"]:
    P = s["P"]
    st = P.argmax(axis=1)
    WS.append({"model": s["model"], "pineapple_id": s["pineapple_id"], "date": s["date"], "group": s["group"],
               "true_stage": s["true_stage"], "window_starts": " ".join(map(str, s["starts"])), "n_windows": len(st),
               "window_stages": " ".join(map(str, st)), "n_distinct_stages": len(set(st)),
               "adjacent_flip_rate": float(np.mean(st[1:] != st[:-1])) if len(st) > 1 else None,
               "agree_with_window0": float(np.mean(st == st[0])),
               "window0_correct": bool(st[0] == s["true_stage"]), "share_windows_correct": float(np.mean(st == s["true_stage"])),
               **{f"prob_std_s{k}": float(P[:, k].std()) for k in STAGES},
               "max_prob_range_any_stage": float((P.max(axis=0) - P.min(axis=0)).max())})
ws = pd.DataFrame(WS)
ws_sum = ws.groupby(["model", "true_stage"]).agg(n_days=("n_windows", "size"), mean_windows=("n_windows", "mean"),
                                                 flip_rate=("adjacent_flip_rate", "mean"),
                                                 share_days_all_windows_agree=("n_distinct_stages", lambda v: float(np.mean(v == 1))),
                                                 agree_with_w0=("agree_with_window0", "mean"),
                                                 share_windows_correct=("share_windows_correct", "mean"),
                                                 mean_max_prob_range=("max_prob_range_any_stage", "mean")).reset_index()
ws_all = ws.groupby("model").agg(n_days=("n_windows", "size"), mean_windows=("n_windows", "mean"),
                                 flip_rate=("adjacent_flip_rate", "mean"),
                                 share_days_all_windows_agree=("n_distinct_stages", lambda v: float(np.mean(v == 1))),
                                 agree_with_w0=("agree_with_window0", "mean"),
                                 share_windows_correct=("share_windows_correct", "mean"),
                                 mean_max_prob_range=("max_prob_range_any_stage", "mean")).reset_index().assign(true_stage="all")
ws_summary = pd.concat([ws_all, ws_sum], ignore_index=True)
print(ws_summary.round(3).to_string(index=False))
ws_out = pd.concat([ws_summary.assign(level="summary"), ws.assign(level="day")], ignore_index=True)
ws_out.to_csv(HERE / "window_stability.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# Part E：群組
# ═════════════════════════════════════════
section("Part E｜群組（負責人群組，不等於設備 ID）")
GROUP_ROWS = []
for part, scope, src in (("B (LOGO)", "S99", LOGO["S99"]), ("B (LOGO)", "S101", LOGO["S101"]), ("A", "S99", pa)):
    ks = {KEY(d) for d in SETS[scope]}
    for v in ("C0", "C2", "C3"):
        s = src[(src.variant == v) & [(p, dt) in ks for p, dt in zip(src.pineapple_id, src.date)]]
        for g, gg in s.groupby("group"):
            m = mets(gg.true_stage, gg.pred_stage)
            row = {"part": part, "scope": scope, "variant": v, "group": g, "n_pids": gg.pineapple_id.nunique(), **m,
                   "macro_f1_note": "only " + m["stages_present"] + " present — macro-F1/balanced acc over these stages only" if m["stages_present"].count("S") < 4 else ""}
            if g in ("A", "B"):
                sub = gg[gg.true_stage.isin([1, 2])]
                cm = confusion_matrix(sub.true_stage, sub.pred_stage, labels=STAGES)
                row["S1_vs_S2: S1->[0,1,2,3]"] = str(cm[1].tolist())
                row["S1_vs_S2: S2->[0,1,2,3]"] = str(cm[2].tolist())
            GROUP_ROWS.append(row)
        # 排除單一群組後的合併結果
        for g in sorted(s.group.unique()):
            rest = s[s.group != g]
            m = mets(rest.true_stage, rest.pred_stage)
            GROUP_ROWS.append({"part": part, "scope": scope, "variant": v, "group": f"ALL EXCEPT {g}",
                               "n_pids": rest.pineapple_id.nunique(), **m})
# Leave-one-GROUP-out
LOGRO = {}
for scope in ("S101", "S99"):
    df, _, _ = logo(SETS[scope], unit="group")
    LOGRO[scope] = df
    for v in ("C0", "C2", "C3"):
        s = df[df.variant == v]
        m = mets(s.true_stage, s.pred_stage)
        GROUP_ROWS.append({"part": "Leave-one-GROUP-out", "scope": scope, "variant": v, "group": "ALL (pooled out-of-group)",
                           "n_pids": s.pineapple_id.nunique(), **m})
        mab = mets(s[s.group.isin(["A", "B"])].true_stage, s[s.group.isin(["A", "B"])].pred_stage)
        GROUP_ROWS.append({"part": "Leave-one-GROUP-out", "scope": scope, "variant": v, "group": "A+B only",
                           "n_pids": s[s.group.isin(["A", "B"])].pineapple_id.nunique(), **mab})
pg = pd.DataFrame(GROUP_ROWS)
print(pg[["part", "scope", "variant", "group", "n_days", "stages_present", "accuracy", "macro_f1", "balanced_accuracy",
          "recall_s1", "recall_s2"]].round(3).to_string(index=False))
pg.to_csv(HERE / "per_group_metrics.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 翻轉分析
# ═════════════════════════════════════════
section("翻轉分析")
FLIP = []


def flips(part, scope, src, a, b):
    ks = {KEY(d) for d in SETS[scope]}
    A = src[(src.variant == a) & [(p, dt) in ks for p, dt in zip(src.pineapple_id, src.date)]].set_index(["pineapple_id", "date"])
    B = src[(src.variant == b) & [(p, dt) in ks for p, dt in zip(src.pineapple_id, src.date)]].set_index(["pineapple_id", "date"])
    B = B.loc[A.index]
    ca, cb = A.pred_stage == A.true_stage, B.pred_stage == B.true_stage
    ch = A.pred_stage != B.pred_stage
    cats = {"wrong->right": ~ca & cb, "right->wrong": ca & ~cb, "changed_still_wrong": ch & ~ca & ~cb,
            "unchanged_right": ~ch & ca, "unchanged_wrong": ~ch & ~ca}
    row = {"part": part, "scope": scope, "transition": f"{a}->{b}", "n_days": len(A), "n_changed": int(ch.sum()),
           **{k: int(v.sum()) for k, v in cats.items()}, "net_correct_change": int(cats["wrong->right"].sum() - cats["right->wrong"].sum())}
    for k in ("wrong->right", "right->wrong", "changed_still_wrong"):
        idx = cats[k]
        row[f"{k} by group"] = json.dumps(A[idx].group.value_counts().sort_index().to_dict())
        row[f"{k} by true stage"] = json.dumps({int(x): int(n) for x, n in A[idx].true_stage.value_counts().sort_index().items()})
        row[f"{k} by pineapple"] = json.dumps({int(x): int(n) for x, n in A[idx].reset_index().pineapple_id.value_counts().sort_index().items()})
    row["changed days (pid/date:a->b,true)"] = " ".join(f"{p}/{dt}:{A.loc[(p, dt)].pred_stage}->{B.loc[(p, dt)].pred_stage},{A.loc[(p, dt)].true_stage}"
                                                       for p, dt in A[ch].index)
    FLIP.append(row)


for part, src in (("A (deployed, in-sample)", pa), ("B (LOGO)", None)):
    for scope in ("S99", "S101", "S100"):
        s = src if src is not None else LOGO[scope]
        for a, b in (("C0", "C2"), ("C0", "C1"), ("C1", "C2"), ("C2", "C3")):
            flips(part, scope, s, a, b)
fl = pd.DataFrame(FLIP)
print(fl[["part", "scope", "transition", "n_changed", "wrong->right", "right->wrong", "changed_still_wrong", "unchanged_right",
          "unchanged_wrong", "net_correct_change"]].to_string(index=False))
fl.to_csv(HERE / "flip_analysis.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 輸出
# ═════════════════════════════════════════
section("輸出")
fmc.to_csv(HERE / "fixed_model_comparison.csv", index=False, encoding="utf-8-sig")
pa.to_csv(HERE / "fixed_model_predictions.csv", index=False, encoding="utf-8-sig")
lm.to_csv(HERE / "logo_metrics.csv", index=False, encoding="utf-8-sig")
preds = pd.concat([df.assign(scope=sc, split="leave-one-pineapple-out") for sc, df in LOGO.items()]
                  + [df.assign(scope=sc, split="leave-one-group-out") for sc, df in LOGRO.items()]
                  + [ref.assign(scope="S101", split="LOGO-Reference (Round-2 run())", variant="Reference")], ignore_index=True)
preds["in_rule_exclusion"] = [(p, dt) in RULE_EXCL for p, dt in zip(preds.pineapple_id, preds.date)]
preds.to_csv(HERE / "logo_predictions.csv", index=False, encoding="utf-8-sig")
pd.concat([f.assign(scope=sc) for sc, f in FOLDS.items()]).to_csv(HERE / "logo_folds.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(FRUIT_ROWS).to_csv(HERE / "per_fruit_metrics.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(STAGE_ROWS).to_csv(HERE / "stage_metrics.csv", index=False, encoding="utf-8-sig")
bt.to_csv(HERE / "bootstrap_ci.csv", index=False, encoding="utf-8-sig")
pd.concat([base.assign(table="baselines"), err.assign(table="error_structure"),
           seeds.assign(table="posthoc_seed_variation_S99")], ignore_index=True).to_csv(HERE / "baselines_and_errors.csv", index=False, encoding="utf-8-sig")
json.dump({k: v.tolist() for k, v in CMS.items()}, open(HERE / "confusion_matrices.json", "w", encoding="utf-8"), indent=1)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PANELS = [("A S101 C0", "Part A deployed model, S101\nC0 old features + old override\n(in-sample, NOT generalization)"),
          ("A S101 C2", "Part A deployed model, S101\nC2 fixed features, raw\n(in-sample, NOT generalization)"),
          ("LOGO S101 Reference", "LOGO-Reference (Round 2), S101\n3-window test"),
          ("LOGO S99 C0", "LOGO-C0, S99 (primary)\nold features + old override\n(diagnostic; potential leakage)"),
          ("LOGO S99 C2", "LOGO-C2, S99 (primary)\nfixed features, raw output"),
          ("LOGO S99 C3", "LOGO-C3, S99\nfixed features, 3-window mean")]
fig, axes = plt.subplots(2, 3, figsize=(16, 10.5))
lbl = [SNAME[k] for k in STAGES]
for ax, (key, title) in zip(axes.ravel(), PANELS):
    cm = CMS[key]
    ax.imshow(cm / np.maximum(cm.sum(axis=1, keepdims=True), 1), cmap="Blues", vmin=0, vmax=1)
    for i in range(4):
        for j in range(4):
            n = cm[i, j]
            rowsum = max(cm[i].sum(), 1)
            ax.text(j, i, f"{n}\n({n / rowsum:.0%})", ha="center", va="center", fontsize=9,
                    color="white" if n / rowsum > 0.55 else "black")
    acc = np.trace(cm) / cm.sum()
    ax.set_title(f"{title}\nacc={acc:.3f}, n={cm.sum()}", fontsize=9.5)
    ax.set_xticks(range(4), lbl, rotation=25, fontsize=8)
    ax.set_yticks(range(4), lbl, fontsize=8)
    ax.set_xlabel("Predicted stage", fontsize=8)
    ax.set_ylabel("True stage (manual label)", fontsize=8)
fig.suptitle("PineNose Step 2.6 — four-stage confusion matrices (rows = true stage; % of row)", fontsize=12)
fig.tight_layout()
fig.savefig(HERE / "confusion_matrices.png", dpi=130)
plt.close(fig)

# ─────────────────────────────────────────
# 安全檢查（之後）
# ─────────────────────────────────────────
section("Git／部署安全檢查")
STATE_AFTER = {str(p): git_state(p) for p in OTHER_WT}
SELF_AFTER = git_state(ROOT)
PKL_AFTER = sha_file(MODEL_PATH)
self_changes = [ln for ln in SELF_AFTER["status"].splitlines() if ln.strip()]
outside = [ln for ln in self_changes if "scanner_accuracy_validation" not in ln and "evaluation/__pycache__" not in ln]
lines = [f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"deploy_student.pkl sha256 before: {PKL_BEFORE}", f"deploy_student.pkl sha256 after : {PKL_AFTER}",
         f"expected (Step 2.5)             : {EXPECTED_SHA}",
         f"model unchanged: {PKL_BEFORE == PKL_AFTER == EXPECTED_SHA}", ""]
ok_other = True
for p in OTHER_WT:
    b, a = STATE_BEFORE[str(p)], STATE_AFTER[str(p)]
    same = b == a
    ok_other &= same
    lines += [f"{p}", f"  before: branch={b['branch']} head={b['head'][:12]} status_lines={len(b['status'].splitlines())}",
              f"  after : branch={a['branch']} head={a['head'][:12]} status_lines={len(a['status'].splitlines())}  unchanged={same}"]
lines += ["", f"this worktree: {ROOT}", f"  branch={SELF_AFTER['branch']} head={SELF_AFTER['head'][:12]}",
          f"  changed paths outside {OUT_REL} : {len(outside)}"] + [f"    {x}" for x in outside]
lines += ["", f"other worktrees unchanged: {ok_other}",
          "no model file written by this script (models exist only in memory per fold)",
          "no serial port opened, no SSH/paramiko import, no server started, no network call",
          "no push / merge performed by this script", "Raspberry Pi: NOT CONTACTED"]
(HERE / "git_safety_check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
assert PKL_BEFORE == PKL_AFTER == EXPECTED_SHA and ok_other and not outside
print(f"\n完成，耗時 {time.time() - T0:.0f}s")
sys.stdout = sys.__stdout__
LOG.close()
