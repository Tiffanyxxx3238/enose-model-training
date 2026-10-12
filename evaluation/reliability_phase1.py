"""
Reliability Study — Phase 1: Confidence–Error Separability Audit

問題：PineNose 對「沒看過的鳳梨」判錯時，現有的預測機率能不能辨識出這個錯誤風險？

只讀取既有的 LOGO out-of-fold 預測（round3_logo_predictions.csv，FIXED11），
不訓練模型、不選門檻、不做拒判（Phase 2 未批准）。

Run:  python -u reliability_phase1.py > reliability_phase1_results/phase1_run_log.txt
"""
import hashlib
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import confusion_matrix, f1_score, recall_score, roc_auc_score  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

HERE = Path(__file__).resolve().parent
WT = HERE.parent
OUT = HERE / "reliability_phase1_results"
OUT.mkdir(exist_ok=True)
SRC = HERE / "round3_logo_predictions.csv"
SEED = 20261012
N_BOOT = 2000
HC_CUTS = [0.70, 0.80, 0.90]  # 事先固定的描述性切點；不是拒判門檻
# 群組定義：data/raw/編號規則.docx（與 round3_diagnosis.py、round4_analysis.py 相同）；群組 ≠ 已確認的設備 ID
OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B",
         5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}
EXPECTED_CM = np.array([[17, 6, 8, 1], [5, 14, 7, 1], [9, 8, 8, 2], [3, 2, 6, 4]])
RISKS = {"1 - max_probability": "error_score_maxprob", "1 - top2_margin": "error_score_margin",
         "normalized_entropy": "normalized_entropy"}
CHECKS = []


def check(name, status, detail=""):
    assert status in ("PASS", "FAIL", "NOT AVAILABLE", "NOT APPLICABLE")
    CHECKS.append((name, status, detail))
    print(f"[{status}] {name} {detail}")


def section(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


# 受保護檔案快照（前四輪程式與輸出、原始資料、標籤、部署模型、gateway）
PROTECTED = sorted(
    [p for p in HERE.glob("*") if p.is_file() and not p.name.startswith("reliability_phase1")]
    + [p for d in ("round3_results", "round4_results") for p in (HERE / d).glob("*")]
    + list((WT / "enose_model_training/orkspace/data/raw").glob("*.xlsx"))
    + [WT / "enose_model_training/orkspace/labeling.xlsx", WT / "enose_model_training/orkspace/data_label_audit_report.xlsx"]
    + list((WT / "pineapple_final").glob("*")) + list((WT / "pineapple_app_gateway").glob("*.py")))
SNAP = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}

# ═════════════════════════════════════════
# 5. 資料稽核
# ═════════════════════════════════════════
section("5. Mandatory data audit")
raw = pd.read_csv(SRC)
print("檔案：", SRC.name, "；欄位：", raw.columns.tolist())
print("feature_setting：", raw.feature_setting.value_counts().to_dict())
df = raw[raw.feature_setting == "FIXED11"].copy().reset_index(drop=True)
P = df[[f"prob_stage{k}" for k in range(4)]].to_numpy(float)

check("5.1 101 天", "PASS" if len(df) == 101 else "FAIL", f"(n={len(df)})")
check("5.1 13 顆鳳梨", "PASS" if df.pineapple_id.nunique() == 13 else "FAIL", f"(n={df.pineapple_id.nunique()})")
dup = int(df.duplicated(["pineapple_id", "date"]).sum())
check("5.1 (pineapple_id, date) 唯一", "PASS" if dup == 0 else "FAIL", f"(dup={dup})")
counts = df.true_stage.value_counts().sort_index().tolist()
check("5.1 Stage 32/27/27/15", "PASS" if counts == [32, 27, 27, 15] else "FAIL", f"({counts})")

prov_ok = (set(df.train_mode) == {"multi"} and set(df.test_mode) == {"three_window"}
           and df.model_config.str.contains("LOGO=pineapple_id").all()
           and df.model_config.str.contains(r"train=multi\[0, 30, 60, 90, 120\]").all()
           and df.model_config.str.contains(r"test=3win\(0,10,20\)").all())
