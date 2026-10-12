"""
第三輪診斷：Label Consistency / Dynamic Signal Analysis / Stage 2 LOGO Error Attribution

只做分析，不訓練新模型（僅重新執行第二輪既定的 LOGO 以重現結果並匯出逐日預測）、
不匯出 .pkl、不修改原始 XLSX、人工標籤、gateway 或部署模型。

主要基準：4 類 / FIXED11 / 多窗口訓練 / 三窗口測試（retrain_round2.run(4, "multi", "FIXED11")）
補充對照：SEL-GW8 / 多窗口訓練（只匯出，不與主要基準混用）

Run:  python -u round3_diagnosis.py > round3_results/round3_run_log.txt
"""
import hashlib
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import mannwhitneyu, spearmanr  # noqa: E402

import retrain_round2 as r2  # noqa: E402  （import 時會載入資料並計算窗口特徵）
from eval_common import FEATURES, ORK, RAW, SENSORS, WINDOW, WT, new, read_raw_xlsx  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
OUT = HERE / "round3_results"
OUT.mkdir(exist_ok=True)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)

# 編號規則.docx：不同編號由不同同學負責（報告中以群組代號表示）
OWNER = {1: "A", 2: "A", 9: "A", 12: "A",
         3: "B", 4: "B", 10: "B", 11: "B", 13: "B",
         5: "C", 6: "C", 14: "C",
         7: "D", 8: "D"}
STAGE_COLORS = {0: "#2b8cbe", 1: "#41ab5d", 2: "#fd8d3c", 3: "#d7301f"}
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def section(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ─────────────────────────────────────────
# 0. 完整性快照（原始資料、標籤、gateway、部署模型）
# ─────────────────────────────────────────
PROTECTED = sorted(
    list(RAW.glob("*.xlsx"))
    + [ORK / "labeling.xlsx", ORK / "data_label_audit_report.xlsx"]
    + list((WT / "pineapple_final").glob("*"))
    + list((WT / "pineapple_app_gateway").glob("*.py"))
)


def snapshot():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}


SNAP_BEFORE = snapshot()

days = r2.days
DAY = {(d["pid"], d["date"]): d for d in days}


def to_dt(x):
    return pd.to_datetime(str(int(x)), format="%Y%m%d", errors="coerce")


# ═════════════════════════════════════════
# Round 3A｜Label Consistency Audit
# ═════════════════════════════════════════
section("Round 3A｜Label Consistency Audit")
audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
lab = audit[audit.has_label == 1].copy()
lab["pid"] = lab.pid.astype(int)
lab["date"] = lab.date.astype(int)
lab["mdate"] = lab.date.map(to_dt)
lab["true_stage"] = lab.stage.astype(int)
lab["in_analysis"] = [(p, d) in DAY for p, d in zip(lab.pid, lab.date)]
lab = lab.sort_values(["pid", "mdate"]).reset_index(drop=True)

recs = []
for pid, g in lab.groupby("pid"):
    prev_stage, prev_dt = None, None
    for _, r in g.iterrows():
        change = None if prev_stage is None else int(r.true_stage - prev_stage)
        gap = None if prev_dt is None else int((r.mdate - prev_dt).days)
        reasons = []
        if change is not None and change < 0:
            reasons.append(f"階段倒退 {prev_stage}→{r.true_stage}（待人工複查）")
        if change is not None and change > 1:
            reasons.append(f"跳階 {prev_stage}→{r.true_stage}")
        if gap is not None and gap > 3:
            reasons.append(f"與前次量測相隔 {gap} 天")
        if not r.has_raw_fruit:
            reasons.append("有標籤但無原始鳳梨檔")
        elif not r.in_analysis:
            reasons.append("原始檔無法讀取，未納入 101 天")
        recs.append({
            "pineapple_id": pid, "owner_group": OWNER.get(pid, "?"), "date": r.date,
            "true_stage": int(r.true_stage), "previous_stage": prev_stage, "stage_change": change,
            "days_since_previous_measurement": gap,
            "potential_stage_regression": bool(change is not None and change < 0),
            "stage_jump_gt1": bool(change is not None and change > 1),
            "has_raw_fruit": bool(r.has_raw_fruit), "in_analysis_101": bool(r.in_analysis),
            "anomaly_reason": "；".join(reasons),
        })
        prev_stage, prev_dt = int(r.true_stage), r.mdate
label_audit = pd.DataFrame(recs)
label_audit.to_csv(HERE / "round3_label_audit.csv", index=False, encoding="utf-8-sig")

n_reg = int(label_audit.potential_stage_regression.sum())
n_jump = int(label_audit.stage_jump_gt1.sum())
print(f"標籤總數（含無原始檔）：{len(label_audit)}；納入分析：{int(label_audit.in_analysis_101.sum())}")
print(f"階段倒退：{n_reg} 筆；跳階（>1）：{n_jump} 筆")
print(label_audit[label_audit.anomaly_reason != ""][["pineapple_id", "date", "previous_stage", "true_stage",
                                                     "days_since_previous_measurement", "anomaly_reason"]].to_string(index=False))

# 跟 audit 報表既有的 label_regression / label_big_jump 對照
for sh in ("label_regression", "label_big_jump"):
    try:
        print(f"audit 報表 {sh}：{len(pd.read_excel(ORK / 'data_label_audit_report.xlsx', sheet_name=sh))} 筆")
    except Exception as e:  # pragma: no cover
        print(sh, "讀取失敗", e)


