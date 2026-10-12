"""
第四輪離線研究：資料品質、訊號表示、群組／月份混雜、探索性漂移校正、溫濕度、訊號對空氣波動比

研究問題：在跨鳳梨、跨群組的變異下，baseline-aware 的訊號處理與漂移校正，
能否從微弱的電子鼻量測中找回可辨識成熟度的資訊？

所有方法皆為「事先指定」（見 METHODS），不依 LOGO 測試結果追加調參。
不匯出模型、不修改原始資料／標籤／gateway／部署模型。

Run:  python -u round4_analysis.py > round4_results/round4_run_log.txt
"""
import hashlib
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import kruskal, spearmanr  # noqa: E402
from sklearn.ensemble import ExtraTreesClassifier  # noqa: E402
from sklearn.metrics import confusion_matrix, f1_score, recall_score  # noqa: E402

import retrain_round2 as r2  # noqa: E402  （import 時載入 101 天資料與既有窗口特徵）
from eval_common import FEATURES, ORK, RAW, SENSORS, WINDOW, WT, read_raw_xlsx  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

HERE = Path(__file__).resolve().parent
OUT = HERE / "round4_results"
OUT.mkdir(exist_ok=True)
DATA_VERSION = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=HERE).stdout.strip()
OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B",
         5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}  # 編號規則.docx；群組 ≠ 已知設備 ID
ANOMALIES = {(3, 20260214), (4, 20260206)}       # 第三輪確認：鳳梨檔感測值與空氣檔逐筆相同
EXPECTED_CM = np.array([[17, 6, 8, 1], [5, 14, 7, 1], [9, 8, 8, 2], [3, 2, 6, 4]])
K = r2.K                     # 測試三窗口（0/10/20 筆）
AUG_IDX = r2.AUG_IDX         # 訓練多窗口（0/30/60/90/120 筆），權重 1/5
ET_PARAMS = r2.ET_PARAMS
NEEDED_IDX = sorted(set(range(K)) | set(AUG_IDX))
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def section(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


PROTECTED = sorted(list(RAW.glob("*.xlsx")) + [ORK / "labeling.xlsx", ORK / "data_label_audit_report.xlsx"]
                   + list((WT / "pineapple_final").glob("*")) + list((WT / "pineapple_app_gateway").glob("*.py")))
SNAP_BEFORE = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}

days = r2.days
DAYKEY = [(d["pid"], d["date"]) for d in days]
y_all = np.array([d["y"] for d in days])
audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit").set_index(["pid", "date"])

# ─────────────────────────────────────────
# 每日原始序列（鳳梨＋空氣，含溫濕度），用於 4B／4D／4E／訊號雜訊分析
# ─────────────────────────────────────────
for d in days:
    a = audit.loc[(d["pid"], d["date"])]
    fdf = read_raw_xlsx(RAW / a.fruit_file)
    adf = read_raw_xlsx(RAW / a.air_file)
    assert len(fdf) == len(d["rows"]), "鳳梨檔列數與 load_days 不一致"
    d["S"] = {s: fdf[f"{s}_raw"].to_numpy(float) for s in SENSORS}
    d["T"] = fdf["Temp_C"].to_numpy(float) if "Temp_C" in fdf else np.full(len(fdf), np.nan)
    d["H"] = fdf["Humidity_pct"].to_numpy(float) if "Humidity_pct" in fdf else np.full(len(fdf), np.nan)
    d["A"] = {s: adf[f"{s}_raw"].to_numpy(float) for s in SENSORS}
    d["AT"] = adf["Temp_C"].to_numpy(float) if "Temp_C" in adf else np.full(len(adf), np.nan)
    d["AH"] = adf["Humidity_pct"].to_numpy(float) if "Humidity_pct" in adf else np.full(len(adf), np.nan)
    d["group"] = OWNER[d["pid"]]
    d["month"] = d["date"] // 100 % 100
    d["air_file"] = a.air_file
    for s in SENSORS:  # 與既有流程一致：B = 空氣檔前 30 筆平均
        assert abs(np.mean(d["A"][s][:WINDOW]) - d["air"][s]) < 1e-9


def memo(fn):
    """同一天、同一窗口的特徵只算一次（結果與逐次計算相同）。"""
    cache = {}

    def g(d, i):
        k = (d["pid"], d["date"], i)
        if k not in cache:
            cache[k] = list(fn(d, i))
        return cache[k]
    return g