leak = int(sum(str(r.pineapple_id) in str(r.train_pids).split() for r in df.itertuples()))
fold_ok = df.groupby("pineapple_id").fold_id.nunique().eq(1).all() and df.fold_id.nunique() == 13
check("5.2 來源：4 類／FIXED11／多窗口訓練／三窗口測試",
      "PASS" if prov_ok and set(df.true_stage) <= {0, 1, 2, 3} else "FAIL",
      "(feature_setting、train_mode、test_mode、model_config 欄位；由 round3_diagnosis.py 呼叫 retrain_round2.run(4,'multi','FIXED11') 產生，"
      "round4_analysis.py 已逐日重新訓練並重現相同預測)")
check("5.2 LOGO：每顆鳳梨一折、訓練名單不含測試鳳梨", "PASS" if fold_ok and leak == 0 else "FAIL",
      f"(13 折；leak rows={leak})")

finite = bool(np.isfinite(P).all())
in01 = bool(((P >= 0) & (P <= 1)).all())
sums = P.sum(1)
argmax_ok = bool((P.argmax(1) == df.pred_stage.to_numpy()).all())
ties = int(((P == P.max(1, keepdims=True)).sum(1) > 1).sum())
check("5.3 機率有限、位於 [0,1]", "PASS" if finite and in01 else "FAIL")
check("5.3 四類機率總和 ≈ 1（CSV 四捨五入至 4 位）", "PASS" if np.allclose(sums, 1, atol=5e-4) else "FAIL",
      f"(min={sums.min():.4f}, max={sums.max():.4f})")
check("5.3 類別順序 0..3 且 argmax = pred_stage", "PASS" if argmax_ok else "FAIL", f"(最大值並列 {ties} 列)")

cm = confusion_matrix(df.true_stage, df.pred_stage, labels=[0, 1, 2, 3])
acc = float((df.true_stage == df.pred_stage).mean())
mf1 = float(f1_score(df.true_stage, df.pred_stage, labels=[0, 1, 2, 3], average="macro"))
rec = recall_score(df.true_stage, df.pred_stage, labels=[0, 1, 2, 3], average=None)
print(f"重現：acc={acc:.3f} macroF1={mf1:.3f} recall={np.round(rec, 3).tolist()}\n{cm}")
check("5.4 重現第二輪混淆矩陣與指標",
      "PASS" if np.array_equal(cm, EXPECTED_CM) and round(acc, 3) == 0.426 and round(mf1, 3) == 0.410
      and round(rec[2], 3) == 0.296 and round(rec[3], 3) == 0.267 else "FAIL",
      f"(acc={acc:.3f}, F1={mf1:.3f}, R2={rec[2]:.3f}, R3={rec[3]:.3f})")

has_windows = any(c.startswith(("prob_w", "window_")) for c in raw.columns)
print("5.5 個別窗口機率：", "有" if has_windows else
      "沒有。CSV 只有三窗口平均機率；sliding_share_* 是『三窗口平均』在不同起點的一致率，不是個別窗口分歧，不拿來替代。")
check("5.5 三個個別窗口的預測與機率", "NOT AVAILABLE" if not has_windows else "PASS",
      "(依指示不重新訓練 LOGO 來取得)")

# ═════════════════════════════════════════
# 6. 信心指標
# ═════════════════════════════════════════
section("6. Confidence metrics")
Ps = np.sort(P, axis=1)[:, ::-1]
df["max_probability"] = Ps[:, 0]
df["top2_margin"] = Ps[:, 0] - Ps[:, 1]
with np.errstate(divide="ignore", invalid="ignore"):
    plogp = np.where(P > 0, P * np.log(P), 0.0)  # 0·log0 定義為 0
df["predictive_entropy"] = -plogp.sum(1)
df["normalized_entropy"] = df.predictive_entropy / np.log(4)
df["error_score_maxprob"] = 1 - df.max_probability
df["error_score_margin"] = 1 - df.top2_margin
df["is_error"] = (df.pred_stage != df.true_stage).astype(int)
df["group"] = df.pineapple_id.map(OWNER)
df["n_zero_prob"] = (P == 0).sum(1)
assert df[["predictive_entropy", "normalized_entropy"]].notna().all().all()
print(f"錯誤 {df.is_error.sum()} / {len(df)}；含 0 機率的列：{int((df.n_zero_prob > 0).sum())}")
df[["pineapple_id", "date", "group", "fold_id", "true_stage", "pred_stage", "is_error",
    "prob_stage0", "prob_stage1", "prob_stage2", "prob_stage3", "max_probability", "top2_margin",
    "predictive_entropy", "normalized_entropy", "error_score_maxprob", "error_score_margin",
    "feature_setting", "train_mode", "test_mode", "model_config"]].to_csv(
    OUT / "phase1_prediction_confidence.csv", index=False, encoding="utf-8-sig")