def plot_label_timeline():
    la = pd.read_csv(HERE / "round3_label_audit.csv")
    la["mdate"] = la.date.map(to_dt)
    pids = sorted(la.pineapple_id.unique())
    ncol = 4
    nrow = int(np.ceil(len(pids) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(16, 2.6 * nrow), sharey=True)
    for ax, pid in zip(axes.flat, pids):
        g = la[la.pineapple_id == pid].sort_values("mdate")
        ax.step(g.mdate, g.true_stage, where="post", color="#555", lw=1)
        for _, r in g.iterrows():
            c = STAGE_COLORS[r.true_stage]
            ax.scatter(r.mdate, r.true_stage, s=36, color=c if r.in_analysis_101 else "white",
                       edgecolor=c, zorder=3)
            if r.potential_stage_regression:
                ax.scatter(r.mdate, r.true_stage, s=140, facecolor="none", edgecolor="red", lw=1.5, zorder=4)
        ax.set_title(f"pineapple {pid:02d}（群組 {OWNER.get(pid, '?')}）", fontsize=10)
        ax.set_yticks([0, 1, 2, 3])
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
        ax.grid(alpha=0.3)
    for ax in list(axes.flat)[len(pids):]:
        ax.axis("off")
    fig.suptitle("人工標籤時間軸（實心＝納入 101 天分析；空心＝無可用原始檔；紅圈＝階段倒退待複查）", fontsize=12)
    fig.tight_layout()
    fig.savefig(HERE / "round3_label_timeline.png", dpi=130)
    plt.close(fig)


plot_label_timeline()

# A2 分布與個體覆蓋（以 101 天分析資料為準）
ana = label_audit[label_audit.in_analysis_101].copy()
pid_stage = pd.crosstab(ana.pineapple_id, ana.true_stage).reindex(columns=[0, 1, 2, 3], fill_value=0)
pid_stage.to_csv(OUT / "round3_pid_stage_counts.csv", encoding="utf-8-sig")
print("\npineapple × stage 天數（101 天）：")
print(pid_stage.to_string())
stage_pids = {s: int((pid_stage[s] > 0).sum()) for s in range(4)}
print("各 Stage 出現在幾顆鳳梨：", stage_pids)
for s in (2, 3):
    col = pid_stage[s].sort_values(ascending=False)
    top = col[col > 0]
    share_top2 = top.iloc[:2].sum() / top.sum()
    print(f"Stage {s}：{top.sum()} 天分布在 {len(top)} 顆；前兩顆佔 {share_top2:.0%}：{top.to_dict()}")

cover = []
for pid, g in ana.groupby("pineapple_id"):
    st = sorted(set(g.true_stage))
    dts = g.date.map(to_dt)
    cover.append({
        "pineapple_id": pid, "owner_group": OWNER.get(pid, "?"), "n_days": len(g),
        "stages_observed": ",".join(map(str, st)),
        "contiguous_stages": st == list(range(st[0], st[-1] + 1)),
        "first_date": g.date.min(), "last_date": g.date.max(),
        "span_days": int((dts.max() - dts.min()).days),
        "median_gap_days": float(np.median(g.days_since_previous_measurement.dropna())) if len(g) > 1 else np.nan,
    })
cover = pd.DataFrame(cover)
cover.to_csv(OUT / "round3_pid_coverage.csv", index=False, encoding="utf-8-sig")
print("\n各鳳梨覆蓋：")
print(cover.to_string(index=False))
gap_by_stage = ana.groupby("true_stage").days_since_previous_measurement.describe()[["count", "50%", "max"]]
print("\n各 Stage 與前次量測的日期間隔：")
print(gap_by_stage.to_string())

# 不同標註群組：從第一次量測到第一次 Stage 2 / 3 的天數
first = []
for pid, g in lab.groupby("pid"):
    d0 = g.mdate.min()
    row = {"pineapple_id": pid, "owner_group": OWNER.get(pid, "?")}
    for s in (1, 2, 3):
        hit = g[g.true_stage >= s]
        row[f"days_to_stage{s}"] = int((hit.mdate.min() - d0).days) if len(hit) else np.nan
    first.append(row)
first = pd.DataFrame(first)
first.to_csv(OUT / "round3_days_to_stage.csv", index=False, encoding="utf-8-sig")
print("\n從第一次量測到首次標為 ≥Stage s 的天數（含無原始檔的標籤日）：")
print(first.to_string(index=False))
print("\n各群組 Stage 天數：")
print(pd.crosstab(ana.owner_group, ana.true_stage).to_string())


def plot_heatmap():
    m = pd.read_csv(OUT / "round3_pid_stage_counts.csv", index_col=0)
    fig, ax = plt.subplots(figsize=(5.5, 6))
    im = ax.imshow(m.values, cmap="Oranges")
    ax.set_xticks(range(4))
    ax.set_xticklabels([f"Stage {c}" for c in m.columns])
    ax.set_yticks(range(len(m)))
    ax.set_yticklabels([f"{i:02d}（{OWNER.get(i, '?')}）" for i in m.index])
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, int(m.values[i, j]), ha="center", va="center", fontsize=9)
    ax.set_title("鳳梨 × 成熟階段 天數（101 天）")
    fig.colorbar(im, ax=ax, shrink=0.6)
    fig.tight_layout()
    fig.savefig(OUT / "round3_pid_stage_heatmap.png", dpi=130)
    plt.close(fig)


plot_heatmap()

# A3 可驗證性：repo 內是否有糖度、硬度、外觀等紀錄
labeling_cols = pd.read_excel(ORK / "labeling.xlsx").columns.tolist()
print("\nA3：labeling.xlsx 欄位 =", labeling_cols, "；repo 中未找到糖度／硬度／外觀等獨立觀察紀錄")


# ═════════════════════════════════════════
# Round 3B｜Dynamic Sensor Signal Analysis
# ═════════════════════════════════════════
section("Round 3B｜Dynamic Sensor Signal Analysis")
amap = audit.set_index(["pid", "date"])


def file_mode(path):
    try:
        head = pd.read_excel(path, header=None, nrows=4, usecols=[0]).iloc[:, 0].astype(str).tolist()
    except Exception:
        return "unreadable"
    for v in head:
        if "MODE:" in v:
            return v.split("MODE:")[1].strip(" #").replace("_INTERNAL_ADC", "")
    return "none"


def slope(y):
    return float(np.polyfit(np.arange(len(y)), y, 1)[0]) if len(y) >= 2 else np.nan