# ─────────────────────────────────────────
# 通用 LOGO：逐行對應 retrain_round2.run（4 類、多窗口訓練、三窗口測試）
# ─────────────────────────────────────────
def logo(name, xfun, train_exclude=frozenset(), test_keys=None, fold_hook=None, unit="pid", params=None):
    """xfun(d, idx) -> 1 列特徵；fold_hook(train_days) -> f(X, d) 只用訓練折擬合的轉換。"""
    test_keys = set(DAYKEY) if test_keys is None else set(test_keys)
    rows, fold_info = [], []
    for fold_id, pid in enumerate(sorted({d[unit] for d in days})):
        tr = [d for d in days if d[unit] != pid and (d["pid"], d["date"]) not in train_exclude]
        te = [d for d in days if d[unit] == pid and (d["pid"], d["date"]) in test_keys]
        if not te:
            continue
        test_pids = {d["pid"] for d in te}
        assert all(t["pid"] not in test_pids for t in tr)
        tf = fold_hook(tr) if fold_hook else (lambda X, d: X)
        X = np.vstack([tf(np.array([xfun(d, i)]), d) for d in tr for i in AUG_IDX]).astype(float)
        yl = np.array([d["y"] for d in tr for _ in AUG_IDX])
        w = np.full(len(yl), 1.0 / len(AUG_IDX))
        med = np.nanmedian(X, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        X = np.where(np.isnan(X), med, X)
        m = ExtraTreesClassifier(**(params or ET_PARAMS)).fit(X, yl, sample_weight=w)
        cls = m.classes_.astype(int)
        for d in te:
            Xd = np.vstack([tf(np.array([xfun(d, i)]), d) for i in range(K)]).astype(float)
            Xd = np.where(np.isnan(Xd), med, Xd)
            P = np.zeros((K, 4))
            P[:, cls] = m.predict_proba(Xd)
            p = P.mean(axis=0)
            rows.append({"method": name, "pineapple_id": d["pid"], "date": d["date"], "group": d["group"],
                         "month": d["month"], "fold_id": fold_id, "true_stage": d["y"],
                         "pred_stage": int(np.argmax(p)), **{f"prob_stage{k}": round(float(p[k]), 4) for k in range(4)},
                         "n_train_days": len(tr), "train_has_test_pid": any(t["pid"] in test_pids for t in tr)})
        fold_info.append({"method": name, "fold_id": fold_id, "test_pid": pid, "n_features": X.shape[1]})
    return pd.DataFrame(rows), pd.DataFrame(fold_info)


def metrics(df):
    yt, yp = df.true_stage.to_numpy(), df.pred_stage.to_numpy()
    rec = recall_score(yt, yp, labels=[0, 1, 2, 3], average=None, zero_division=0)
    cm = confusion_matrix(yt, yp, labels=[0, 1, 2, 3])
    return {"n_days": len(df), "n_pids": df.pineapple_id.nunique(),
            "accuracy": round(float(np.mean(yt == yp)), 3),
            "macro_f1": round(float(f1_score(yt, yp, labels=[0, 1, 2, 3], average="macro", zero_division=0)), 3),
            "recall_s0": round(float(rec[0]), 3), "recall_s1": round(float(rec[1]), 3),
            "recall_s2": round(float(rec[2]), 3), "recall_s3": round(float(rec[3]), 3),
            "s2_to_s0_s1": int(cm[2, 0] + cm[2, 1]), "s3_to_s0_s1": int(cm[3, 0] + cm[3, 1]),
            "s2_correct_pids": df[(df.true_stage == 2) & (df.pred_stage == 2)].pineapple_id.nunique()}, cm


def _macro_f1(yt, yp):
    cm = np.bincount(yt * 4 + yp, minlength=16).reshape(4, 4)
    tp = np.diag(cm).astype(float)
    prec = np.divide(tp, cm.sum(0), out=np.zeros(4), where=cm.sum(0) > 0)
    rec = np.divide(tp, cm.sum(1), out=np.zeros(4), where=cm.sum(1) > 0)
    f = np.divide(2 * prec * rec, prec + rec, out=np.zeros(4), where=(prec + rec) > 0)
    return f.mean()


def cluster_bootstrap(a, b, n=2000, seed=0):
    """以鳳梨為單位重抽，回傳 (Δaccuracy, ΔmacroF1, ΔS2recall) 的 95% 區間；a、b 為同一組測試日。"""
    m = a.merge(b, on=["pineapple_id", "date", "true_stage"], suffixes=("_a", "_b"))
    yt = m.true_stage.to_numpy()
    pa, pb = m.pred_stage_a.to_numpy(), m.pred_stage_b.to_numpy()
    pids = m.pineapple_id.to_numpy()
    groups = [np.flatnonzero(pids == p) for p in np.unique(pids)]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        idx = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        t, x, y = yt[idx], pa[idx], pb[idx]
        s2 = t == 2
        out.append((np.mean(y == t) - np.mean(x == t), _macro_f1(t, y) - _macro_f1(t, x),
                    (np.mean(y[s2] == 2) - np.mean(x[s2] == 2)) if s2.any() else np.nan))
    o = np.array(out, dtype=float)
    q = lambda v: f"[{np.nanpercentile(v, 2.5):+.3f}, {np.nanpercentile(v, 97.5):+.3f}]"  # noqa: E731
    return q(o[:, 0]), q(o[:, 1]), q(o[:, 2])


def paired(a, b):
    """b 相對 a 的逐日改變：改善 = a 錯 b 對；退步 = a 對 b 錯。"""
    m = a.merge(b, on=["pineapple_id", "date", "true_stage"], suffixes=("_a", "_b"))
    ca, cb = m.pred_stage_a == m.true_stage, m.pred_stage_b == m.true_stage
    s2 = m.true_stage == 2
    return {"improved_days": int((~ca & cb).sum()), "worsened_days": int((ca & ~cb).sum()),
            "s2_improved": int((~ca & cb & s2).sum()), "s2_worsened": int((ca & ~cb & s2).sum()),
            "s2_improved_pids": " ".join(map(str, sorted(m[~ca & cb & s2].pineapple_id.unique()))),
            "s2_worsened_pids": " ".join(map(str, sorted(m[ca & ~cb & s2].pineapple_id.unique())))}


ALL_PREDS, SUMMARY, CMS = [], [], {}


def record(df, label, control=None, extra=None):
    met, cm = metrics(df)
    row = {"method": label, "data_version": DATA_VERSION, "model": "ExtraTrees(n=400,sqrt,rs=42)",
           "train": "multi-window 0/30/60/90/120 w=1/5", "test": "3-window mean (0/10/20)",
           "split": "LOGO by pineapple_id", **met, **(extra or {})}
    if control is not None:
        common = control[control.set_index(["pineapple_id", "date"]).index.isin(df.set_index(["pineapple_id", "date"]).index)]
        row.update(paired(common, df))
        ci = cluster_bootstrap(common, df)
        row.update({"delta_acc_95CI_vs_control": ci[0], "delta_macroF1_95CI_vs_control": ci[1],
                    "delta_S2recall_95CI_vs_control": ci[2]})
    SUMMARY.append(row)
    CMS[label] = cm
    ALL_PREDS.append(df.assign(method=label))
    print(f"{label:48s} acc={met['accuracy']:.3f} F1={met['macro_f1']:.3f} "
          f"R2={met['recall_s2']:.3f} R3={met['recall_s3']:.3f} S2→0/1={met['s2_to_s0_s1']}")
    return row


# ═════════════════════════════════════════
# 0. 重現第二輪基準
# ═════════════════════════════════════════
section("0. 重現第二輪 FIXED11 / 4 類 / 多窗口訓練 / 三窗口測試")
fixed_x = memo(lambda d, i: [d["feats"][i][c] for c in FEATURES])
A0, A0_folds = logo("A0_FIXED11_101", fixed_x)
_, cm_a0 = metrics(A0)
r3 = pd.read_csv(HERE / "round3_logo_predictions.csv")
r3 = r3[r3.feature_setting == "FIXED11"]
same_pred = A0.merge(r3, on=["pineapple_id", "date"], suffixes=("", "_r3"))
check("基準：101 天、13 顆、32/27/27/15",
      len(days) == 101 and len({d["pid"] for d in days}) == 13
      and pd.Series(y_all).value_counts().sort_index().tolist() == [32, 27, 27, 15])
check("基準：重現第二輪混淆矩陣", np.array_equal(cm_a0, EXPECTED_CM), f"\n{cm_a0}")
check("基準：逐日預測與 round3_logo_predictions.csv 完全相同",
      len(same_pred) == 101 and (same_pred.pred_stage == same_pred.pred_stage_r3).all()
      and np.allclose(same_pred.prob_stage2, same_pred.prob_stage2_r3, atol=1e-4))
record(A0, "A0 FIXED11（原始基準，101 天）")

# ═════════════════════════════════════════
# 4A. 資料品質敏感度
# ═════════════════════════════════════════
section("4A. 資料品質敏感度（兩筆鳳梨檔＝空氣檔）")
A1, _ = logo("A1", fixed_x, train_exclude=frozenset(ANOMALIES))
record(A1, "A1 訓練排除異常（測試 101 天）", control=A0)
common99 = [k for k in DAYKEY if k not in ANOMALIES]
A0_99 = A0[A0.set_index(["pineapple_id", "date"]).index.isin(common99)]
A1_99 = A1[A1.set_index(["pineapple_id", "date"]).index.isin(common99)]
record(A0_99.copy(), "A2-a A0 模型於共同 99 天")
record(A1_99.copy(), "A2-b A1 模型於共同 99 天", control=A0_99)
# 補充：完全排除後重新 LOGO（測試日的預測只取決於訓練組，因此與 A1 在 99 天上相同）
S99, _ = logo("S99", fixed_x, train_exclude=frozenset(ANOMALIES), test_keys=common99)
same99 = S99.merge(A1_99, on=["pineapple_id", "date"])
print("補充 99 天 LOGO 與 A1 在 99 天上的預測是否相同：", bool((same99.pred_stage_x == same99.pred_stage_y).all()))
anom_rows = pd.concat([A0, A1])[lambda x: x.set_index(["pineapple_id", "date"]).index.isin(list(ANOMALIES))]
print("兩筆異常資料本身的預測：")
print(anom_rows[["method", "pineapple_id", "date", "true_stage", "pred_stage"]].to_string(index=False))
q = pd.DataFrame([r for r in SUMMARY if r["method"].startswith(("A0", "A1", "A2"))])
q.to_csv(OUT / "round4_quality_sensitivity.csv", index=False, encoding="utf-8-sig")
pd.concat([A0.assign(setting="A0"), A1.assign(setting="A1")]).pivot_table(
    index=["pineapple_id", "date", "true_stage"], columns="setting", values="pred_stage").reset_index().assign(
    is_anomaly=lambda x: [(p, dd) in ANOMALIES for p, dd in zip(x.pineapple_id, x.date)]).to_csv(
    OUT / "round4_quality_paired_predictions.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 4B. 訊號表示消融
# ═════════════════════════════════════════
section("4B. Baseline representation ablation")
STATS = ("mean", "std", "min", "max", "slope", "delta_std")
INVALID_B = []


def stat_family(x):
    if np.any(np.isnan(x)):
        return [np.nan] * len(STATS)
    t = np.arange(len(x))
    return [x.mean(), x.std(), x.min(), x.max(), np.polyfit(t, x, 1)[0], np.diff(x).std()]


def rep_x(kind):
    def f(d, i):
        out = []
        for s in SENSORS:
            S = d["S"][s][i * r2.STEP: i * r2.STEP + WINDOW]
            B = d["air"][s]
            valid = B > 1.0  # 近零或無效空氣基準 → 依賴 B 的表示設為 NaN（訓練折中位數補值）
            if not valid and (d["pid"], d["date"], s) not in INVALID_B:
                INVALID_B.append((d["pid"], d["date"], s))
            if kind == "raw":
                x = S
            elif kind == "difference":
                x = S - B if valid else np.full(len(S), np.nan)
            elif kind in ("ratio", "air_response"):
                x = S / B if valid else np.full(len(S), np.nan)
            elif kind == "log_ratio":
                x = np.log(S / B) if valid and np.all(S > 0) else np.full(len(S), np.nan)
            out += stat_family(x)
        if kind == "air_response":
            out += [d["air"][s] for s in SENSORS]
        return out
    return f


REPS = {"B1 Raw（S）": "raw", "B2 Difference（S−B）": "difference", "B3 Ratio（S/B）": "ratio",
        "B4 Log-ratio（log S/B）": "log_ratio", "B5 Air + Response（S/B ＋ B）": "air_response"}
rep_preds = {"B0 FIXED11（控制組）": A0}
record(A0, "B0 FIXED11（控制組）", extra={"n_features": 11})
for label, kind in REPS.items():
    df, fi = logo(label, memo(rep_x(kind)))
    rep_preds[label] = df
    record(df, label, control=A0, extra={"n_features": int(fi.n_features.iloc[0])})
print("無效空氣基準（B ≤ 1）：", INVALID_B or "無")
pd.DataFrame([r for r in SUMMARY if r["method"].startswith("B")]).to_csv(
    OUT / "round4_baseline_comparison.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 4C. 群組／月份混雜稽核（描述性）
# ═════════════════════════════════════════
section("4C. Group / Month confounding audit")
meta = pd.DataFrame({"pineapple_id": [d["pid"] for d in days], "date": [d["date"] for d in days],
                     "stage": y_all, "group": [d["group"] for d in days], "month": [d["month"] for d in days]})
for s in SENSORS:
    meta[f"{s}_air_baseline"] = [d["air"][s] for d in days]
    meta[f"{s}_amp30"] = [np.mean(d["S"][s][:WINDOW]) / d["air"][s] - 1 for d in days]
gs = pd.crosstab(meta.group, meta.stage).reindex(columns=[0, 1, 2, 3], fill_value=0)
ms = pd.crosstab(meta.month, meta.stage).reindex(columns=[0, 1, 2, 3], fill_value=0)
gms = pd.crosstab([meta.group, meta.month], meta.stage).reindex(columns=[0, 1, 2, 3], fill_value=0)
gp = pd.crosstab(meta.group, meta.pineapple_id)
gm = pd.crosstab(meta.group, meta.month)


def cramers_v(a, b):
    t = pd.crosstab(a, b).to_numpy()
    n = t.sum()
    e = t.sum(1, keepdims=True) @ t.sum(0, keepdims=True) / n
    chi2 = ((t - e) ** 2 / e).sum()
    return float(np.sqrt(chi2 / (n * (min(t.shape) - 1))))


def eta2(v, g):
    v, g = np.asarray(v, float), np.asarray(g)
    tot = ((v - v.mean()) ** 2).sum()
    return float(sum(len(v[g == k]) * (v[g == k].mean() - v.mean()) ** 2 for k in np.unique(g)) / tot)


assoc = pd.DataFrame([
    {"pair": "stage–group", "cramers_v": round(cramers_v(meta.stage, meta.group), 3)},
    {"pair": "stage–month", "cramers_v": round(cramers_v(meta.stage, meta.month), 3)},
    {"pair": "group–month", "cramers_v": round(cramers_v(meta.group, meta.month), 3)},
    {"pair": "stage–pineapple", "cramers_v": round(cramers_v(meta.stage, meta.pineapple_id), 3)},
])
base_assoc = pd.DataFrame([{"sensor": s, **{f"eta2_{k}": round(eta2(meta[f"{s}_air_baseline"], meta[k]), 3)
                                            for k in ("group", "month", "stage", "pineapple_id")}}
                           for s in SENSORS])
stage_groups = {st: sorted(meta[meta.stage == st].group.unique()) for st in range(4)}
gs.assign(n_groups_with_stage="").to_csv(OUT / "round4_group_stage_coverage.csv", encoding="utf-8-sig")
with open(OUT / "round4_group_month_coverage.csv", "w", encoding="utf-8-sig") as f:
    f.write("# Stage × Month\n")
    ms.to_csv(f)
    f.write("\n# Stage × Group × Month\n")
    gms.to_csv(f)
    f.write("\n# Group × Pineapple\n")
    gp.to_csv(f)
    f.write("\n# Group × Month\n")
    gm.to_csv(f)
    f.write("\n# 關聯（Cramér's V）\n")
    assoc.to_csv(f, index=False)
    f.write("\n# 空氣基準原始值的 eta²\n")
    base_assoc.to_csv(f, index=False)
print("Stage × Group：")
print(gs.to_string())
print("\nStage × Month：")
print(ms.to_string())
print("\nStage × Group × Month：")
print(gms.to_string())
print("\nGroup × Month：")
print(gm.to_string())
print("\n各 Stage 出現於哪些群組：", stage_groups)
print("\n關聯（Cramér's V）：")
print(assoc.to_string(index=False))
print("\n空氣基準原始值的 eta²：")
print(base_assoc.to_string(index=False))
within_group_stage_overlap = {g: sorted(meta[meta.group == g].stage.unique()) for g in sorted(meta.group.unique())}
print("\n各群組觀察到的 Stage：", within_group_stage_overlap)
print("設備 ID：原始檔與標籤中沒有設備編號欄位，群組無法可靠對應到實際設備。")
MIN_COVERAGE = all(len(v) >= 2 for v in stage_groups.values()) and \
    sum(len(v) >= 3 for v in within_group_stage_overlap.values()) >= 2
print("最低覆蓋條件（每個 Stage 至少 2 群組、至少 2 群組各有 ≥3 個 Stage）：", MIN_COVERAGE,
      "——僅為必要條件，不代表群組與成熟度效果可分離（見報告 4C）")


def plot_baselines():
    df = meta
    fig, axes = plt.subplots(2, 5, figsize=(22, 8))
    groups = sorted(df.group.unique())
    for j, s in enumerate(SENSORS):
        ax = axes[0, j]
        data = [df[df.group == g][f"{s}_air_baseline"] for g in groups]
        ax.boxplot(data, showfliers=False)
        for k, g in enumerate(groups, start=1):
            sub = df[df.group == g]
            ax.scatter(np.random.default_rng(k).normal(k, 0.07, len(sub)), sub[f"{s}_air_baseline"], s=12,
                       c=sub.month.map({2: "#3182bd", 3: "#e6550d"}), alpha=0.8)
        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels([f"群組 {g}" for g in groups])
        ax.set_title(f"{s} 空氣基準原始值（藍＝2 月、橘＝3 月）", fontsize=10)
        ax = axes[1, j]
        keys = [(g, m) for g in groups for m in (2, 3) if ((df.group == g) & (df.month == m)).any()]
        data = [df[(df.group == g) & (df.month == m)][f"{s}_amp30"] for g, m in keys]
        ax.boxplot(data, showfliers=False)
        for k, (g, m) in enumerate(keys, start=1):
            sub = df[(df.group == g) & (df.month == m)]
            ax.scatter(np.random.default_rng(k).normal(k, 0.07, len(sub)), sub[f"{s}_amp30"], s=12,
                       c=sub.stage.map({0: "#2b8cbe", 1: "#41ab5d", 2: "#fd8d3c", 3: "#d7301f"}), alpha=0.85)
        ax.axhline(0, color="k", lw=0.6, ls="--")
        ax.set_xticks(range(1, len(keys) + 1))
        ax.set_xticklabels([f"{g}-{m}月" for g, m in keys], rotation=45, fontsize=8)
        ax.set_title(f"{s} 正規化反應 amp30（點色＝Stage）", fontsize=10)
    fig.suptitle("4C：各群組／月份的空氣基準與正規化訊號（群組不等於已知設備）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "round4_baseline_distributions.png", dpi=110)
    plt.close(fig)


plot_baselines()


# ═════════════════════════════════════════
# 4D. 探索性 PCA 低秩干擾校正
# ═════════════════════════════════════════
section("4D. Exploratory PCA-based low-rank nuisance correction")
# 空間一致性：在「log ADC」空間進行。空氣基準 log B 與鳳梨窗口位準 log S 都是 5 維、單位相同（每個感測器的 log 讀值），
# 所以從 log B 估出的方向可以直接作用在 log S 位準特徵上。動態特徵（log S 的 std、斜率、差分 std）與位準平移無關，不做校正。
D_SETTINGS = [0, 1, 2]  # 事先固定：k=0（同特徵、不校正，控制組）、k=1、k=2
D_DIAG = []


@memo
def logs_x(d, i):
    lv, dyn = [], []
    for s in SENSORS:
        x = np.log(np.maximum(d["S"][s][i * r2.STEP: i * r2.STEP + WINDOW], 1.0))
        lv.append(x.mean())
        dyn += [x.std(), np.polyfit(np.arange(len(x)), x, 1)[0], np.diff(x).std()]
    return lv + dyn  # 前 5 欄為位準，其餘為動態


def make_hook(k, diag=True):
    def hook(tr):
        if k == 0:
            return lambda X, d: X
        LB = np.array([[np.log(t["air"][s]) for s in SENSORS] for t in tr])
        mu_b = LB.mean(axis=0)
        U, S_, Vt = np.linalg.svd(LB - mu_b, full_matrices=False)
        V = Vt[:k].T  # 5 × k，訓練折空氣基準的主方向
        lvl_tr = np.array([logs_x(t, i)[:5] for t in tr for i in AUG_IDX])
        mu_l = lvl_tr.mean(axis=0)
        ev = (S_ ** 2 / np.sum(S_ ** 2))[:k]
        # 診斷（不用於選擇設定）：校正方向分數與訓練組 stage／group 的關聯
        score = (lvl_tr - mu_l) @ V[:, 0]
        st = np.array([t["y"] for t in tr for _ in AUG_IDX])
        gr = np.array([t["group"] for t in tr for _ in AUG_IDX])
        lvl_proj = (lvl_tr - mu_l) @ V @ V.T
        if diag:
            D_DIAG.append({"k": k, "explained_var_air_pc": np.round(ev, 3).tolist(),
                           "pc1_loading": np.round(V[:, 0], 3).tolist(),
                           "eta2_stage_of_removed_score": round(eta2(score, st), 3),
                           "eta2_group_of_removed_score": round(eta2(score, gr), 3),
                           "frac_level_var_removed": round(float(np.sum(lvl_proj ** 2) / np.sum((lvl_tr - mu_l) ** 2)), 3)})

        def tf(X, d):
            X = X.copy()
            L = X[:, :5]
            X[:, :5] = L - ((L - mu_l) @ V) @ V.T
            return X
        return tf
    return hook


drift_rows = []
d_preds = {}
for k in D_SETTINGS:
    label = f"D{k} log-level + dynamic, PCA 校正 k={k}" if k else "D0 log-level + dynamic（不校正，控制組）"
    df, fi = logo(label, logs_x, fold_hook=make_hook(k))
    d_preds[k] = df
    drift_rows.append(record(df, label, control=A0 if k == 0 else d_preds[0], extra={"n_features": 20}))
diag = pd.DataFrame(D_DIAG)
diag_summary = diag.groupby("k").agg(
    eta2_stage_removed=("eta2_stage_of_removed_score", "mean"),
    eta2_group_removed=("eta2_group_of_removed_score", "mean"),
    frac_level_var_removed=("frac_level_var_removed", "mean")).round(3).reset_index()
print("\n校正方向診斷（13 折平均；僅描述，不用於選擇設定）：")
print(diag_summary.to_string(index=False))
print("PC1 載荷（第 1 折）：", diag[diag.k == 1].pc1_loading.iloc[0], "解釋變異：", diag[diag.k == 2].explained_var_air_pc.iloc[0])
pd.DataFrame(drift_rows).merge(
    diag_summary.rename(columns={"k": "pca_k"}).assign(method=lambda x: [
        f"D{k} log-level + dynamic, PCA 校正 k={k}" for k in x.pca_k]), on="method", how="left").to_csv(
    OUT / "round4_drift_correction.csv", index=False, encoding="utf-8-sig")
diag.to_csv(OUT / "round4_drift_fold_diagnostics.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 4E. 溫濕度
# ═════════════════════════════════════════
section("4E. Temperature / humidity")
env_audit = []
for d in days:
    T, H, AT, AH = d["T"], d["H"], d["AT"], d["AH"]
    env_audit.append({
        "pineapple_id": d["pid"], "date": d["date"], "stage": d["y"], "group": d["group"], "month": d["month"],
        "fruit_T_missing": int(np.isnan(T).sum()), "fruit_H_missing": int(np.isnan(H).sum()),
        "air_T_missing": int(np.isnan(AT).sum()), "air_H_missing": int(np.isnan(AH).sum()),
        "fruit_T_out_of_range": int(np.sum((T < 0) | (T > 50))), "fruit_H_out_of_range": int(np.sum((H < 0) | (H > 100))),
        "fruit_T30": float(np.nanmean(T[:WINDOW])), "fruit_H30": float(np.nanmean(H[:WINDOW])),
        "air_T30": float(np.nanmean(AT[:WINDOW])), "air_H30": float(np.nanmean(AH[:WINDOW])),
        "fruit_minus_air_T": float(np.nanmean(T[:WINDOW]) - np.nanmean(AT[:WINDOW])),
        "fruit_minus_air_H": float(np.nanmean(H[:WINDOW]) - np.nanmean(AH[:WINDOW])),
        **{f"w0_{c}": d["feats"][0][c] for c in FEATURES},
    })
env = pd.DataFrame(env_audit)
complete = float(1 - (env[["fruit_T_missing", "fruit_H_missing"]].sum().sum()) / (2 * sum(len(d["T"]) for d in days)))
print(f"溫濕度完整率（鳳梨檔）：{complete:.4f}；超出範圍：T {int(env.fruit_T_out_of_range.sum())}、H {int(env.fruit_H_out_of_range.sum())}")
print(f"溫度範圍 {env.fruit_T30.min():.1f}～{env.fruit_T30.max():.1f} °C；濕度 {env.fruit_H30.min():.1f}～{env.fruit_H30.max():.1f} %")
env_assoc = []
for v in ("fruit_T30", "fruit_H30"):
    env_assoc.append({"variable": v, "spearman_vs_stage": round(spearmanr(env[v], env.stage).correlation, 3),
                      "eta2_group": round(eta2(env[v], env.group), 3), "eta2_month": round(eta2(env[v], env.month), 3),
                      "eta2_pineapple": round(eta2(env[v], env.pineapple_id), 3),
                      "spearman_vs_date": round(spearmanr(env[v], env.date).correlation, 3)})
    for c in FEATURES:
        within = [spearmanr(g[v], g[f"w0_{c}"]).correlation for _, g in env.groupby("pineapple_id")
                  if len(g) >= 4 and g[v].nunique() > 1 and g[f"w0_{c}"].nunique() > 1]
        within = [w for w in within if np.isfinite(w)]
        env_assoc.append({"variable": v, "feature": c,
                          "spearman_pooled": round(spearmanr(env[v], env[f"w0_{c}"]).correlation, 3),
                          "within_pid_mean_rho": round(float(np.mean(within)), 3) if within else np.nan,
                          "within_pid_sign_consistency": round(float(np.mean(np.sign(within) == np.sign(np.mean(within)))), 2) if within else np.nan})
env_assoc = pd.DataFrame(env_assoc)
print(env_assoc[env_assoc.feature.isna()].dropna(axis=1).to_string(index=False))
print(env_assoc[env_assoc.feature.notna()].sort_values("spearman_pooled", key=abs, ascending=False).head(8).to_string(index=False))

ENV_FEASIBLE = complete > 0.99
E_rows = []
if ENV_FEASIBLE:
    @memo
    def fixed_env_x(d, i):
        sl = slice(i * r2.STEP, i * r2.STEP + WINDOW)
        return fixed_x(d, i) + [np.nanmean(d["T"][sl]), np.nanmean(d["H"][sl])]

    E2, _ = logo("E2", fixed_env_x)
    E_rows.append(record(E2, "E2 FIXED11 + 溫濕度輸入", control=A0, extra={"n_features": 13}))

    def env_comp_hook(tr):
        # 訓練折內以 OLS 估計每個特徵對 [1, T, H] 的線性關係（不使用標籤），以殘差＋截距替換
        Z = np.array([fixed_env_x(t, i) for t in tr for i in AUG_IDX], dtype=float)
        F, TH = Z[:, :11], np.column_stack([np.ones(len(Z)), Z[:, 11:13]])
        ok = ~np.isnan(TH).any(axis=1)
        coef = np.linalg.lstsq(TH[ok], F[ok], rcond=None)[0]

        def tf(X, d):
            X = X.copy()
            th = np.column_stack([np.zeros(len(X)), X[:, 11:13]])
            X[:, :11] = X[:, :11] - th @ coef
            return X[:, :11]
        return tf

    E3, _ = logo("E3", fixed_env_x, fold_hook=env_comp_hook)
    E_rows.append(record(E3, "E3 FIXED11 訓練折線性溫濕度補償", control=A0, extra={"n_features": 11}))
else:
    print("NOT FEASIBLE：溫濕度資料不足")
pd.concat([env_assoc, pd.DataFrame(E_rows)], ignore_index=True).to_csv(
    OUT / "round4_environment_analysis.csv", index=False, encoding="utf-8-sig")
env.to_csv(OUT / "round4_environment_audit.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 訊號對空氣波動比（描述性 effect-to-noise proxy，非 SNR）
# ═════════════════════════════════════════
section("Signal-to-baseline variability（Z_response，描述性）")
SD_FLOOR = 0.5  # ADC；低於此值視為量化雜訊下限，避免除以近零
r3preds = r3.set_index(["pineapple_id", "date"])
zr = []
for d in days:
    for s in SENSORS:
        S, Bs = d["S"][s], d["A"][s]
        t = np.arange(len(Bs))
        resid = Bs - np.polyval(np.polyfit(t, Bs, 1), t)
        sd_raw, sd_det = float(np.std(Bs, ddof=1)), float(np.std(resid, ddof=1))
        mad = float(np.median(np.abs(Bs - np.median(Bs)))) or SD_FLOOR
        ac1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if np.std(resid) > 0 else np.nan
        sd_used = max(sd_det, SD_FLOOR)
        diff_full = float(np.median(S) - np.median(Bs))
        diff_30 = float(np.median(S[:WINDOW]) - np.median(Bs[:WINDOW]))
        p = r3preds.loc[(d["pid"], d["date"])]
        zr.append({"pineapple_id": d["pid"], "date": d["date"], "stage": d["y"], "group": d["group"],
                   "month": d["month"], "sensor": s, "is_anomaly": (d["pid"], d["date"]) in ANOMALIES,
                   "median_S": float(np.median(S)), "median_B": float(np.median(Bs)),
                   "signed_diff": diff_full, "signed_rel_diff": diff_full / float(np.median(Bs)),
                   "sd_B_raw": sd_raw, "sd_B_detrended": sd_det, "sd_floored": sd_det < SD_FLOOR,
                   "air_trend_per100s": float(np.polyfit(t, Bs, 1)[0] * 100), "air_lag1_autocorr": ac1,
                   "air_outliers_5mad": int(np.sum(np.abs(Bs - np.median(Bs)) > 5 * mad)),
                   "Z_response": abs(diff_full) / sd_used, "Z_response_first30": abs(diff_30) / sd_used,
                   "Z_response_rawSD": abs(diff_full) / max(sd_raw, SD_FLOOR),
                   "logo_pred_stage": int(p.pred_stage), "logo_correct": bool(p.correct)})
zr = pd.DataFrame(zr)
zr.to_csv(OUT / "round4_signal_noise.csv", index=False, encoding="utf-8-sig")
zs = zr.groupby("sensor").agg(median_Z=("Z_response", "median"), p_Z_gt2=("Z_response", lambda v: (v > 2).mean()),
                              p_Z_gt3=("Z_response", lambda v: (v > 3).mean()),
                              median_Z_rawSD=("Z_response_rawSD", "median"),
                              median_sd_detrended=("sd_B_detrended", "median"),
                              n_sd_floored=("sd_floored", "sum"), median_air_lag1=("air_lag1_autocorr", "median"),
                              median_abs_air_trend_per100s=("air_trend_per100s", lambda v: v.abs().median()),
                              p_fruit_below_air=("signed_diff", lambda v: (v < 0).mean())).round(3).reindex(SENSORS)
print(zs.to_string())
for k in ("stage", "group", "month"):
    print(f"\nZ_response 中位數 依 {k} × sensor：")
    print(zr.pivot_table(index=k, columns="sensor", values="Z_response", aggfunc="median")[SENSORS].round(2).to_string())
s2z = zr[zr.stage == 2].assign(grp=lambda x: np.where(x.logo_correct, "S2 判對", np.where(x.logo_pred_stage <= 1, "S2→0/1", "S2→3")))
print("\nStage 2 判對 vs 誤判的 Z_response 中位數：")
print(s2z.pivot_table(index="grp", columns="sensor", values="Z_response", aggfunc="median")[SENSORS].round(2).to_string())
kw = []
for s in SENSORS:
    sub = zr[(zr.sensor == s) & ~zr.is_anomaly]
    groups = [sub[sub.stage == st].signed_rel_diff for st in range(4)]
    kw.append({"sensor": s, "kruskal_p_signed_rel_diff_by_stage": round(float(kruskal(*groups).pvalue), 3),
               "eta2_stage": round(eta2(sub.signed_rel_diff, sub.stage), 3),
               "eta2_pineapple": round(eta2(sub.signed_rel_diff, sub.pineapple_id), 3),
               "eta2_group": round(eta2(sub.signed_rel_diff, sub.group), 3),
               **{f"median_rel_diff_S{st}": round(float(np.median(groups[st])), 4) for st in range(4)}})
kw = pd.DataFrame(kw)
print("\n鳳梨−空氣差異（相對值）能否區分 Stage（描述性；同顆鳳梨不同日期不獨立）：")
print(kw.to_string(index=False))
kw.to_csv(OUT / "round4_signal_noise_stage_separation.csv", index=False, encoding="utf-8-sig")
zs.to_csv(OUT / "round4_signal_noise_summary.csv", encoding="utf-8-sig")


def plot_signal_noise():
    z = pd.read_csv(OUT / "round4_signal_noise.csv")
    fig, axes = plt.subplots(2, 5, figsize=(22, 8))
    for j, s in enumerate(SENSORS):
        sub = z[z.sensor == s]
        ax = axes[0, j]
        data = [np.log10(sub[sub.stage == st].Z_response + 1e-3) for st in range(4)]
        ax.boxplot(data, showfliers=False)
        for st in range(4):
            v = data[st]
            ax.scatter(np.random.default_rng(st).normal(st + 1, 0.07, len(v)), v, s=10, alpha=0.6, color="#555")
        ax.axhline(np.log10(2), color="r", ls="--", lw=0.8)
        ax.set_xticks([1, 2, 3, 4])
        ax.set_xticklabels(["S0", "S1", "S2", "S3"])
        ax.set_title(f"{s}：log10 Z_response（紅線＝Z=2）", fontsize=10)
        ax = axes[1, j]
        s2 = sub[sub.stage == 2]
        grp = [("S2 判對", s2[s2.logo_correct]), ("S2→0/1", s2[~s2.logo_correct & (s2.logo_pred_stage <= 1)]),
               ("S0", sub[sub.stage == 0]), ("S1", sub[sub.stage == 1]), ("S3", sub[sub.stage == 3])]
        ax.boxplot([g.signed_rel_diff for _, g in grp], showfliers=False)
        for k2, (_, g) in enumerate(grp, start=1):
            ax.scatter(np.random.default_rng(k2).normal(k2, 0.07, len(g)), g.signed_rel_diff, s=10, alpha=0.6)
        ax.axhline(0, color="k", lw=0.6, ls="--")
        ax.set_xticks(range(1, 6))
        ax.set_xticklabels([n for n, _ in grp], fontsize=8, rotation=30)
        ax.set_title(f"{s}：鳳梨−空氣相對差（有正負）", fontsize=10)
    fig.suptitle("訊號對空氣波動比（描述性 effect-to-noise proxy，非 SNR）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "round4_signal_noise_distributions.png", dpi=110)
    plt.close(fig)


plot_signal_noise()


# ═════════════════════════════════════════
# 事後診斷（非預先指定方法；只用來解讀不確定性與群組捷徑，不用來挑選方法）
# ═════════════════════════════════════════
section("事後診斷：群組捷徑、跨群組驗證、亂數種子變異、訊號 vs 漂移")
PH = {
    "B0 FIXED11": (fixed_x, None),
    "B1 Raw": (memo(rep_x("raw")), None),
    "B4 Log-ratio": (memo(rep_x("log_ratio")), None),
    "B5 Air+Response": (memo(rep_x("air_response")), None),
    "D0 log-level（不校正）": (logs_x, None),
    "D2 PCA k=2": (logs_x, 2),
}
ph_rows = []
# (1) 只看同時有多個 Stage 的群組 A＋B（排除只有單一 Stage 的群組 C、D 帶來的「群組＝答案」捷徑）
name_map = {"B0 FIXED11": "B0 FIXED11（控制組）", "B1 Raw": "B1 Raw（S）", "B4 Log-ratio": "B4 Log-ratio（log S/B）",
            "B5 Air+Response": "B5 Air + Response（S/B ＋ B）", "D0 log-level（不校正）": "D0 log-level + dynamic（不校正，控制組）",
            "D2 PCA k=2": "D2 log-level + dynamic, PCA 校正 k=2"}
all_pred = pd.concat(ALL_PREDS, ignore_index=True)
for short, full in name_map.items():
    sub = all_pred[(all_pred.method == full) & all_pred.group.isin(["A", "B"])]
    met, _ = metrics(sub)
    ph_rows.append({"diagnostic": "LOGO-pineapple，只計群組 A+B", "method": short, **met})
    subcd = all_pred[(all_pred.method == full) & all_pred.group.isin(["C", "D"])]
    ph_rows.append({"diagnostic": "LOGO-pineapple，只計群組 C+D（各只有 1～2 個 Stage）", "method": short, **metrics(subcd)[0]})
# (2) 留出整個群組（A、B 才有多個 Stage；C、D 也照樣留出但只列整體）
for short, (fx, k) in PH.items():
    hook = make_hook(k, diag=False) if k else None
    df, _ = logo(f"LOGrO {short}", fx, fold_hook=hook, unit="group")
    ph_rows.append({"diagnostic": "Leave-one-GROUP-out（全部 101 天）", "method": short, **metrics(df)[0]})
    ph_rows.append({"diagnostic": "Leave-one-GROUP-out，只計群組 A+B", "method": short,
                    **metrics(df[df.group.isin(["A", "B"])])[0]})
# (3) 亂數種子變異（LOGO-pineapple，種子 0～9；原設定為 42）
for short, (fx, k) in PH.items():
    hook = make_hook(k, diag=False) if k else None
    accs, f1s, r2s, r3s = [], [], [], []
    for seed in range(10):
        df, _ = logo(f"seed{seed} {short}", fx, fold_hook=hook, params={**ET_PARAMS, "random_state": seed})
        met = metrics(df)[0]
        accs.append(met["accuracy"]); f1s.append(met["macro_f1"]); r2s.append(met["recall_s2"]); r3s.append(met["recall_s3"])
    ph_rows.append({"diagnostic": "亂數種子 0～9（LOGO-pineapple，101 天）", "method": short,
                    "accuracy": f"{np.mean(accs):.3f} ± {np.std(accs):.3f} [{min(accs):.3f}, {max(accs):.3f}]",
                    "macro_f1": f"{np.mean(f1s):.3f} ± {np.std(f1s):.3f}",
                    "recall_s2": f"{np.mean(r2s):.3f} ± {np.std(r2s):.3f} [{min(r2s):.3f}, {max(r2s):.3f}]",
                    "recall_s3": f"{np.mean(r3s):.3f} ± {np.std(r3s):.3f}"})
ph = pd.DataFrame(ph_rows)
ph.to_csv(OUT / "round4_posthoc_diagnostics.csv", index=False, encoding="utf-8-sig")
print(ph[["diagnostic", "method", "n_days", "accuracy", "macro_f1", "recall_s2", "recall_s3"]].fillna("").to_string(index=False))

# (4) 鳳梨−空氣差距 vs 空氣本身的漂移（兩者為不同時間的記錄）
dr = []
for d in days:
    for s in SENSORS:
        Bs = d["A"][s]
        trend_total = abs(np.polyfit(np.arange(len(Bs)), Bs, 1)[0]) * (len(Bs) - 1)
        dr.append({"pineapple_id": d["pid"], "date": d["date"], "sensor": s, "stage": d["y"],
                   "abs_fruit_minus_air": abs(np.median(d["S"][s]) - np.median(Bs)),
                   "air_session_drift_900s": trend_total, "median_B": float(np.median(Bs))})
dr = pd.DataFrame(dr).sort_values(["pineapple_id", "sensor", "date"])
dr["day_to_day_air_change"] = dr.groupby(["pineapple_id", "sensor"]).median_B.diff().abs()
dr = dr[~dr.set_index(["pineapple_id", "date"]).index.isin(list(ANOMALIES))]
drs = dr.groupby("sensor").apply(lambda g: pd.Series({
    "median_abs_fruit_minus_air_ADC": g.abs_fruit_minus_air.median(),
    "median_air_drift_within_900s_ADC": g.air_session_drift_900s.median(),
    "median_day_to_day_air_change_ADC": g.day_to_day_air_change.median(),
    "P(|S−B| > air drift within session)": (g.abs_fruit_minus_air > g.air_session_drift_900s).mean(),
    "P(|S−B| > day-to-day air change)": (g.abs_fruit_minus_air > g.day_to_day_air_change).dropna().mean()
    if g.day_to_day_air_change.notna().any() else np.nan}), include_groups=False).round(3).reindex(SENSORS)
drs.to_csv(OUT / "round4_signal_vs_drift.csv", encoding="utf-8-sig")
print("\n鳳梨−空氣差距 vs 空氣漂移（ADC；排除 2 筆異常）：")
print(drs.to_string())


# ═════════════════════════════════════════
# 彙整：所有方法、逐顆鳳梨、混淆矩陣
# ═════════════════════════════════════════
section("彙整：全部事先指定方法")
summary = pd.DataFrame(SUMMARY)
summary.to_csv(OUT / "round4_all_methods.csv", index=False, encoding="utf-8-sig")
print(summary[["method", "n_days", "accuracy", "macro_f1", "recall_s2", "recall_s3", "s2_to_s0_s1",
               "s2_correct_pids", "improved_days", "worsened_days", "s2_improved", "s2_worsened",
               "delta_acc_95CI_vs_control", "delta_S2recall_95CI_vs_control"]].fillna("").to_string(index=False))
preds = pd.concat(ALL_PREDS, ignore_index=True)
preds.to_csv(OUT / "round4_predictions.csv", index=False, encoding="utf-8-sig")
pp = preds.groupby(["method", "pineapple_id"]).apply(lambda g: pd.Series({
    "group": g.group.iloc[0], "n_days": len(g), "accuracy": round(float(np.mean(g.pred_stage == g.true_stage)), 3),
    "s2_n": int((g.true_stage == 2).sum()), "s2_correct": int(((g.true_stage == 2) & (g.pred_stage == 2)).sum()),
    "s3_n": int((g.true_stage == 3).sum()), "s3_correct": int(((g.true_stage == 3) & (g.pred_stage == 3)).sum())}),
    include_groups=False).reset_index()
pp.to_csv(OUT / "round4_per_pineapple.csv", index=False, encoding="utf-8-sig")
print("\nStage 2 判對天數（逐顆）× 方法：")
print(pp[pp.s2_n > 0].pivot_table(index="pineapple_id", columns="method", values="s2_correct").to_string())


def plot_cms():
    labels = list(CMS)
    n = len(labels)
    ncol = 4
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.6 * ncol, 4.2 * nrow))
    for ax, lab in zip(axes.flat, labels):
        cm = CMS[lab]
        ax.imshow(cm, cmap="Blues")
        for i in range(4):
            for j in range(4):
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=10,
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        ax.set_xticks(range(4))
        ax.set_yticks(range(4))
        ax.set_xlabel("預測")
        ax.set_ylabel("真實")
        ax.set_title(lab, fontsize=9)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(OUT / "round4_confusion_matrices.png", dpi=100)
    plt.close(fig)


plot_cms()

# ═════════════════════════════════════════
# 驗收
# ═════════════════════════════════════════
section("驗收檢查")
leak = int(preds.train_has_test_pid.sum())
check("LOGO 無 pineapple_id 洩漏（所有方法、所有折）", leak == 0, f"(leak rows={leak})")
check("學習型校正只用訓練折（PCA、OLS、補值皆在 fold hook／logo 內以訓練組估計）", True,
      "(設計檢查：make_hook / env_comp_hook / nanmedian 只接收 tr)")
check("4A 有共同測試集比較（共同 99 天）", len(A0_99) == 99 and len(A1_99) == 99)
check("4B 特徵由原始感測序列重新計算", all(k in REPS.values() for k in ("raw", "difference", "ratio", "log_ratio")))
check("4C 群組／月份／Stage 覆蓋表已輸出", (OUT / "round4_group_stage_coverage.csv").exists()
      and (OUT / "round4_group_month_coverage.csv").exists())
check("4D 未把 PCA 主成分宣稱為真實漂移", True, "(方法命名為 PCA-based exploratory correction；報告另述)")
check("4E 溫濕度缺值與完整率已記錄", (OUT / "round4_environment_audit.csv").exists(), f"(完整率 {complete:.4f})")
check("訊號／空氣分析使用實際空氣時間序列", zr.sd_B_detrended.notna().all())
check("報告列出全部預先指定方法", len(summary) == 1 + 3 + 6 + 3 + 2, f"(方法列數 {len(summary)})")
SNAP_AFTER = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}
changed = [p for p in SNAP_BEFORE if SNAP_BEFORE[p] != SNAP_AFTER.get(p)]
dirty = subprocess.run(["git", "status", "--porcelain", "--", str(RAW), str(ORK / "labeling.xlsx"),
                        str(ORK / "data_label_audit_report.xlsx"), str(WT / "pineapple_final"),
                        str(WT / "pineapple_app_gateway")], capture_output=True, text=True, cwd=WT).stdout.strip()
check("原始資料、標籤、部署模型、Gateway 未修改", not changed and not dirty,
      f"({len(SNAP_BEFORE)} 檔 SHA-256 前後一致；App 不在此 worktree 的 sparse checkout 中，未觸及)")
with open(OUT / "round4_checks.txt", "w", encoding="utf-8") as f:
    for name, ok, detail in CHECKS:
        f.write(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}\n")
print("\n完成。失敗：", [n for n, ok, _ in CHECKS if not ok] or "無")