# ═════════════════════════════════════════
# 7. 正確 vs 錯誤的信心分布
# ═════════════════════════════════════════
section("7. Confidence vs correctness")


def describe(v):
    v = np.asarray(v, float)
    if len(v) == 0:
        return {"n": 0}
    q1, q3 = np.percentile(v, [25, 75])
    return {"n": len(v), "mean": v.mean(), "median": np.median(v), "q1": q1, "q3": q3, "iqr": q3 - q1,
            "min": v.min(), "max": v.max()}


summ = []
for metric in ("max_probability", "top2_margin", "normalized_entropy"):
    for lab, sub in (("correct", df[df.is_error == 0]), ("error", df[df.is_error == 1])):
        summ.append({"metric": metric, "outcome": lab, **describe(sub[metric])})
summ = pd.DataFrame(summ).round(4)
summ.to_csv(OUT / "phase1_confidence_summary.csv", index=False, encoding="utf-8-sig")
print(summ.to_string(index=False))
# 重疊程度：正確組的 IQR 與錯誤組的 IQR 是否重疊
for metric in ("max_probability", "top2_margin", "normalized_entropy"):
    a = summ[(summ.metric == metric) & (summ.outcome == "correct")].iloc[0]
    b = summ[(summ.metric == metric) & (summ.outcome == "error")].iloc[0]
    ov = max(0.0, min(a.q3, b.q3) - max(a.q1, b.q1))
    print(f"{metric}: IQR 重疊長度 {ov:.4f}（正確 [{a.q1:.3f},{a.q3:.3f}]，錯誤 [{b.q1:.3f},{b.q3:.3f}]）")

hc = []
for cut in HC_CUTS:
    sub = df[df.max_probability >= cut]
    err = sub[sub.is_error == 1]
    hc.append({"cut_max_probability_ge": cut, "n": len(sub), "correct": int((sub.is_error == 0).sum()),
               "errors": len(err), "error_rate": round(len(err) / len(sub), 3) if len(sub) else np.nan,
               "stage2_errors": int((err.true_stage == 2).sum()), "stage3_errors": int((err.true_stage == 3).sum()),
               "error_pineapples": " ".join(map(str, sorted(err.pineapple_id.unique()))),
               "error_groups": " ".join(sorted(err.group.unique())),
               "error_days": "; ".join(f"{r.pineapple_id}/{r.date}:S{r.true_stage}→S{r.pred_stage}({r.max_probability:.2f})"
                                       for r in err.itertuples()),
               "note": "描述性切點，非拒判門檻"})
hc = pd.DataFrame(hc)
hc.to_csv(OUT / "phase1_high_confidence_errors.csv", index=False, encoding="utf-8-sig")
print("\n高信心切點（描述性）：")
print(hc.drop(columns=["error_days"]).to_string(index=False))
print("最高信心的 10 個錯誤：")
print(df[df.is_error == 1].nlargest(10, "max_probability")[["pineapple_id", "date", "group", "true_stage",
                                                              "pred_stage", "max_probability", "top2_margin"]].to_string(index=False))


# ═════════════════════════════════════════
# 8. Error AUROC ＋ cluster bootstrap
# ═════════════════════════════════════════
section("8. Error AUROC with pineapple-cluster bootstrap")


def auroc(y, s, w=None):
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return np.nan  # 單一結果類別：無法計算（N/A），不填 0.5
    return float(roc_auc_score(y, s, sample_weight=w))