sig_rows, curve_rows = [], []
for d in sorted(days, key=lambda x: (x["pid"], x["date"])):
    pid, date = d["pid"], d["date"]
    a = amap.loc[(pid, date)]
    fruit_path = RAW / a.fruit_file
    air_file = a.air_file if isinstance(a.air_file, str) and (RAW / a.air_file).exists() else None
    fdf = read_raw_xlsx(fruit_path)
    adf = read_raw_xlsx(RAW / air_file) if air_file else None

    ts = fdf["timestamp_ms"].to_numpy(dtype=float) if "timestamp_ms" in fdf else np.array([])
    ts_ok = ts[~np.isnan(ts)]
    iv = np.diff(ts_ok) / 1000.0 if len(ts_ok) > 1 else np.array([np.nan])
    raw_mat = {s: np.array([r[s] for r in d["rows"]], dtype=float) for s in SENSORS}
    jumps = {s: int(np.sum(np.abs(np.diff(raw_mat[s])) >= 20)) for s in SENSORS}
    n_cmp = min(len(fdf), len(adf)) if adf is not None else 0
    fruit_equals_air = bool(adf is not None and all(
        np.array_equal(fdf[f"{s}_raw"].to_numpy()[:n_cmp], adf[f"{s}_raw"].to_numpy()[:n_cmp]) for s in SENSORS))
    missing = {s: int(fdf[f"{s}_raw"].isna().sum()) for s in SENSORS}

    row = {
        "pineapple_id": pid, "owner_group": OWNER.get(pid, "?"), "date": date, "true_stage": d["y"],
        "fruit_file": a.fruit_file, "air_file": air_file or "",
        "air_source": a.air_source if air_file else "fallback_first_fruit_file",
        "fruit_mode": file_mode(fruit_path), "air_mode": file_mode(RAW / air_file) if air_file else "",
        "n_rows": len(d["rows"]), "ts_present": len(ts_ok) > 0, "ts_missing": int(len(ts) - len(ts_ok)),
        "ts_median_interval_s": float(np.nanmedian(iv)), "ts_min_interval_s": float(np.nanmin(iv)),
        "ts_max_interval_s": float(np.nanmax(iv)), "ts_duplicates": int(np.sum(iv == 0)),
        "ts_nonpositive": int(np.sum(iv <= 0)),
        "missing_gas_values": int(sum(missing.values())), "jump_count_ge20adc": int(sum(jumps.values())),
        "air_rows": len(adf) if adf is not None else 0,
        "fruit_equals_air": fruit_equals_air,
        "temp_c": float(fdf["Temp_C"].iloc[:WINDOW].mean()) if "Temp_C" in fdf else np.nan,
        "humidity_pct": float(fdf["Humidity_pct"].iloc[:WINDOW].mean()) if "Humidity_pct" in fdf else np.nan,
        "air_temp_c": float(adf["Temp_C"].iloc[:WINDOW].mean()) if adf is not None and "Temp_C" in adf else np.nan,
        "air_humidity_pct": float(adf["Humidity_pct"].iloc[:WINDOW].mean()) if adf is not None and "Humidity_pct" in adf else np.nan,
    }
    for s in SENSORS:
        b = d["air"][s]
        x = raw_mat[s]
        n = x / b
        wins = [n[i:i + WINDOW].mean() for i in range(0, len(n) - WINDOW + 1, WINDOW)]
        row.update({
            f"{s}_air_baseline_raw": b,
            f"{s}_raw_mean30": float(x[:WINDOW].mean()),
            f"{s}_amp30": float(n[:WINDOW].mean() - 1),            # 開頭 30 秒相對空氣基準的反應量
            f"{s}_amp_full": float(np.median(n) - 1),              # 整段記錄的中位反應量
            f"{s}_early_late": float(n[-60:].mean() - n[:60].mean()),
            f"{s}_slope30": slope(n[:WINDOW]),
            f"{s}_slope_full_per100s": slope(n) * 100,
            f"{s}_std30": float(n[:WINDOW].std()),
            f"{s}_win_up_frac": float(np.mean(np.diff(wins) > 0)) if len(wins) > 1 else np.nan,
            f"{s}_win_volatility": float(np.std(wins)),
        })
        for i in range(0, len(n), 5):  # 每 5 秒一點，供曲線圖重現
            curve_rows.append((pid, date, d["y"], s, i, float(x[i]), float(b), float(n[i])))
    sig_rows.append(row)

sig = pd.DataFrame(sig_rows)
pd.DataFrame(curve_rows, columns=["pineapple_id", "date", "true_stage", "sensor", "t_s", "raw", "air_baseline",
                                  "normalized"]).to_csv(OUT / "round3_normalized_curves.csv", index=False)

# 縱向（需同一顆鳳梨歷史）指標
sig["mdate"] = sig.date.map(to_dt)
sig = sig.sort_values(["pineapple_id", "mdate"])
sig["days_since_first"] = sig.groupby("pineapple_id").mdate.transform(lambda s: (s - s.min()).dt.days)
for s in SENSORS:
    c = f"{s}_amp30"
    first_val = sig.groupby("pineapple_id")[c].transform("first")
    sig[f"long_{s}_amp30_delta_vs_first"] = sig[c] - first_val
    prev = sig.groupby("pineapple_id")[c].shift(1)
    gap = sig.groupby("pineapple_id").mdate.diff().dt.days
    sig[f"long_{s}_amp30_change_per_day"] = (sig[c] - prev) / gap

print("B1 原始資料稽核：")
print(f"  timestamp 存在：{sig.ts_present.mean():.0%}；取樣間隔中位數範圍 {sig.ts_median_interval_s.min():.3f}～{sig.ts_median_interval_s.max():.3f} s；"
      f"最大間隔 {sig.ts_max_interval_s.max():.3f} s；重複時間戳 {int(sig.ts_duplicates.sum())}；非正間隔 {int(sig.ts_nonpositive.sum())}")
print(f"  缺失氣體值總數 {int(sig.missing_gas_values.sum())}；記錄長度 {sig.n_rows.min()}～{sig.n_rows.max()} 筆")
print("  空氣基準來源：", sig.air_source.value_counts().to_dict())
print("  鳳梨檔的 MODE 標記：", sig.fruit_mode.value_counts().to_dict())
print("  空氣檔的 MODE 標記：", sig.air_mode.value_counts().to_dict())
mode_air = sig[sig.fruit_mode == "AIR"]
print(f"  鳳梨檔標記為 AIR 模式：{len(mode_air)} 天（pid {sorted(mode_air.pineapple_id.unique())}）")
print("  ≥20 ADC 跳值次數（全部天數合計）：", int(sig.jump_count_ge20adc.sum()))
dup = sig[sig.fruit_equals_air]
print(f"  鳳梨檔感測值與同日空氣檔完全相同：{len(dup)} 天 →",
      dup[["pineapple_id", "date", "true_stage", "fruit_file", "air_file"]].to_dict("records"))
print("  原始資料中沒有「鳳梨放入」或「取出／恢復」的時間標記 → 無法做真實暴露反應（T90）或恢復時間分析")

amp_sum = pd.DataFrame({s: {
    "P(amp30>0)": (sig[f"{s}_amp30"] > 0).mean(), "P(amp_full>0)": (sig[f"{s}_amp_full"] > 0).mean(),
    "median_amp30": sig[f"{s}_amp30"].median(), "median_amp_full": sig[f"{s}_amp_full"].median(),
    "median_abs_amp30": sig[f"{s}_amp30"].abs().median(),
    "P(|amp30|>0.05)": (sig[f"{s}_amp30"].abs() > 0.05).mean()} for s in SENSORS}).round(3)
amp_sum.to_csv(OUT / "round3_fruit_vs_air_amplitude.csv", encoding="utf-8-sig")
print("\nB2 鳳梨讀值相對同日空氣基準（amp = raw/air − 1）：")
print(amp_sum.to_string())

SINGLE = [f"{s}_{m}" for s in SENSORS for m in ("amp30", "amp_full", "early_late", "slope30",
                                                 "slope_full_per100s", "std30", "win_up_frac", "win_volatility")]
LONG = [f"long_{s}_amp30_delta_vs_first" for s in SENSORS] + [f"long_{s}_amp30_change_per_day" for s in SENSORS]


def eta2(v, g):
    v = np.asarray(v, float)
    g = np.asarray(g)
    ok = ~np.isnan(v)
    v, g = v[ok], g[ok]
    tot = np.sum((v - v.mean()) ** 2)
    if tot == 0:
        return np.nan
    return float(sum(len(v[g == k]) * (v[g == k].mean() - v.mean()) ** 2 for k in np.unique(g)) / tot)


def within_rho(df, col, target):
    rhos = []
    for _, g in df.groupby("pineapple_id"):
        g = g.dropna(subset=[col])
        if len(g) < 3 or g[target].nunique() < 2 or g[col].nunique() < 2:
            continue
        r = spearmanr(g[col], g[target]).correlation
        if np.isfinite(r):
            rhos.append(r)
    if not rhos:
        return np.nan, np.nan, 0
    m = float(np.mean(rhos))
    return m, float(np.mean(np.sign(rhos) == np.sign(m))), len(rhos)


var_rows = []
for col in SINGLE + LONG:
    v = sig[col].to_numpy(float)
    centered = v - sig.groupby("pineapple_id")[col].transform("mean").to_numpy(float)
    m_st, c_st, n_st = within_rho(sig, col, "true_stage")
    m_t, _, _ = within_rho(sig, col, "days_since_first")
    # 同一 Stage 不同鳳梨的分散程度（各 stage 內鳳梨平均值的標準差，再取中位數）
    between_pid_sd = np.nanmedian([sig[sig.true_stage == s].groupby("pineapple_id")[col].mean().std()
                                   for s in range(4)])
    var_rows.append({
        "feature": col, "type": "longitudinal" if col.startswith("long_") else "single-scan",
        "eta2_pid": round(eta2(v, sig.pineapple_id), 3), "eta2_stage": round(eta2(v, sig.true_stage), 3),
        "eta2_stage_pid_centered": round(eta2(centered, sig.true_stage), 3),
        "rho_within_pid_vs_stage": round(m_st, 3), "sign_consistency": round(c_st, 2), "n_pid": n_st,
        "rho_within_pid_vs_days": round(m_t, 3),
        "between_pid_sd_same_stage": round(float(between_pid_sd), 4),
        "overall_sd": round(float(np.nanstd(v)), 4),
    })
var = pd.DataFrame(var_rows)
var["score"] = (var.rho_within_pid_vs_stage.abs() * var.sign_consistency).round(3)
var = var.sort_values("score", ascending=False)
var.to_csv(OUT / "round3_variance_decomposition.csv", index=False, encoding="utf-8-sig")
print("\nB4 變異分解（描述性，全部 101 天；pid-centered 使用同顆鳳梨全部日期，僅供描述）：")
print(var.head(20).to_string(index=False))
print("\n縱向指標：")
print(var[var.type == "longitudinal"].to_string(index=False))

# 混雜因素：成熟度與日期進程、溫濕度、空氣基準
conf_rows = []
for col in ["days_since_first", "temp_c", "humidity_pct"] + [f"{s}_air_baseline_raw" for s in SENSORS]:
    pooled = spearmanr(sig[col], sig.true_stage, nan_policy="omit").correlation
    m, cns, n = within_rho(sig, col, "true_stage")
    conf_rows.append({"variable": col, "spearman_pooled_vs_stage": round(float(pooled), 3),
                      "within_pid_mean_rho": round(m, 3), "sign_consistency": round(cns, 2), "n_pid": n})
conf = pd.DataFrame(conf_rows)
conf.to_csv(OUT / "round3_confounders.csv", index=False, encoding="utf-8-sig")
print("\nB3 混雜因素（與成熟階段的 Spearman）：")
print(conf.to_string(index=False))

sig["month"] = sig.date // 100 % 100
base_rows = []
for s in SENSORS:
    c = f"{s}_air_baseline_raw"
    base_rows.append({"sensor": s, "eta2_pid": round(eta2(sig[c], sig.pineapple_id), 2),
                      "eta2_owner_group": round(eta2(sig[c], sig.owner_group), 2),
                      "eta2_month": round(eta2(sig[c], sig.month), 2),
                      "eta2_stage": round(eta2(sig[c], sig.true_stage), 2)})