def cluster_boot(d, score, n=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    pids = np.array(sorted(d.pineapple_id.unique()))
    idx = {p: np.flatnonzero(d.pineapple_id.to_numpy() == p) for p in pids}
    y = d.is_error.to_numpy()
    s = d[score].to_numpy()
    vals, invalid = [], 0
    for _ in range(n):
        pick = rng.choice(pids, len(pids), replace=True)       # 有放回抽 13 顆；重複抽到就重複整顆
        ii = np.concatenate([idx[p] for p in pick])
        if len(np.unique(y[ii])) < 2:
            invalid += 1
            continue
        vals.append(roc_auc_score(y[ii], s[ii]))
    vals = np.array(vals)
    return vals, invalid


au_rows, boot_rows = [], []
w_eq = 1.0 / df.groupby("pineapple_id").pineapple_id.transform("size")
for label, col in RISKS.items():
    a = auroc(df.is_error, df[col])
    a_eq = auroc(df.is_error, df[col], w_eq)
    vals, invalid = cluster_boot(df, col)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    # 群組內 AUROC 的平均（去除群組間差異後的排序能力）
    within = {g: auroc(s.is_error, s[col]) for g, s in df.groupby("group")}
    au_rows.append({"risk_score": label, "column": col, "n_days": len(df), "n_errors": int(df.is_error.sum()),
                    "n_pineapples": 13, "auroc_day_weighted": round(a, 3),
                    "auroc_pineapple_equal_weighted": round(a_eq, 3),
                    "boot_ci95_low": round(lo, 3), "boot_ci95_high": round(hi, 3),
                    "boot_median": round(float(np.median(vals)), 3),
                    "boot_P(auroc>0.5)": round(float(np.mean(vals > 0.5)), 3),
                    "boot_valid": len(vals), "boot_invalid_single_class": invalid,
                    **{f"auroc_within_group_{g}": (round(v, 3) if np.isfinite(v) else "N/A") for g, v in within.items()}})
    boot_rows += [{"risk_score": label, "replicate": i, "auroc": round(v, 5)} for i, v in enumerate(vals)]
au = pd.DataFrame(au_rows)
au.to_csv(OUT / "phase1_error_auroc.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(boot_rows).to_csv(OUT / "phase1_cluster_bootstrap.csv", index=False, encoding="utf-8-sig")
print(au.T.to_string())


# ═════════════════════════════════════════
# 9. 群組、10. Stage、11. 逐顆鳳梨
# ═════════════════════════════════════════
def rel_table(key, label_fn=lambda k: k):
    rows = []
    for k, s in df.groupby(key):
        r = {key: label_fn(k), "n_pineapples": s.pineapple_id.nunique(), "n_days": len(s),
             "correct": int((s.is_error == 0).sum()), "errors": int(s.is_error.sum()),
             "accuracy": round(1 - s.is_error.mean(), 3), "error_rate": round(s.is_error.mean(), 3),
             "mean_max_prob": round(s.max_probability.mean(), 3), "median_max_prob": round(s.max_probability.median(), 3),
             "median_top2_margin": round(s.top2_margin.median(), 3),
             "median_norm_entropy": round(s.normalized_entropy.median(), 3),
             "median_maxprob_correct": round(s[s.is_error == 0].max_probability.median(), 3) if (s.is_error == 0).any() else "N/A",
             "median_maxprob_error": round(s[s.is_error == 1].max_probability.median(), 3) if (s.is_error == 1).any() else "N/A",
             **{f"hc_errors_ge{c:.2f}": int(((s.max_probability >= c) & (s.is_error == 1)).sum()) for c in HC_CUTS},
             "stage_coverage": " ".join(f"S{st}:{n}" for st, n in s.true_stage.value_counts().sort_index().items())}
        for lab, col in RISKS.items():
            v = auroc(s.is_error, s[col])
            r[f"auroc[{lab}]"] = round(v, 3) if np.isfinite(v) else "N/A"
        r["auroc_note"] = "" if s.is_error.nunique() == 2 else \
            ("全部正確，AUROC 無法計算" if s.is_error.sum() == 0 else "全部錯誤，AUROC 無法計算")
        rows.append(r)
    return pd.DataFrame(rows)


section("9. Group-wise reliability（群組 ≠ 已確認設備 ID）")
grp = rel_table("group")
grp.to_csv(OUT / "phase1_group_reliability.csv", index=False, encoding="utf-8-sig")
print(grp.to_string(index=False))
grp_mp = df.groupby("group").agg(acc=("is_error", lambda v: 1 - v.mean()), mp=("max_probability", "mean"))
print("\n群組層級：平均信心 vs 準確率\n", grp_mp.round(3).to_string())

section("10. Stage-wise reliability")
stg = rel_table("true_stage", lambda k: f"S{k}")
for st in range(4):
    s = df[df.true_stage == st]
    stg.loc[stg.true_stage == f"S{st}", "recall"] = round(1 - s.is_error.mean(), 3)
    stg.loc[stg.true_stage == f"S{st}", "pred_distribution"] = " ".join(
        f"→S{k}:{n}" for k, n in s.pred_stage.value_counts().sort_index().items())
stg.to_csv(OUT / "phase1_stage_reliability.csv", index=False, encoding="utf-8-sig")
print(stg.to_string(index=False))
for st in (2, 3):
    s = df[df.true_stage == st]
    print(f"\nStage {st} 錯誤的最高機率（由高到低）：",
          [f"{r.pineapple_id}/{r.date}→S{r.pred_stage}:{r.max_probability:.2f}" for r in s[s.is_error == 1].sort_values("max_probability", ascending=False).itertuples()])
    print(f"Stage {st} 正確的最高機率：", [f"{r.pineapple_id}/{r.date}:{r.max_probability:.2f}" for r in s[s.is_error == 0].itertuples()])

section("11. Per-pineapple")
pp = rel_table("pineapple_id")
pp.insert(1, "group", pp.pineapple_id.map(OWNER))
pp.to_csv(OUT / "phase1_per_pineapple.csv", index=False, encoding="utf-8-sig")
print(pp.to_string(index=False))

# 影響分析：留出一顆鳳梨後的整體 AUROC（看是否由少數鳳梨主導）
infl = []
for p in sorted(df.pineapple_id.unique()):
    s = df[df.pineapple_id != p]
    infl.append({"dropped_pineapple": p, "group": OWNER[p],
                 **{f"auroc[{lab}]": round(auroc(s.is_error, s[col]), 3) for lab, col in RISKS.items()}})
for g in sorted(df.group.unique()):
    s = df[df.group != g]
    infl.append({"dropped_pineapple": f"group {g}", "group": g,
                 **{f"auroc[{lab}]": round(auroc(s.is_error, s[col]), 3) for lab, col in RISKS.items()}})
infl = pd.DataFrame(infl)
infl.to_csv(OUT / "phase1_influence_drop_one.csv", index=False, encoding="utf-8-sig")
print("\n移除單一鳳梨／群組後的整體 AUROC：")
print(infl.to_string(index=False))


# ═════════════════════════════════════════
# 圖表
# ═════════════════════════════════════════
def jitter(n, center, seed):
    return np.random.default_rng(int(round(seed * 10))).normal(center, 0.06, n)


def plot_distributions():
    d = pd.read_csv(OUT / "phase1_prediction_confidence.csv")
    fig, axes = plt.subplots(1, 4, figsize=(20, 5))
    for ax, metric, title in zip(axes[:3], ("max_probability", "top2_margin", "normalized_entropy"),
                                 ("最高機率", "Top-2 差距", "正規化熵")):
        data = [d[d.is_error == 0][metric], d[d.is_error == 1][metric]]
        ax.boxplot(data, showfliers=False)
        for k, v in enumerate(data, start=1):
            ax.scatter(jitter(len(v), k, k), v, s=14, alpha=0.6, color=["#1a9850", "#d73027"][k - 1])
        ax.set_xticks([1, 2])
        ax.set_xticklabels([f"正確 (n={len(data[0])})", f"錯誤 (n={len(data[1])})"])
        ax.set_title(title)
    ax = axes[3]
    colors = {0: "#2b8cbe", 1: "#41ab5d", 2: "#fd8d3c", 3: "#d7301f"}
    for st in range(4):
        s = d[d.true_stage == st]
        ax.scatter(s.max_probability, s.is_error + np.random.default_rng(st).normal(0, 0.05, len(s)),
                   color=colors[st], s=22, alpha=0.75, label=f"真實 S{st}")
    for c in HC_CUTS:
        ax.axvline(c, color="#999", ls=":", lw=0.8)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["正確", "錯誤"])
    ax.set_xlabel("最高機率（虛線＝描述性切點 0.7/0.8/0.9，非門檻）")
    ax.legend(fontsize=8)
    ax.set_title("信心 vs 正誤（依真實 Stage 上色）")
    fig.suptitle("Phase 1：正確與錯誤預測的信心分布（LOGO，FIXED11，101 天）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(OUT / "phase1_confidence_distributions.png", dpi=120)
    plt.close(fig)


def plot_auroc():
    a = pd.read_csv(OUT / "phase1_error_auroc.csv")
    b = pd.read_csv(OUT / "phase1_cluster_bootstrap.csv")
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    ax = axes[0]
    for k, r in enumerate(a.itertuples()):
        ax.errorbar(r.auroc_day_weighted, k, xerr=[[r.auroc_day_weighted - r.boot_ci95_low],
                                                   [r.boot_ci95_high - r.auroc_day_weighted]],
                    fmt="o", color="#08519c", capsize=5, label="按天加權＋95% cluster bootstrap CI" if k == 0 else None)
        ax.scatter(r.auroc_pineapple_equal_weighted, k + 0.15, marker="s", color="#e6550d",
                   label="每顆鳳梨等權（敏感度）" if k == 0 else None)
    ax.axvline(0.5, color="k", ls="--", lw=0.8)
    ax.set_yticks(range(len(a)))
    ax.set_yticklabels(a.risk_score)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Error AUROC（正類 = 判錯）")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title("三種風險分數的 Error AUROC")
    ax = axes[1]
    for k, lab in enumerate(a.risk_score):
        v = b[b.risk_score == lab].auroc
        ax.hist(v, bins=40, alpha=0.45, label=lab)
    ax.axvline(0.5, color="k", ls="--", lw=0.8)
    ax.set_xlabel("bootstrap AUROC（以 pineapple_id 為 cluster，2000 次）")
    ax.legend(fontsize=8)
    ax.set_title("Cluster bootstrap 分布")
    fig.tight_layout()
    fig.savefig(OUT / "phase1_error_auroc.png", dpi=120)
    plt.close(fig)


def plot_group_stage(fname, key, order, title):
    d = pd.read_csv(OUT / "phase1_prediction_confidence.csv")
    if key == "true_stage":
        d["k"] = "S" + d.true_stage.astype(str)
    else:
        d["k"] = d[key]
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    ax = axes[0]
    pos = 0
    ticks, labels = [], []
    for k in order:
        s = d[d.k == k]
        for err, col in ((0, "#1a9850"), (1, "#d73027")):
            v = s[s.is_error == err].max_probability
            if len(v):
                ax.boxplot([v], positions=[pos], widths=0.6, showfliers=False)
                ax.scatter(jitter(len(v), pos, pos), v, s=14, color=col, alpha=0.7)
            pos += 1
        ticks.append(pos - 1.5)
        labels.append(f"{k}\n(n={len(s)})")
        pos += 0.8
    for c in HC_CUTS:
        ax.axhline(c, color="#999", ls=":", lw=0.8)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.set_ylabel("最高機率（綠＝正確、紅＝錯誤）")
    ax.set_title(f"{title}：正確／錯誤的最高機率")
    ax = axes[1]
    s = d.groupby("k").agg(acc=("is_error", lambda v: 1 - v.mean()), mp=("max_probability", "mean"),
                           n=("is_error", "size")).reindex(order)
    ax.scatter(s.mp, s.acc, s=s.n * 8, color="#3182bd", alpha=0.7)
    for k, r in s.iterrows():
        ax.annotate(k, (r.mp, r.acc), xytext=(5, 5), textcoords="offset points")
    lim = [0.2, 1.0]
    ax.plot(lim, lim, "k--", lw=0.8, label="平均信心 = 準確率")
    ax.set_xlim(*lim)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("平均最高機率")
    ax.set_ylabel("準確率")
    ax.legend(fontsize=8)
    ax.set_title(f"{title}：平均信心 vs 準確率（點大小＝天數）")
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=120)
    plt.close(fig)


def plot_per_pineapple():
    d = pd.read_csv(OUT / "phase1_prediction_confidence.csv")
    pids = sorted(d.pineapple_id.unique())
    fig, axes = plt.subplots(4, 4, figsize=(18, 13), sharex=True, sharey=True)
    for ax, p in zip(axes.flat, pids):
        s = d[d.pineapple_id == p].sort_values("date")
        x = np.arange(len(s))
        ax.bar(x, s.max_probability, color=np.where(s.is_error == 1, "#d73027", "#1a9850"))
        for xi, r in zip(x, s.itertuples()):
            ax.text(xi, 0.02, f"{r.true_stage}→{r.pred_stage}", ha="center", fontsize=6, rotation=90, color="white")
        for c in HC_CUTS:
            ax.axhline(c, color="#999", ls=":", lw=0.7)
        ax.set_title(f"鳳梨 {p:02d}（群組 {OWNER[p]}）acc={1 - s.is_error.mean():.2f}", fontsize=9)
        ax.set_ylim(0, 1)
    for ax in list(axes.flat)[len(pids):]:
        ax.axis("off")
    fig.suptitle("逐顆鳳梨：每天的最高機率（綠＝正確、紅＝錯誤；標示 真實→預測）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "phase1_per_pineapple.png", dpi=110)
    plt.close(fig)


plot_distributions()
plot_auroc()
plot_group_stage("phase1_group_comparison.png", "group", sorted(df.group.unique()), "群組")
plot_group_stage("phase1_stage_comparison.png", "true_stage", ["S0", "S1", "S2", "S3"], "真實 Stage")
plot_per_pineapple()

# ═════════════════════════════════════════
# 15. 驗收
# ═════════════════════════════════════════
section("15. Mandatory verification")
recomputed = []
for label, col in RISKS.items():
    # 方向檢查：風險分數越高越可能錯；直接以 is_error=1 為正類計算
    recomputed.append(abs(roc_auc_score(df.is_error, df[col]) - au.set_index("risk_score").loc[label, "auroc_day_weighted"]) < 1e-3)
zero_rows = df[df.n_zero_prob > 0]
check("7. Error AUROC 方向：risk score 越高越可能錯、is_error=1 為正類", "PASS" if all(recomputed) else "FAIL",
      "(1−maxprob、1−margin、normalized_entropy)")
check("8. Entropy 對零機率處理（0·log0 = 0，無 NaN）",
      "PASS" if df.normalized_entropy.notna().all() and (df.normalized_entropy.between(0, 1)).all() else "FAIL",
      f"(含 0 機率的列 {len(zero_rows)})")
check("9. Cluster bootstrap 以 pineapple_id 抽樣（13 顆、有放回、保留整顆所有日期）", "PASS",
      f"(seed={SEED}, B={N_BOOT})")
na_ok = all(((r["auroc_note"] != "") == (r["auroc[1 - max_probability]"] == "N/A"))
            for t in (grp, stg, pp) for _, r in t.iterrows())
check("10. 單一結果類別的 AUROC 標記 N/A，不填 0.5", "PASS" if na_ok else "FAIL")
check("11. 群組與 Stage 分析完整、缺失類別有註記",
      "PASS" if len(grp) == df.group.nunique() and len(stg) == 4 and stg.stage_coverage.notna().all() else "FAIL",
      f"(群組 {sorted(df.group.unique())}；群組 C 只有 S0、群組 D 只有 S1/S3 已記錄於 stage_coverage)")
check("12. Window Disagreement 未取得原始窗口資料時不虛構", "NOT AVAILABLE" if not has_windows else "PASS",
      "(未計算、未推測)")
check("13. 未選擇或最佳化任何拒判門檻", "PASS", "(0.7/0.8/0.9 為事先固定的描述性切點，未依結果調整)")
check("14. 未開始 Phase 2", "PASS", "(無 risk–coverage、拒判、校準模型或新模型訓練)")
after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}
changed = [p for p in SNAP if SNAP[p] != after.get(p)]
dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], capture_output=True, text=True, cwd=WT).stdout
dirty = [l for l in dirty.splitlines() if "reliability_phase1" not in l]
check("15. 原始資料、標籤、gateway、部署模型、既有分析程式未修改",
      "PASS" if not changed and not dirty else "FAIL",
      f"({len(SNAP)} 檔 SHA-256 前後一致；git status 除本輪新增外無變更={not dirty}；App 不在此 sparse checkout）")

with open(OUT / "phase1_checks.txt", "w", encoding="utf-8") as f:
    for name, status, detail in CHECKS:
        f.write(f"[{status}] {name} {detail}\n")
cnt = pd.Series([s for _, s, _ in CHECKS]).value_counts().to_dict()
print("\n驗收統計：", cnt)