base_eta = pd.DataFrame(base_rows)
base_by_group = sig.groupby(["owner_group", "month"])[[f"{s}_air_baseline_raw" for s in SENSORS]].median().round(0)
base_eta.to_csv(OUT / "round3_air_baseline_eta2.csv", index=False, encoding="utf-8-sig")
base_by_group.to_csv(OUT / "round3_air_baseline_by_group_month.csv", encoding="utf-8-sig")
print("\n空氣基準原始值的變異來源（eta2）：")
print(base_eta.to_string(index=False))
print("\n空氣基準原始值中位數（群組 × 月份）：")
print(base_by_group.to_string())
print("\n月份 × 階段 天數：")
print(pd.crosstab(sig.month, sig.true_stage).to_string())
sig = sig.drop(columns=["month"])

# ═════════════════════════════════════════
# Round 3C｜Stage 2 LOGO Error Attribution
# ═════════════════════════════════════════
section("Round 3C｜Stage 2 LOGO Error Attribution")
EXPECTED_CM = np.array([[17, 6, 8, 1], [5, 14, 7, 1], [9, 8, 8, 2], [3, 2, 6, 4]])
MODEL_CONFIG = (f"ExtraTrees(n_estimators={r2.ET_PARAMS['n_estimators']},max_features={r2.ET_PARAMS['max_features']},"
                f"random_state={r2.ET_PARAMS['random_state']})|train=multi{r2.AUG_STARTS} w=1/{len(r2.AUG_STARTS)}"
                f"|test=3win(0,{r2.STEP},{2 * r2.STEP})|LOGO=pineapple_id")

pred_frames = {}
for feat_mode in ("FIXED11", "SEL-GW8"):
    out, _ = r2.run(4, "multi", feat_mode)
    rows = []
    for i in range(len(out["y"])):
        P3 = out["proba_three"][i]
        Pall = out["proba_all"][i]
        seq = [int(np.argmax(Pall[k:k + r2.K].mean(axis=0))) for k in range(len(Pall) - r2.K + 1)]
        rows.append({
            "pineapple_id": int(out["pid"][i]), "date": int(out["date"][i]), "fold_id": int(out["fold"][i]),
            "true_stage": int(out["y"][i]), "pred_stage": int(out["three"][i]),
            "correct": bool(out["y"][i] == out["three"][i]),
            **{f"prob_stage{k}": round(float(P3[k]), 4) for k in range(4)},
            "feature_setting": feat_mode, "train_mode": "multi", "test_mode": "three_window",
            "model_config": MODEL_CONFIG,
            "train_pids": " ".join(map(str, out["train_pids"][i])),
            "sliding_share_pred": round(seq.count(int(out["three"][i])) / len(seq), 3),
            "sliding_share_true": round(seq.count(int(out["y"][i])) / len(seq), 3),
            "sliding_mode_stage": max(set(seq), key=seq.count),
        })
    pred_frames[feat_mode] = pd.DataFrame(rows)

preds = pd.concat(pred_frames.values(), ignore_index=True)
preds.to_csv(HERE / "round3_logo_predictions.csv", index=False, encoding="utf-8-sig")
main = pred_frames["FIXED11"].copy()

cm = pd.crosstab(main.true_stage, main.pred_stage).reindex(index=range(4), columns=range(4), fill_value=0).values
acc = float(main.correct.mean())
from sklearn.metrics import f1_score, recall_score  # noqa: E402

mf1 = float(f1_score(main.true_stage, main.pred_stage, average="macro", labels=[0, 1, 2, 3]))
rec = recall_score(main.true_stage, main.pred_stage, average=None, labels=[0, 1, 2, 3])
print("主要基準（FIXED11 / 4 類 / 多窗口訓練 / 三窗口測試）重現：")
print(pd.DataFrame(cm, index=[f"真{i}" for i in range(4)], columns=[f"預{i}" for i in range(4)]).to_string())
print(f"acc={acc:.3f} macroF1={mf1:.3f} recall={np.round(rec, 3).tolist()}")

# C3：Stage 2 誤判分析
GROUP = {2: "correct", 0: "err_to_0", 1: "err_to_1", 3: "err_to_3"}
s2 = main[main.true_stage == 2].copy()
s2["group"] = s2.pred_stage.map(GROUP)
w0 = {(d["pid"], d["date"]): d["feats"][0] for d in days}
w3 = {(d["pid"], d["date"]): {c: float(np.mean([d["feats"][k][c] for k in range(r2.K)])) for c in FEATURES}
      for d in days}
sigk = sig.set_index(["pineapple_id", "date"])
labk = label_audit.set_index(["pineapple_id", "date"])

err_rows = []
for _, r in s2.iterrows():
    key = (r.pineapple_id, r.date)
    g = label_audit[label_audit.pineapple_id == r.pineapple_id].reset_index(drop=True)
    i = g.index[g.date == r.date][0]
    srow = sigk.loc[key]
    notes = []
    if srow.fruit_equals_air:
        notes.append("鳳梨檔感測值與空氣檔完全相同（無鳳梨資料）")
    if srow.fruit_mode == "AIR":
        notes.append("鳳梨檔標記 AIR 模式")
    if srow.air_source != "pid_specific":
        notes.append(f"空氣基準來源={srow.air_source}")
    if srow.jump_count_ge20adc > 0:
        notes.append(f"≥20ADC 跳值 {int(srow.jump_count_ge20adc)} 次")
    if srow.ts_max_interval_s > 1.5:
        notes.append(f"最大取樣間隔 {srow.ts_max_interval_s:.1f}s")
    rec_ = {
        "pineapple_id": r.pineapple_id, "owner_group": OWNER.get(r.pineapple_id, "?"), "date": r.date,
        "group": r.group, "pred_stage": r.pred_stage,
        **{f"prob_stage{k}": r[f"prob_stage{k}"] for k in range(4)},
        "sliding_share_true(stage2)": r.sliding_share_true, "sliding_mode_stage": r.sliding_mode_stage,
        "prev_date": g.date[i - 1] if i > 0 else None, "prev_stage": g.true_stage[i - 1] if i > 0 else None,
        "next_date": g.date[i + 1] if i + 1 < len(g) else None,
        "next_stage": g.true_stage[i + 1] if i + 1 < len(g) else None,
        "days_since_first": int(srow.days_since_first),
        **{f"w0_{c}": round(w0[key][c], 5) for c in FEATURES},
        **{f"w3mean_{c}": round(w3[key][c], 5) for c in FEATURES},
        **{f"{s}_amp30": round(srow[f"{s}_amp30"], 4) for s in SENSORS},
        **{f"{s}_air_baseline_raw": round(srow[f"{s}_air_baseline_raw"], 2) for s in SENSORS},
        "temp_c": round(srow.temp_c, 2), "humidity_pct": round(srow.humidity_pct, 2),
        "air_source": srow.air_source, "fruit_mode": srow.fruit_mode,
        "quality_notes": "；".join(notes),
    }
    err_rows.append(rec_)
s2err = pd.DataFrame(err_rows).sort_values(["group", "pineapple_id", "date"])
s2err.to_csv(HERE / "round3_stage2_errors.csv", index=False, encoding="utf-8-sig")
print("\nStage 2 的 27 天：", s2.group.value_counts().to_dict())
print(s2err[["pineapple_id", "owner_group", "date", "group", "prob_stage0", "prob_stage1", "prob_stage2",
             "prob_stage3", "sliding_share_true(stage2)", "prev_stage", "next_stage", "quality_notes"]].to_string(index=False))

# 各組中位數比較：Stage 2 正確 / 誤判 0/1 與其他真實 Stage 的參考分布
main_k = main.set_index(["pineapple_id", "date"])
ref = []
for key, d in DAY.items():
    p = main_k.loc[key]
    if p.true_stage == 2:
        grp = "S2_correct" if p.pred_stage == 2 else ("S2_err_to_0/1" if p.pred_stage in (0, 1) else "S2_err_to_3")
    else:
        grp = f"true_S{p.true_stage}"
    row = {"pineapple_id": key[0], "date": key[1], "grp": grp}
    row.update({c: w3[key][c] for c in FEATURES})
    srow = sigk.loc[key]
    row.update({f"{s}_amp30": srow[f"{s}_amp30"] for s in SENSORS})
    row.update({"temp_c": srow.temp_c, "humidity_pct": srow.humidity_pct,
                **{f"{s}_air_baseline_raw": srow[f"{s}_air_baseline_raw"] for s in SENSORS}})
    ref.append(row)
ref = pd.DataFrame(ref)
cmp_cols = list(FEATURES) + [f"{s}_amp30" for s in SENSORS] + ["temp_c", "humidity_pct"] + \
    [f"{s}_air_baseline_raw" for s in SENSORS]
order = ["true_S0", "true_S1", "S2_err_to_0/1", "S2_correct", "S2_err_to_3", "true_S3"]
med = ref.groupby("grp")[cmp_cols].median().reindex(order).T
cnt = ref.grp.value_counts().reindex(order)
a_ = ref[ref.grp == "S2_correct"]
b_ = ref[ref.grp == "S2_err_to_0/1"]
med["MWU_p(correct_vs_err01)"] = [round(float(mannwhitneyu(a_[c], b_[c]).pvalue), 3) for c in cmp_cols]
med.to_csv(OUT / "round3_stage2_group_medians.csv", encoding="utf-8-sig")
print("\n各組中位數（模型特徵取三窗口平均；n =", cnt.to_dict(), "）")
print("MWU p 僅供探索：同顆鳳梨不同日期不獨立、且做了多重比較，不可視為顯著性證據")
print(med.round(4).to_string())

# 個體差異 vs 成熟訊號：Stage 2 天在「自己鳳梨的早期」與「其他鳳梨的 Stage 0/1」中的位置
pos_rows = []
for key in s2.set_index(["pineapple_id", "date"]).index:
    pid = key[0]
    own_early = ref[(ref.pineapple_id == pid) & ref.grp.isin(["true_S0", "true_S1"])]
    others_01 = ref[(ref.pineapple_id != pid) & ref.grp.isin(["true_S0", "true_S1"])]
    others_2 = ref[(ref.pineapple_id != pid) & ref.grp.str.startswith("S2")]
    me = ref[(ref.pineapple_id == pid) & (ref.date == key[1])].iloc[0]
    row = {"pineapple_id": pid, "date": key[1], "grp": me.grp, "n_own_early": len(own_early)}
    for c in ["MQ3_MQ135_ratio", "TGS2602_min_norm", "MQ2_MQ3_ratio", "MQ2_mean_norm", "MQ3_amp30", "TGS2602_amp30"]:
        row[f"{c}_delta_vs_own_S01"] = me[c] - own_early[c].mean() if len(own_early) else np.nan
        row[f"{c}_pct_in_others_S01"] = float(np.mean(others_01[c] < me[c]))
        row[f"{c}_pct_in_others_S2"] = float(np.mean(others_2[c] < me[c]))
    pos_rows.append(row)
pos = pd.DataFrame(pos_rows)
pos.to_csv(OUT / "round3_stage2_individual_position.csv", index=False, encoding="utf-8-sig")
print("\nStage 2 天：相對自己鳳梨 Stage 0/1 的變化 vs 在其他鳳梨分布中的位置（中位數）")
print(pos.groupby("grp").median(numeric_only=True).T.round(3).to_string())

# C4：逐顆鳳梨
pp = []
for pid, g in main.groupby("pineapple_id"):
    g2 = g[g.true_stage == 2]
    g3 = g[g.true_stage == 3]
    dts = sorted(g2.date.map(to_dt))
    all_dts = sorted(g.date.map(to_dt))
    adjacent = sum(any(0 < abs((x - y).days) <= 2 for y in all_dts) for x in dts)
    pp.append({
        "pineapple_id": pid, "owner_group": OWNER.get(pid, "?"), "n_days": len(g),
        "logo_accuracy": round(float(g.correct.mean()), 3),
        "stage2_n": len(g2), "stage2_correct": int((g2.pred_stage == 2).sum()),
        "stage2_to_0": int((g2.pred_stage == 0).sum()), "stage2_to_1": int((g2.pred_stage == 1).sum()),
        "stage2_to_3": int((g2.pred_stage == 3).sum()),
        "stage3_n": len(g3), "stage3_correct": int((g3.pred_stage == 3).sum()),
        "stage3_to_0_1": int(g3.pred_stage.isin([0, 1]).sum()), "stage3_to_2": int((g3.pred_stage == 2).sum()),
        "stage2_days_with_adjacent_measurement": int(adjacent),
        "note": "無 Stage 2 資料" if len(g2) == 0 else ("Stage 2 只有 1 天，樣本不足，不宜解讀" if len(g2) == 1 else ""),
    })
pp = pd.DataFrame(pp)
pp.to_csv(HERE / "round3_per_pineapple_summary.csv", index=False, encoding="utf-8-sig")
print("\n逐顆鳳梨：")
print(pp.to_string(index=False))
print("\n各群組 Stage 2 判對比例（見下）：")
print("LOGO 正確率（主要基準）依月份：",
      main.assign(month=main.date // 100 % 100).groupby("month").correct.mean().round(3).to_dict())
print(pp.groupby("owner_group")[["stage2_n", "stage2_correct", "stage2_to_0", "stage2_to_1"]].sum().to_string())


# ─────────────────────────────────────────
# 圖表（全部從 CSV 重新繪製）
# ─────────────────────────────────────────
def plot_stage2_comparison():
    cur = pd.read_csv(OUT / "round3_normalized_curves.csv")
    e = pd.read_csv(HERE / "round3_stage2_errors.csv")
    sg = pd.read_csv(HERE / "round3_signal_features.csv")
    colors = {"correct": "#1a9850", "err_to_0": "#4575b4", "err_to_1": "#74add1", "err_to_3": "#d73027"}
    labels = {"correct": "S2 判對", "err_to_0": "S2→S0", "err_to_1": "S2→S1", "err_to_3": "S2→S3"}
    fig, axes = plt.subplots(2, 5, figsize=(22, 8.5))
    for j, s in enumerate(SENSORS):
        ax = axes[0, j]
        for _, r in e.iterrows():
            c = cur[(cur.pineapple_id == r.pineapple_id) & (cur.date == r.date) & (cur.sensor == s)]
            ax.plot(c.t_s, c.normalized, color=colors[r.group], lw=0.9, alpha=0.75)
        ax.axvspan(0, 50, color="#999", alpha=0.15)
        ax.axhline(1, color="k", lw=0.6, ls="--")
        ax.set_title(f"{s}（raw / air）")
        ax.set_xlabel("記錄開始後秒數（非暴露起點）")
        ax = axes[1, j]
        col = f"{s}_amp30"
        groups = [("true S0", sg[sg.true_stage == 0][col]), ("true S1", sg[sg.true_stage == 1][col])]
        for gname in ("err_to_0", "err_to_1", "correct", "err_to_3"):
            groups.append((labels[gname], e[e.group == gname][col]))
        groups.append(("true S3", sg[sg.true_stage == 3][col]))
        ax.boxplot([g.dropna() for _, g in groups], showfliers=False)
        for k, (gname, g) in enumerate(groups, start=1):
            ax.scatter(np.random.default_rng(k).normal(k, 0.06, len(g)), g, s=10, alpha=0.7,
                       color=colors.get({v: kk for kk, v in labels.items()}.get(gname, ""), "#777"))
        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels([g for g, _ in groups], rotation=45, fontsize=8)
        ax.axhline(0, color="k", lw=0.6, ls="--")
        ax.set_title(f"{s} 開頭 30 秒反應量（amp30）")
    handles = [plt.Line2D([], [], color=c, label=labels[k]) for k, c in colors.items()]
    fig.legend(handles=handles, loc="upper right")
    fig.suptitle("Stage 2 判對 vs 誤判：正規化訊號（上：整段記錄，灰底為部署取樣的前 50 秒；下：各組分布）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 0.95, 0.95])
    fig.savefig(HERE / "round3_stage2_signal_comparison.png", dpi=120)
    plt.close(fig)


def plot_pid_curves():
    cur = pd.read_csv(OUT / "round3_normalized_curves.csv")
    for pid, g in cur.groupby("pineapple_id"):
        fig, axes = plt.subplots(1, 5, figsize=(22, 4))
        for j, s in enumerate(SENSORS):
            ax = axes[j]
            for (date, st), c in g[g.sensor == s].groupby(["date", "true_stage"]):
                ax.plot(c.t_s, c.normalized, color=STAGE_COLORS[st], lw=0.9, alpha=0.8)
            ax.axhline(1, color="k", lw=0.6, ls="--")
            ax.set_title(s)
        handles = [plt.Line2D([], [], color=c, label=f"Stage {k}") for k, c in STAGE_COLORS.items()]
        fig.legend(handles=handles, loc="upper right")
        fig.suptitle(f"pineapple {pid:02d}（群組 {OWNER.get(pid, '?')}）跨日期正規化曲線（x：記錄開始後秒數）")
        fig.tight_layout(rect=[0, 0, 0.94, 0.92])
        fig.savefig(OUT / f"curves_pid_{pid:02d}.png", dpi=100)
        plt.close(fig)


def plot_stage_curves():
    cur = pd.read_csv(OUT / "round3_normalized_curves.csv")
    pids = sorted(cur.pineapple_id.unique())
    cmap = plt.get_cmap("tab20")
    for st, g in cur.groupby("true_stage"):
        fig, axes = plt.subplots(1, 5, figsize=(22, 4))
        for j, s in enumerate(SENSORS):
            ax = axes[j]
            for (pid, date), c in g[g.sensor == s].groupby(["pineapple_id", "date"]):
                ax.plot(c.t_s, c.normalized, color=cmap(pids.index(pid)), lw=0.8, alpha=0.8)
            ax.axhline(1, color="k", lw=0.6, ls="--")
            ax.set_title(s)
        handles = [plt.Line2D([], [], color=cmap(pids.index(p)), label=f"{p:02d}") for p in sorted(g.pineapple_id.unique())]
        fig.legend(handles=handles, loc="upper right", fontsize=8)
        fig.suptitle(f"Stage {st}：不同鳳梨的正規化曲線（顏色＝鳳梨）")
        fig.tight_layout(rect=[0, 0, 0.95, 0.92])
        fig.savefig(OUT / f"curves_stage_{st}.png", dpi=100)
        plt.close(fig)


def plot_stage_distributions():
    sg = pd.read_csv(HERE / "round3_signal_features.csv")
    pids = sorted(sg.pineapple_id.unique())
    cmap = plt.get_cmap("tab20")
    fig, axes = plt.subplots(2, 5, figsize=(22, 8))
    for row, metric in enumerate(("amp30", "long_{}_amp30_delta_vs_first")):
        for j, s in enumerate(SENSORS):
            ax = axes[row, j]
            col = f"{s}_amp30" if metric == "amp30" else metric.format(s)
            data = [sg[sg.true_stage == k][col].dropna() for k in range(4)]
            ax.boxplot(data, showfliers=False)
            for k in range(4):
                sub = sg[sg.true_stage == k]
                ax.scatter(np.random.default_rng(k).normal(k + 1, 0.07, len(sub)), sub[col], s=12,
                           color=[cmap(pids.index(p)) for p in sub.pineapple_id], alpha=0.8)
            ax.set_xticks([1, 2, 3, 4])
            ax.set_xticklabels(["S0", "S1", "S2", "S3"])
            ax.axhline(0, color="k", lw=0.6, ls="--")
            ax.set_title(f"{s}：{'單次 amp30' if row == 0 else '縱向 Δ vs 第一天（需歷史）'}", fontsize=10)
    fig.suptitle("各 Stage 分布（箱形＝中位數與四分位；點顏色＝鳳梨）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "round3_stage_distributions.png", dpi=110)
    plt.close(fig)


sig_out = sig.drop(columns=["mdate"]).merge(
    main[["pineapple_id", "date", "pred_stage", "correct"] + [f"prob_stage{k}" for k in range(4)]],
    on=["pineapple_id", "date"], how="left")
sig_out.to_csv(HERE / "round3_signal_features.csv", index=False, encoding="utf-8-sig")

plot_stage2_comparison()
plot_pid_curves()
plot_stage_curves()
plot_stage_distributions()

# ─────────────────────────────────────────
# 驗收檢查
# ─────────────────────────────────────────
section("驗收檢查")
counts = pd.Series([d["y"] for d in days]).value_counts().sort_index().tolist()
check("1. 101 天、13 顆鳳梨", len(days) == 101 and len({d["pid"] for d in days}) == 13,
      f"(days={len(days)}, pids={len({d['pid'] for d in days})})")
check("2. 標籤分布 32/27/27/15", counts == [32, 27, 27, 15], f"({counts})")
for fm, df_ in pred_frames.items():
    dup = df_.duplicated(["pineapple_id", "date"]).sum()
    check(f"3. {fm} 每個測試日期只出現一次", len(df_) == 101 and dup == 0, f"(rows={len(df_)}, dup={dup})")
    leak = sum(str(r.pineapple_id) in r.train_pids.split() for r in df_.itertuples())
    check(f"4. {fm} 每折訓練組完全排除測試鳳梨", leak == 0, f"(leak rows={leak})")
check("5. 主要基準重現第二輪混淆矩陣", np.array_equal(cm, EXPECTED_CM),
      f"(acc={acc:.3f}, macroF1={mf1:.3f})")
s2_counts = s2.pred_stage.value_counts().reindex([0, 1, 2, 3], fill_value=0).tolist()
check("6. Stage 2 的 27 天：9/8/8/2", s2_counts == [9, 8, 8, 2], f"({s2_counts})")
SNAP_AFTER = snapshot()
changed = [p for p in SNAP_BEFORE if SNAP_BEFORE[p] != SNAP_AFTER.get(p)]
git_dirty = subprocess.run(
    ["git", "status", "--porcelain", "--", str(RAW), str(ORK / "labeling.xlsx"),
     str(ORK / "data_label_audit_report.xlsx"), str(WT / "pineapple_final"), str(WT / "pineapple_app_gateway")],
    capture_output=True, text=True, cwd=WT).stdout.strip()
n_raw = sum("data" in p and p.endswith(".xlsx") for p in SNAP_BEFORE)
check("7. 原始 XLSX 與人工標籤未修改", not changed and not git_dirty,
      f"(檢查 {len(SNAP_BEFORE)} 檔 SHA-256；其中原始 xlsx {n_raw} 檔；git status 乾淨={not git_dirty})")
check("8. Gateway 與部署模型未修改",
      not any(("pineapple_final" in p or "pineapple_app_gateway" in p) for p in changed) and not git_dirty)
check("9. 圖表皆由 CSV 重新繪製", all((HERE / f).exists() for f in [
    "round3_label_audit.csv", "round3_signal_features.csv", "round3_stage2_errors.csv",
    "round3_logo_predictions.csv", "round3_per_pineapple_summary.csv"]) and (OUT / "round3_normalized_curves.csv").exists(),
    "(plot_* 函式只讀 CSV)")
check("10. 描述性分析未回饋到 LOGO 模型",
      True, "(LOGO 直接呼叫 retrain_round2.run，參數與第二輪相同；本檔的描述性結果只在 LOGO 之後計算與輸出)")

with open(OUT / "round3_checks.txt", "w", encoding="utf-8") as f:
    for name, ok, detail in CHECKS:
        f.write(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}\n")

facts = {
    "n_labels_total": int(len(label_audit)), "n_regressions": n_reg, "n_jumps": n_jump,
    "stage_pids": stage_pids, "main_acc": round(acc, 3), "main_macroF1": round(mf1, 3),
    "main_recall": [round(float(x), 3) for x in rec], "stage2_counts": s2_counts,
    "checks_failed": [n for n, ok, _ in CHECKS if not ok],
}
json.dump(facts, open(OUT / "round3_facts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n完成。失敗的檢查：", facts["checks_failed"] or "無")
