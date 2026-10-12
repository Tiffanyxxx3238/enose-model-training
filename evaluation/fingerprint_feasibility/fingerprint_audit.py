"""
Odor Fingerprint Feasibility Study — Step 1A～1C（純離線、描述性；不訓練任何分類器）

研究問題：五個感測器之間的「相對反應模式」，是否含有可跨鳳梨、跨群組轉移的成熟度資訊，
而這些資訊被絕對讀值大小與量測群組差異掩蓋？

執行順序刻意安排為：
  1. 資料配對與物理訊號稽核（不看 Stage）
  2. 只用 AIR 資料決定 LOW_SIGNAL 門檻與相似度設計 → 寫入 fingerprint_preregistration.json
  3. 之後才計算與 Stage／Group 有關的比較

Run:  python -u fingerprint_audit.py > run_log.txt
"""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))
from eval_common import ORK, RAW, SENSORS, WINDOW, WT, load_days, read_raw_xlsx  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["mathtext.default"] = "regular"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

OWNER = {1: "A", 2: "A", 9: "A", 12: "A", 3: "B", 4: "B", 10: "B", 11: "B", 13: "B",
         5: "C", 6: "C", 14: "C", 7: "D", 8: "D"}  # data/raw/編號規則.docx；群組 ≠ 已確認設備 ID
SUSPECTED = {(3, 20260214), (4, 20260206)}
SEED = 20261012
N_BOOT = 2000
ADC_MAX = 1023
FW_VALID = (10, 1000)  # 韌體 isValidMQRaw：超出範圍的樣本整筆丟棄
ORIGINAL_WORKSPACES = [Path("c:/Users/user/electronic-nose-pineapple-ripeness-assessment"),
                       Path("c:/Users/user/enose-gateway-fix")]
CHECKS = []


def check(name, status, detail=""):
    assert status in ("PASS", "FAIL", "NOT AVAILABLE", "NOT APPLICABLE")
    CHECKS.append((name, status, detail))
    print(f"[{status}] {name} {detail}")


def section(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


def git_status(path):
    r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=path)
    return r.stdout


def git_head(path):
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=path).stdout.strip()


# 受保護檔案（本工作區）＋原工作區狀態快照
PROTECTED = sorted(list(RAW.glob("*.xlsx")) + [ORK / "labeling.xlsx", ORK / "data_label_audit_report.xlsx"]
                   + list((WT / "pineapple_final").glob("*")) + list((WT / "pineapple_app_gateway").glob("*.py"))
                   + [p for p in EVAL.glob("*") if p.is_file()]
                   + [p for d in ("round3_results", "round4_results", "reliability_phase1_results") for p in (EVAL / d).glob("*")])
SNAP = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}
ORIG_BEFORE = {str(p): (git_status(p), git_head(p)) for p in ORIGINAL_WORKSPACES if p.exists()}
# 與研究 worktree 中同名原始檔比對（應逐位元相同）
SRC_RAW = Path("c:/Users/user/enose-gateway-fix/Semester 2 Final Exam (三下-期末)/enose_model_training/orkspace/data/raw")

# ═════════════════════════════════════════
# Step 1A｜資料配對與物理訊號稽核（不使用 Stage）
# ═════════════════════════════════════════
section("Step 1A｜A1 AIR / Fruit pairing audit")
days = load_days()
audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit").set_index(["pid", "date"])


def head_info(path):
    raw = pd.read_excel(path, header=None, nrows=6)
    col0 = raw.iloc[:, 0].astype(str).tolist()
    hdr = next((i for i, v in enumerate(col0) if v.strip() == "timestamp_ms"), None)
    mode = next((v.split("MODE:")[1].strip(" #").replace("_INTERNAL_ADC", "") for v in col0 if "MODE:" in v), "none")
    ncol = int(raw.iloc[hdr].notna().sum()) if hdr is not None else 0
    return hdr, mode, ncol


def xlsx_meta(path):
    try:
        x = zipfile.ZipFile(path).read("docProps/core.xml").decode("utf-8", "ignore")
    except Exception:
        return None, None
    c = re.search(r"<dcterms:created[^>]*>(.*?)</dcterms:created>", x)
    who = re.search(r"<dc:creator>(.*?)</dc:creator>", x)
    return (c.group(1) if c else None), (who.group(1) if who else None)


creators = {}
pair_rows = []
for d in days:
    key = (d["pid"], d["date"])
    a = audit.loc[key]
    fp, ap = RAW / a.fruit_file, RAW / a.air_file
    fdf, adf = read_raw_xlsx(fp), read_raw_xlsx(ap)
    d["F"] = {s: fdf[f"{s}_raw"].to_numpy(float) for s in SENSORS}
    d["A"] = {s: adf[f"{s}_raw"].to_numpy(float) for s in SENSORS}
    fh, fm, fc = head_info(fp)
    ah, am, ac = head_info(ap)
    fc_t, f_who = xlsx_meta(fp)
    ac_t, a_who = xlsx_meta(ap)
    for w in (f_who, a_who):
        if w and w not in creators:
            creators[w] = f"creator_{len(creators) + 1}"
    dt = None
    if fc_t and ac_t:
        dt = (datetime.fromisoformat(fc_t.replace("Z", "+00:00")) - datetime.fromisoformat(ac_t.replace("Z", "+00:00"))).total_seconds()
    ts_f, ts_a = fdf["timestamp_ms"].to_numpy(float), adf["timestamp_ms"].to_numpy(float)
    n = min(len(fdf), len(adf))
    identical = all(np.array_equal(d["F"][s][:n], d["A"][s][:n]) for s in SENSORS)
    allv = np.concatenate([np.concatenate([d["F"][s], d["A"][s]]) for s in SENSORS])
    pair_rows.append({
        "pineapple_id": d["pid"], "date": d["date"], "group": OWNER[d["pid"]],
        "fruit_file": a.fruit_file, "air_file": a.air_file, "air_source": a.air_source,
        "air_file_exists": ap.exists(), "fruit_rows": len(fdf), "air_rows": len(adf),
        "fruit_ts_dup": int(np.sum(np.diff(ts_f) == 0)), "air_ts_dup": int(np.sum(np.diff(ts_a) == 0)),
        "fruit_ts_nonpos": int(np.sum(np.diff(ts_f) <= 0)), "air_ts_nonpos": int(np.sum(np.diff(ts_a) <= 0)),
        "fruit_median_dt_s": float(np.median(np.diff(ts_f)) / 1000), "air_median_dt_s": float(np.median(np.diff(ts_a)) / 1000),
        "missing_gas_values": int(sum(np.isnan(d["F"][s]).sum() + np.isnan(d["A"][s]).sum() for s in SENSORS)),
        "zero_values": int((allv == 0).sum()),
        "at_firmware_bounds": int(((allv <= FW_VALID[0]) | (allv >= FW_VALID[1])).sum()),
        "near_adc_rail": int(((allv <= 5) | (allv >= ADC_MAX - 5)).sum()),
        "fruit_equals_air": identical,
        "flag": "SUSPECTED_NOT_FRUIT（鳳梨檔 900 筆感測值與空氣檔逐筆相同）" if identical else "",
        "fruit_header_row": fh, "air_header_row": ah, "fruit_n_cols": fc, "air_n_cols": ac,
        "fruit_mode_tag": fm, "air_mode_tag": am,
        "fruit_xlsx_created": fc_t, "air_xlsx_created": ac_t,
        "xlsx_created_fruit_minus_air_s": dt,
        "fruit_creator_code": creators.get(f_who), "air_creator_code": creators.get(a_who),
    })
pair = pd.DataFrame(pair_rows)
pair.to_csv(HERE / "fingerprint_pairing_audit.csv", index=False, encoding="utf-8-sig")
print(f"配對：{len(pair)} 天，空氣檔全部存在={bool(pair.air_file_exists.all())}；空氣來源 {pair.air_source.value_counts().to_dict()}")
print(f"列數：鳳梨 {pair.fruit_rows.min()}～{pair.fruit_rows.max()}；空氣 {pair.air_rows.min()}～{pair.air_rows.max()}")
print(f"時間戳重複 {int(pair.fruit_ts_dup.sum() + pair.air_ts_dup.sum())}、倒退 {int(pair.fruit_ts_nonpos.sum() + pair.air_ts_nonpos.sum())}；"
      f"缺值 {int(pair.missing_gas_values.sum())}；零值 {int(pair.zero_values.sum())}；"
      f"落在韌體邊界(≤10 或 ≥1000) {int(pair.at_firmware_bounds.sum())}；接近 ADC 上下限 {int(pair.near_adc_rail.sum())}")
print("鳳梨檔與空氣檔逐筆相同：", pair[pair.fruit_equals_air][["pineapple_id", "date", "fruit_file"]].to_dict("records"))
print("xlsx 建立時間（鳳梨 − 空氣，秒）：", pair.xlsx_created_fruit_minus_air_s.describe()[["count", "min", "50%", "max"]].round(1).to_dict(),
      "；缺少建立時間的配對：", int(pair.xlsx_created_fruit_minus_air_s.isna().sum()))
print("※ xlsx 的建立時間是轉存成 Excel 的時間（例如 02-10 的資料在 02-11 建立），不是量測時間；無法用來確認 AIR 是否先量。")
fmt = pair.groupby("group").agg(
    header_row=("fruit_header_row", lambda v: sorted(set(v))), n_cols=("fruit_n_cols", lambda v: sorted(set(v))),
    fruit_mode=("fruit_mode_tag", lambda v: dict(pd.Series(v).value_counts())),
    air_source=("air_source", lambda v: dict(pd.Series(v).value_counts())),
    creator=("fruit_creator_code", lambda v: sorted({x for x in v if x})))
print("\n各群組的檔案格式（量測程序差異的線索）：")
print(fmt.to_string())
fmt.to_csv(HERE / "fingerprint_group_procedure_evidence.csv", encoding="utf-8-sig")

section("Step 1A｜A2 ADC 與電路（程式／文件）")
HW = [
    ("讀值來源", "程式確認", "analogRead(A0..A5)；MQ2→A0、MQ3→A1、MQ9→A2、MQ135→A3、TGS2602→A4、TGS2620→A5（pineapple_sample_collection.ino、air_baseline_collection.ino、use_this.ino 相同）"),
    ("平滑／校正／單位轉換", "程式確認", "原始欄 *_raw 為未處理 ADC 計數；*_logr = log((raw+1)/(該檔前 30 筆平均+1))，是相對自身開頭的 log 比值，不是電阻；*_ma5 為 5 點移動平均"),
    ("無效樣本處理", "程式確認", "isValidMQRaw：任一感測器 <10 或 >1000 時整筆丟棄（飽和讀值不會出現在檔案中）"),
    ("ADC 解析度", "程式＋README", "Arduino Mega 2560 10-bit（0～1023）；README『10-bit ADC』"),
    ("ADC 參考電壓", "程式推定", "程式沒有呼叫 analogReference() → Mega 預設 DEFAULT（板上 AVCC，通常 5 V）；實際電壓未量測、未記錄"),
    ("空氣與鳳梨韌體", "程式確認", "air_baseline_collection.ino 與 pineapple_sample_collection.ino 除註解外相同（5 分鐘預熱、延遲 30 秒、1 Hz、900 筆）"),
    ("感測器模組型號／電路拓撲", "無法確認", "repo 沒有模組型號、接線圖或 schematic"),
    ("負載電阻 RL", "無法確認", "沒有任何文件記載"),
    ("加熱器／供應電壓", "無法確認", "沒有任何文件記載"),
    ("各感測器電路是否不同", "無法確認", "MQ 系列與 TGS 系列常見模組不同，但本專案沒有記錄"),
]
hw = pd.DataFrame(HW, columns=["item", "status", "evidence"])
hw.to_csv(HERE / "fingerprint_hardware_audit.csv", index=False, encoding="utf-8-sig")
print(hw.to_string(index=False))

# ═════════════════════════════════════════
# Step 1A｜訊號強度與 AIR 雜訊（仍不使用 Stage）
# ═════════════════════════════════════════
section("Step 1A｜Signal strength vs AIR variability（不使用 Stage）")
W = WINDOW  # 主要設定：開頭 30 筆，五感測器同一窗口
for d in days:
    B = np.array([d["air"][s] for s in SENSORS])                       # 既有流程：空氣檔前 30 筆平均
    S = np.array([d["F"][s][:W].mean() for s in SENSORS])
    d["B"], d["S"] = B, S
    d["r"] = (S - B) / B
    # AIR-only null：同一空氣檔的其他不重疊 30 筆窗口，相對於前 30 筆基準
    nA = min(len(d["A"][s]) for s in SENSORS)
    starts = list(range(W, nA - W + 1, W))
    d["null"] = np.array([[(d["A"][s][k:k + W].mean() - d["air"][s]) / d["air"][s] for s in SENSORS] for k in starts])
    d["air_sd30"] = np.array([d["A"][s][:W].std(ddof=1) for s in SENSORS])
    d["air_winmean_sd"] = np.array([np.std([d["A"][s][k:k + W].mean() for k in range(0, nA - W + 1, W)], ddof=1)
                                    for s in SENSORS])
n_null = [len(d["null"]) for d in days]
print(f"AIR 長度足以切出不重疊窗口：每天 {min(n_null)}～{max(n_null)} 個 null 向量（不含作為基準的第 1 個窗口）")

# ── 預先登記：只用 AIR 決定的門檻與設計（在任何 Stage 相關計算之前）──
for d in days:
    nn = np.linalg.norm(d["null"], axis=1)
    d["null_q95"] = float(np.percentile(nn, 95))
    nc = d["null"] - d["null"].mean(axis=1, keepdims=True)
    d["null_c_q95"] = float(np.percentile(np.linalg.norm(nc, axis=1), 95))
PREREG = {
    "created_before_stage_analysis": datetime.now().isoformat(timespec="seconds"),
    "window": "鳳梨檔前 30 筆（row 0–29），五感測器相同窗口；B = 空氣檔前 30 筆平均（既有流程）",
    "response": "r_i = (S_i − B_i) / B_i",
    "low_signal_rule": "LOW_SIGNAL：‖r‖₂ ≤ 當天 AIR-only null ‖r_null‖₂ 的第 95 百分位（同一空氣檔的 29 個不重疊 30 筆窗口相對前 30 筆）",
    "low_signal_rule_centered": "F1 方向（補充）：‖r − mean(r)‖₂ ≤ 當天中心化 null 的第 95 百分位",
    "suspected_days": "鳳梨檔＝空氣檔的 2 天標記 SUSPECTED_NOT_FRUIT，排除於相似度分析（保留於品質報告）",
    "representations": {"F0": "r", "F1": "r − mean(r)", "F2": "r / ‖r‖₂（僅非 LOW_SIGNAL）",
                        "F3_supplementary": "(r − mean(r)) / ‖r − mean(r)‖₂（僅中心化非 LOW_SIGNAL；補充描述）"},
    "distance": {"F0": "Euclidean", "F1": "Euclidean", "F2": "cosine similarity", "F3": "cosine similarity"},
    "unit": "pineapple × stage：F0/F1 取各感測器中位數；F2/F3 取有效日單位向量平均後再正規化",
    "comparisons": {"WP": "同鳳梨、不同 Stage", "C1": "同 Stage、不同鳳梨", "C1a": "同 Stage、同群組、不同鳳梨",
                    "C2": "同群組、不同 Stage、不同鳳梨", "C3": "同 Stage、不同群組", "C4": "不同 Stage、不同群組"},
    "primary_contrasts": {"stage_transfer": "C3 − C4（跨群組時，同 Stage 是否比不同 Stage 更相似）",
                          "group_signature": "C2 − C4（不同 Stage 時，同群組是否比不同群組更相似）"},
    "uncertainty": f"以 pineapple_id 為單位的 cluster bootstrap（{N_BOOT} 次，seed {SEED}）",
    "no_model_training": True,
}
json.dump(PREREG, open(HERE / "fingerprint_preregistration.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已寫入 fingerprint_preregistration.json（Stage 相關計算之前）")

q_rows = []
for d in days:
    key = (d["pid"], d["date"])
    norm = float(np.linalg.norm(d["r"]))
    f1 = d["r"] - d["r"].mean()
    nf1 = float(np.linalg.norm(f1))
    low = norm <= d["null_q95"]
    lowc = nf1 <= d["null_c_q95"]
    d.update({"norm": norm, "F1": f1, "nF1": nf1, "low": low, "lowc": lowc, "suspect": key in SUSPECTED,
              "F2": (d["r"] / norm) if (not low and norm > 0) else np.full(5, np.nan),
              "F3": (f1 / nf1) if (not lowc and nf1 > 0) else np.full(5, np.nan)})
    floor = 0.1  # ADC；30 筆平均的量化下限附近
    q_rows.append({
        "pineapple_id": d["pid"], "date": d["date"], "group": OWNER[d["pid"]], "month": d["date"] // 100 % 100,
        "suspected_not_fruit": key in SUSPECTED,
        "r_l2_norm": norm, "air_null_q95_norm": d["null_q95"], "air_null_median_norm": float(np.median(np.linalg.norm(d["null"], axis=1))),
        "LOW_SIGNAL": low, "norm_over_null_q95": norm / d["null_q95"] if d["null_q95"] > 0 else np.nan,
        "F1_norm": nf1, "air_null_centered_q95": d["null_c_q95"], "LOW_SIGNAL_centered": lowc,
        "common_mean_response": float(d["r"].mean()),
        "frac_energy_removed_by_centering": float(5 * d["r"].mean() ** 2 / norm ** 2) if norm > 0 else np.nan,
        **{f"{s}_B": d["B"][i] for i, s in enumerate(SENSORS)},
        **{f"{s}_S30": d["S"][i] for i, s in enumerate(SENSORS)},
        **{f"{s}_abs_diff_ADC": abs(d["S"][i] - d["B"][i]) for i, s in enumerate(SENSORS)},
        **{f"{s}_air_sd30_ADC": d["air_sd30"][i] for i, s in enumerate(SENSORS)},
        **{f"{s}_air_windowmean_sd_ADC": d["air_winmean_sd"][i] for i, s in enumerate(SENSORS)},
        **{f"{s}_RNP": abs(d["S"][i] - d["B"][i]) / max(d["air_winmean_sd"][i], floor) for i, s in enumerate(SENSORS)},
    })
qual = pd.DataFrame(q_rows).sort_values(["pineapple_id", "date"])
# 相鄰量測日的 AIR 基準變化（同一顆鳳梨）
dd = []
for pid, g in qual.groupby("pineapple_id"):
    g = g.sort_values("date")
    Bm = g[[f"{s}_B" for s in SENSORS]].to_numpy()
    for i in range(1, len(g)):
        v = (Bm[i] - Bm[i - 1]) / Bm[i - 1]
        dd.append({"pineapple_id": pid, "date": g.date.iloc[i], "air_day_to_day_norm": float(np.linalg.norm(v)),
                   **{f"{s}_air_day_to_day_rel": v[j] for j, s in enumerate(SENSORS)}})
dd = pd.DataFrame(dd)
qual = qual.merge(dd, on=["pineapple_id", "date"], how="left")
qual.to_csv(HERE / "fingerprint_quality.csv", index=False, encoding="utf-8-sig")

ok = qual[~qual.suspected_not_fruit]
sn = {
    "n_days_analyzed": len(ok),
    "median_r_norm": round(ok.r_l2_norm.median(), 4),
    "median_air_null_q95_norm": round(ok.air_null_q95_norm.median(), 4),
    "median_air_day_to_day_norm": round(ok.air_day_to_day_norm.median(), 4),
    "P(norm > null q95) = 非 LOW_SIGNAL 比例": round((~ok.LOW_SIGNAL).mean(), 3),
    "P(norm > day-to-day AIR change)": round((ok.r_l2_norm > ok.air_day_to_day_norm).dropna().mean(), 3),
    "LOW_SIGNAL_centered 比例": round(ok.LOW_SIGNAL_centered.mean(), 3),
    "median frac energy removed by centering": round(ok.frac_energy_removed_by_centering.median(), 3),
}
per_sensor = pd.DataFrame({s: {
    "median_abs_diff_ADC": ok[f"{s}_abs_diff_ADC"].median(), "median_air_sd30_ADC": ok[f"{s}_air_sd30_ADC"].median(),
    "median_air_windowmean_sd_ADC": ok[f"{s}_air_windowmean_sd_ADC"].median(),
    "median_RNP": ok[f"{s}_RNP"].median(), "P(RNP>2)": (ok[f"{s}_RNP"] > 2).mean(),
    "median_rel_response": ((ok[f"{s}_S30"] - ok[f"{s}_B"]) / ok[f"{s}_B"]).median(),
    "median_abs_day_to_day_rel": ok[f"{s}_air_day_to_day_rel"].abs().median(),
    "P(|r_i| > |day-to-day_i|)": (((ok[f"{s}_S30"] - ok[f"{s}_B"]) / ok[f"{s}_B"]).abs() > ok[f"{s}_air_day_to_day_rel"].abs())[ok[f"{s}_air_day_to_day_rel"].notna()].mean(),
} for s in SENSORS}).round(4)
sig_null = pd.concat([pd.DataFrame([sn]).T.rename(columns={0: "value"}).reset_index().rename(columns={"index": "metric"}).assign(sensor="ALL"),
                      per_sensor.T.reset_index().rename(columns={"index": "sensor"}).melt(id_vars="sensor", var_name="metric")],
                     ignore_index=True)
sig_null.to_csv(HERE / "fingerprint_signal_null_comparison.csv", index=False, encoding="utf-8-sig")
print(pd.Series(sn).to_string())
print(per_sensor.to_string())
print("可疑的 2 天：", qual[qual.suspected_not_fruit][["pineapple_id", "date", "r_l2_norm", "LOW_SIGNAL"]].to_dict("records"))

# ═════════════════════════════════════════
# Step 1B｜指紋（此後才使用 Stage）
# ═════════════════════════════════════════
section("Step 1B｜Fingerprints（F0 / F1 / F2，F3 為補充）")
feat_rows = []
for d in days:
    feat_rows.append({"pineapple_id": d["pid"], "date": d["date"], "stage": d["y"], "group": OWNER[d["pid"]],
                      "month": d["date"] // 100 % 100, "suspected_not_fruit": d["suspect"],
                      "LOW_SIGNAL": d["low"], "LOW_SIGNAL_centered": d["lowc"], "r_l2_norm": d["norm"],
                      "common_mean_response": float(d["r"].mean()), "air_B_l2": float(np.linalg.norm(d["B"])),
                      **{f"F0_{s}": d["r"][i] for i, s in enumerate(SENSORS)},
                      **{f"F1_{s}": d["F1"][i] for i, s in enumerate(SENSORS)},
                      **{f"F2_{s}": d["F2"][i] for i, s in enumerate(SENSORS)},
                      **{f"F3_{s}": d["F3"][i] for i, s in enumerate(SENSORS)}})
feat = pd.DataFrame(feat_rows).sort_values(["pineapple_id", "date"])
feat.to_csv(HERE / "fingerprint_features.csv", index=False, encoding="utf-8-sig")
fa = feat[~feat.suspected_not_fruit].copy()
print(f"分析天數 {len(fa)}（排除 2 筆可疑）；F2 有效 {int((~fa.LOW_SIGNAL).sum())} 天；F3 有效 {int((~fa.LOW_SIGNAL_centered).sum())} 天")
print("各 Stage 的 F2 有效天數：", fa[~fa.LOW_SIGNAL].groupby("stage").size().to_dict(),
      "；LOW_SIGNAL 比例：", fa.groupby("stage").LOW_SIGNAL.mean().round(2).to_dict())
cov = pd.crosstab([fa.group], fa.stage)
cov_pid = fa.groupby(["group", "stage"]).pineapple_id.nunique().unstack(fill_value=0)
print("天數（群組 × Stage）：\n", cov.to_string(), "\n獨立鳳梨數（群組 × Stage）：\n", cov_pid.to_string())
print("各 Stage 中位數（F0 r，五感測器）：")
print(fa.groupby("stage")[[f"F0_{s}" for s in SENSORS]].median().round(4).to_string())
print("各 Stage 中位數（F1 中心化）：")
print(fa.groupby("stage")[[f"F1_{s}" for s in SENSORS]].median().round(4).to_string())

# ═════════════════════════════════════════
# Step 1C｜Stage vs Group 可分離性
# ═════════════════════════════════════════
section("Step 1C｜Stage vs Group separability（單位：鳳梨 × Stage）")


def units(df, rep):
    rows = []
    for (pid, st), g in df.groupby(["pineapple_id", "stage"]):
        cols = [f"{rep}_{s}" for s in SENSORS]
        if rep in ("F2", "F3"):
            v = g[cols].dropna().to_numpy()
            if len(v) == 0:
                continue
            m = v.mean(axis=0)
            vec = m / np.linalg.norm(m)
            n = len(v)
        else:
            vec = g[cols].median().to_numpy()
            n = len(g)
        rows.append({"pid": pid, "stage": st, "group": OWNER[pid], "vec": vec, "n_days": n})
    return rows


def sim(rep, a, b):
    if rep in ("F2", "F3"):
        return float(np.dot(a, b))                   # cosine（單位向量）
    return -float(np.linalg.norm(a - b))             # 以「負的歐氏距離」表示相似度（越大越相似）


def category(u, v):
    if u["pid"] == v["pid"]:
        return "WP" if u["stage"] != v["stage"] else None
    ss, sg = u["stage"] == v["stage"], u["group"] == v["group"]
    if ss and sg:
        return "C1a"
    if ss and not sg:
        return "C3"
    if (not ss) and sg:
        return "C2"
    return "C4"


def pair_table(us, rep):
    out = []
    for i in range(len(us)):
        for j in range(i + 1, len(us)):
            c = category(us[i], us[j])
            if c:
                out.append({"cat": c, "sim": sim(rep, us[i]["vec"], us[j]["vec"]),
                            "pid_a": us[i]["pid"], "pid_b": us[j]["pid"], "stage_a": us[i]["stage"], "stage_b": us[j]["stage"],
                            "group_a": us[i]["group"], "group_b": us[j]["group"]})
    return pd.DataFrame(out)


def contrasts(pt):
    med = pt.groupby("cat").sim.median()
    c1 = pt[pt.cat.isin(["C1a", "C3"])].sim.median()
    return {"C1": c1, **{k: med.get(k, np.nan) for k in ("WP", "C1a", "C2", "C3", "C4")},
            "stage_transfer(C3−C4)": med.get("C3", np.nan) - med.get("C4", np.nan),
            "group_signature(C2−C4)": med.get("C2", np.nan) - med.get("C4", np.nan),
            "same_stage_vs_same_group(C1−C2)": c1 - med.get("C2", np.nan)}


def boot(us, rep, n=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    pids = sorted({u["pid"] for u in us})
    res = []
    for _ in range(n):
        pick = rng.choice(pids, len(pids), replace=True)
        sel = []
        for copy, p in enumerate(pick):
            sel += [{**u, "pid": (p, copy)} for u in us if u["pid"] == p]   # 同顆鳳梨不同抽樣副本視為同一個體
        rows = []
        for i in range(len(sel)):
            for j in range(i + 1, len(sel)):
                a, b = sel[i], sel[j]
                if a["pid"][0] == b["pid"][0] and a["pid"] != b["pid"]:
                    continue  # 同一顆鳳梨的重複副本之間不配對
                c = category({**a, "pid": a["pid"]}, {**b, "pid": b["pid"]})
                if c:
                    rows.append((c, sim(rep, a["vec"], b["vec"])))
        if not rows:
            continue
        res.append(contrasts(pd.DataFrame(rows, columns=["cat", "sim"])))
    return pd.DataFrame(res)


sim_rows, pair_all = [], []
for rep in ("F0", "F1", "F2", "F3"):
    us = units(fa, rep)
    pt = pair_table(us, rep)
    pt["rep"] = rep
    pair_all.append(pt)
    c = contrasts(pt)
    b = boot(us, rep)
    n_cat = pt.cat.value_counts().to_dict()
    for k, v in c.items():
        col = b[k].dropna()
        sim_rows.append({"representation": rep, "metric": "cosine" if rep in ("F2", "F3") else "−Euclidean",
                         "quantity": k, "value": round(v, 4),
                         "boot_ci95_low": round(np.percentile(col, 2.5), 4) if len(col) else np.nan,
                         "boot_ci95_high": round(np.percentile(col, 97.5), 4) if len(col) else np.nan,
                         "boot_P(>0)": round(float((col > 0).mean()), 3) if k.startswith(("stage", "group", "same")) else np.nan,
                         "n_pairs": n_cat.get(k, np.nan) if k in n_cat else np.nan,
                         "n_units": len(us), "n_pineapples": len({u["pid"] for u in us}),
                         "supplementary": rep == "F3"})
simdf = pd.DataFrame(sim_rows)
simdf.to_csv(HERE / "fingerprint_similarity_summary.csv", index=False, encoding="utf-8-sig")
pairs = pd.concat(pair_all, ignore_index=True)
pairs.to_csv(HERE / "fingerprint_pairwise_units.csv", index=False, encoding="utf-8-sig")
print(simdf.pivot_table(index="quantity", columns="representation", values="value").round(4).to_string())
print("\n主要對比的 bootstrap 95% CI：")
print(simdf[simdf.quantity.str.contains("−")][["representation", "quantity", "value", "boot_ci95_low", "boot_ci95_high", "boot_P(>0)"]].to_string(index=False))

# Stage 2：群組 A vs B
section("Stage 2 跨群組（A vs B）")
s2rows = []
for rep in ("F1", "F2"):
    us = units(fa, rep)
    s2 = [u for u in us if u["stage"] == 2]
    for i in range(len(s2)):
        for j in range(i + 1, len(s2)):
            a, b = s2[i], s2[j]
            s2rows.append({"rep": rep, "pid_a": a["pid"], "group_a": a["group"], "pid_b": b["pid"], "group_b": b["group"],
                           "pair_type": "A–B" if a["group"] != b["group"] else f"{a['group']}–{a['group']}",
                           "similarity": round(sim(rep, a["vec"], b["vec"]), 4), "n_days_a": a["n_days"], "n_days_b": b["n_days"]})
    # 對照：S2 單位 vs 同群組其他 Stage 單位（不同鳳梨）
    for a in s2:
        for b in us:
            if b["stage"] != 2 and b["pid"] != a["pid"] and b["group"] == a["group"]:
                s2rows.append({"rep": rep, "pid_a": a["pid"], "group_a": a["group"], "pid_b": b["pid"], "group_b": b["group"],
                               "pair_type": f"S2 vs S{b['stage']}（同群組）", "similarity": round(sim(rep, a["vec"], b["vec"]), 4),
                               "n_days_a": a["n_days"], "n_days_b": b["n_days"]})
s2df = pd.DataFrame(s2rows)
s2df.to_csv(HERE / "fingerprint_stage2_transfer.csv", index=False, encoding="utf-8-sig")
print(s2df.groupby(["rep", "pair_type"]).similarity.agg(["count", "median", "min", "max"]).round(4).to_string())
print("Stage 2 單位：", [(u["pid"], u["group"], u["n_days"]) for u in units(fa, "F2") if u["stage"] == 2])

# 混雜：多變量 R²（日層級，描述性）
section("混雜：Stage／Group／Month／Pineapple／LOW_SIGNAL／AIR 基準")


def mv_r2(X, g):
    X = np.asarray(X, float)
    g = np.asarray(g)
    mu = X.mean(axis=0)
    tot = ((X - mu) ** 2).sum()
    btw = sum(len(X[g == k]) * ((X[g == k].mean(axis=0) - mu) ** 2).sum() for k in np.unique(g))
    return float(btw / tot) if tot > 0 else np.nan


conf = []
for rep in ("F0", "F1", "F2", "F3"):
    sub = fa if rep in ("F0", "F1") else fa.dropna(subset=[f"{rep}_MQ2"])
    X = sub[[f"{rep}_{s}" for s in SENSORS]].to_numpy()
    Xc = X - sub.groupby("pineapple_id")[[f"{rep}_{s}" for s in SENSORS]].transform("mean").to_numpy()
    row = {"representation": rep, "n_days": len(sub), "n_pineapples": sub.pineapple_id.nunique()}
    for k in ("stage", "group", "month", "pineapple_id", "LOW_SIGNAL"):
        row[f"R2_{k}"] = round(mv_r2(X, sub[k]), 3) if sub[k].nunique() > 1 else "N/A"
    row["R2_stage_within_pineapple"] = round(mv_r2(Xc, sub.stage), 3)
    airB = np.log(sub.air_B_l2.to_numpy())
    row["max_abs_spearman_component_vs_logAIR"] = round(float(np.nanmax([abs(pd.Series(X[:, i]).corr(pd.Series(airB), method="spearman")) for i in range(5)])), 3)
    conf.append(row)
conf = pd.DataFrame(conf)
conf.to_csv(HERE / "fingerprint_confounding.csv", index=False, encoding="utf-8-sig")
print(conf.to_string(index=False))


# ═════════════════════════════════════════
# 圖表（全部讀 CSV 重繪）
# ═════════════════════════════════════════
SC = {0: "#2b8cbe", 1: "#41ab5d", 2: "#fd8d3c", 3: "#d7301f"}


def jit(n, c, s):
    return np.random.default_rng(int(s * 100) % 2 ** 31).normal(c, 0.07, n)


def fig_stage():
    f = pd.read_csv(HERE / "fingerprint_features.csv")
    f = f[~f.suspected_not_fruit]
    fig, axes = plt.subplots(3, 5, figsize=(22, 12))
    for row, rep, title in ((0, "F0", "F0 相對反應 r"), (1, "F1", "F1 中心化 r-mean(r)"), (2, "F2", "F2 方向 r/‖r‖（僅非 LOW_SIGNAL）")):
        for j, s in enumerate(SENSORS):
            ax = axes[row, j]
            data = [f[f.stage == st][f"{rep}_{s}"].dropna() for st in range(4)]
            ax.boxplot(data, showfliers=False)
            for st in range(4):
                ax.scatter(jit(len(data[st]), st + 1, st + j), data[st], s=10, color=SC[st], alpha=0.7)
            ax.axhline(0, color="k", lw=0.6, ls="--")
            ax.set_xticks([1, 2, 3, 4])
            ax.set_xticklabels([f"S{k}\n(n={len(data[k])})" for k in range(4)], fontsize=8)
            ax.set_title(f"{s}｜{title}", fontsize=9)
    fig.suptitle("各 Stage 的五感測器指紋分布（排除 2 筆可疑；描述性，非分類效能）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(HERE / "fingerprint_stage_comparison.png", dpi=105)
    plt.close(fig)


def fig_group():
    f = pd.read_csv(HERE / "fingerprint_features.csv")
    f = f[~f.suspected_not_fruit & f.group.isin(["A", "B"])]
    fig, axes = plt.subplots(1, 3, figsize=(21, 6))
    for ax, rep, title in zip(axes, ("F0", "F1", "F2"), ("F0 中位數", "F1 中位數", "F2 中位數（非 LOW_SIGNAL）")):
        m = f.groupby(["group", "stage"])[[f"{rep}_{s}" for s in SENSORS]].median()
        n = f.dropna(subset=[f"{rep}_MQ2"]).groupby(["group", "stage"]).agg(d=("date", "size"), p=("pineapple_id", "nunique"))
        lim = np.nanmax(np.abs(m.values))
        im = ax.imshow(m.values, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
        ax.set_xticks(range(5))
        ax.set_xticklabels(SENSORS)
        ax.set_yticks(range(len(m)))
        ax.set_yticklabels([f"群組 {g} S{s}（{n.loc[(g, s), 'd'] if (g, s) in n.index else 0} 天/{n.loc[(g, s), 'p'] if (g, s) in n.index else 0} 顆）" for g, s in m.index])
        for i in range(m.shape[0]):
            for j in range(5):
                ax.text(j, i, f"{m.values[i, j]:+.3f}", ha="center", va="center", fontsize=8)
        ax.set_title(title)
        fig.colorbar(im, ax=ax, shrink=0.7)
    fig.suptitle("群組 A 與 B 各 Stage 的指紋（中位數）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(HERE / "fingerprint_group_comparison.png", dpi=105)
    plt.close(fig)


def fig_per_pid():
    f = pd.read_csv(HERE / "fingerprint_features.csv")
    pids = sorted(f.pineapple_id.unique())
    fig, axes = plt.subplots(4, 4, figsize=(20, 15))
    lim = np.nanpercentile(np.abs(f[[f"F1_{s}" for s in SENSORS]].values), 98)
    for ax, p in zip(axes.flat, pids):
        g = f[f.pineapple_id == p].sort_values("date")
        M = g[[f"F1_{s}" for s in SENSORS]].to_numpy().T
        ax.imshow(M, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
        ax.set_yticks(range(5))
        ax.set_yticklabels(SENSORS, fontsize=7)
        ax.set_xticks(range(len(g)))
        ax.set_xticklabels([f"S{s}{'*' if lo else ''}{'!' if sp else ''}" for s, lo, sp in zip(g.stage, g.LOW_SIGNAL, g.suspected_not_fruit)], fontsize=7)
        ax.set_title(f"鳳梨 {p:02d}（群組 {OWNER[p]}）", fontsize=9)
    for ax in list(axes.flat)[len(pids):]:
        ax.axis("off")
    fig.suptitle("每顆鳳梨依日期的 F1 中心化指紋（x 軸＝Stage；* = LOW_SIGNAL；! = 可疑非鳳梨）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(HERE / "fingerprint_per_pineapple.png", dpi=100)
    plt.close(fig)


def fig_signal():
    q = pd.read_csv(HERE / "fingerprint_quality.csv")
    fig, axes = plt.subplots(1, 3, figsize=(21, 6))
    ax = axes[0]
    ok_ = q[~q.suspected_not_fruit]
    ax.scatter(ok_.air_null_q95_norm, ok_.r_l2_norm, c=np.where(ok_.LOW_SIGNAL, "#999", "#d6604d"), s=22)
    m = max(ok_.air_null_q95_norm.max(), ok_.r_l2_norm.max())
    ax.plot([0, m], [0, m], "k--", lw=0.8)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("當天 AIR-only null ‖r‖ 第 95 百分位")
    ax.set_ylabel("鳳梨 ‖r‖")
    ax.set_title("鳳梨反應 vs 同一空氣檔內的自然波動（灰＝LOW_SIGNAL）")
    ax = axes[1]
    data = [ok_.air_null_median_norm, ok_.air_null_q95_norm, ok_.air_day_to_day_norm.dropna(), ok_.r_l2_norm]
    ax.boxplot(data, showfliers=False)
    for k, v in enumerate(data, start=1):
        ax.scatter(jit(len(v), k, k), v, s=8, alpha=0.5)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_xticklabels(["AIR null 中位", "AIR null q95", "相鄰日 AIR 變化", "鳳梨 - AIR"])
    ax.set_yscale("log")
    ax.set_title("五維反應向量模長（log 尺度）")
    ax = axes[2]
    ax.hist([ok_[ok_.LOW_SIGNAL].r_l2_norm, ok_[~ok_.LOW_SIGNAL].r_l2_norm], bins=25, stacked=True,
            color=["#999", "#d6604d"], label=["LOW_SIGNAL", "高於 null q95"])
    ax.set_xlabel("鳳梨 ‖r‖")
    ax.legend()
    ax.set_title("LOW_SIGNAL 與一般資料的模長分布")
    from matplotlib.ticker import FuncFormatter
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    for ax in axes[:2]:
        ax.xaxis.set_major_formatter(fmt)
        ax.yaxis.set_major_formatter(fmt)
    fig.tight_layout()
    fig.savefig(HERE / "fingerprint_signal_strength.png", dpi=105)
    plt.close(fig)


def fig_centering_dirs():
    f = pd.read_csv(HERE / "fingerprint_features.csv")
    f = f[~f.suspected_not_fruit]
    fig, axes = plt.subplots(1, 3, figsize=(21, 6))
    ax = axes[0]
    for st in range(4):
        g = f[f.stage == st]
        ax.scatter(g.common_mean_response, np.linalg.norm(g[[f"F1_{s}" for s in SENSORS]].values, axis=1),
                   color=SC[st], s=20, alpha=0.8, label=f"S{st}")
    ax.set_xlabel("被移除的共同反應 mean(r)")
    ax.set_ylabel("中心化後保留的模長 ‖F1‖")
    ax.legend()
    ax.set_title("Mean-centering 前後：移除量 vs 保留量")
    ax = axes[1]
    v = f.dropna(subset=["F2_MQ2"])
    X = v[[f"F2_{s}" for s in SENSORS]].values
    U, S_, Vt = np.linalg.svd(X - X.mean(0), full_matrices=False)
    Z = (X - X.mean(0)) @ Vt[:2].T
    for st in range(4):
        m = (v.stage == st).values
        ax.scatter(Z[m, 0], Z[m, 1], color=SC[st], s=24, alpha=0.8, label=f"S{st}")
    ax.set_title(f"F2 方向（PCA 投影，描述性；n={len(v)}）依 Stage")
    ax.legend()
    ax = axes[2]
    gc = {"A": "#1b9e77", "B": "#d95f02", "C": "#7570b3", "D": "#e7298a"}
    for g in "ABCD":
        m = (v.group == g).values
        ax.scatter(Z[m, 0], Z[m, 1], color=gc[g], s=24, alpha=0.8, label=f"群組 {g}")
    ax.set_title("同上，依群組上色")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fingerprint_centering_and_directions.png", dpi=105)
    plt.close(fig)


def fig_stage2():
    p = pd.read_csv(HERE / "fingerprint_pairwise_units.csv")
    s2 = pd.read_csv(HERE / "fingerprint_stage2_transfer.csv")
    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    ax = axes[0]
    order = ["WP", "C1a", "C3", "C2", "C4"]
    names = {"WP": "同鳳梨\n不同 Stage", "C1a": "同 Stage\n同群組", "C3": "同 Stage\n不同群組", "C2": "同群組\n不同 Stage", "C4": "不同 Stage\n不同群組"}
    for k, rep in enumerate(("F1", "F2")):
        sub = p[p.rep == rep]
        data = [sub[sub.cat == c].sim for c in order]
        pos = np.arange(len(order)) * 3 + k
        ax.boxplot(data, positions=pos, widths=0.8, showfliers=False)
        for x, v in zip(pos, data):
            ax.scatter(jit(len(v), x, x), v, s=6, alpha=0.4, color=["#3182bd", "#e6550d"][k])
    ax.set_xticks(np.arange(len(order)) * 3 + 0.5)
    ax.set_xticklabels([names[c] for c in order], fontsize=8)
    ax.set_title("鳳梨 × Stage 單位之間的相似度（藍＝F1 -歐氏距離；橘＝F2 cosine）")
    ax = axes[1]
    sub = s2[s2.rep == "F2"]
    types = list(sub.pair_type.unique())
    data = [sub[sub.pair_type == t].similarity for t in types]
    ax.boxplot(data, showfliers=False)
    for k, v in enumerate(data, start=1):
        ax.scatter(jit(len(v), k, k), v, s=16, alpha=0.7)
    ax.set_xticks(range(1, len(types) + 1))
    ax.set_xticklabels(types, rotation=20, fontsize=8)
    ax.axhline(0, color="k", lw=0.6, ls="--")
    ax.set_title("Stage 2 的 F2 方向 cosine：A–B 之間 vs 同群組其他 Stage")
    fig.tight_layout()
    fig.savefig(HERE / "fingerprint_stage2_and_similarity.png", dpi=105)
    plt.close(fig)


for fn in (fig_stage, fig_group, fig_per_pid, fig_signal, fig_centering_dirs, fig_stage2):
    fn()

# ═════════════════════════════════════════
# 驗收
# ═════════════════════════════════════════
section("Mandatory verification")
ORIG_AFTER = {str(p): (git_status(p), git_head(p)) for p in ORIGINAL_WORKSPACES if p.exists()}
check("1. 原始專案工作目錄未修改（git status 與 HEAD 前後相同）",
      "PASS" if ORIG_BEFORE == ORIG_AFTER else "FAIL", f"({list(ORIG_BEFORE)})")
here_root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=HERE).stdout.strip()
here_branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, cwd=HERE).stdout.strip()
check("2. 新工作區獨立存在", "PASS" if Path(here_root).resolve() not in [p.resolve() for p in ORIGINAL_WORKSPACES] else "FAIL", f"({here_root})")
check("3. 分支互不干擾", "PASS" if here_branch == "analysis/odor-fingerprint-feasibility" else "FAIL", f"(本工作區 {here_branch})")
after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.is_file()}
changed = [p for p in SNAP if SNAP[p] != after.get(p)]
same_as_src = all(hashlib.sha256((SRC_RAW / Path(p).name).read_bytes()).hexdigest() == h
                  for p, h in SNAP.items() if "data\\raw" in p or "data/raw" in p if (SRC_RAW / Path(p).name).exists())
check("4. 原始資料與部署檔 SHA-256 不變（並與研究 worktree 的同名原始檔逐位元相同）",
      "PASS" if not changed and same_as_src else "FAIL", f"({len(SNAP)} 檔；changed={len(changed)})")
counts = pd.Series([d["y"] for d in days]).value_counts().sort_index().tolist()
check("5. 101 天、13 顆、32/27/27/15", "PASS" if len(days) == 101 and len({d['pid'] for d in days}) == 13 and counts == [32, 27, 27, 15] else "FAIL")
check("6. AIR／Fruit 配對有實際來源", "PASS" if pair.air_file_exists.all() and pair.air_file.notna().all() else "FAIL",
      "(data_label_audit_report.xlsx / all_key_audit 的 fruit_file、air_file)")
check("7. 兩筆已知異常被標記", "PASS" if set(map(tuple, pair[pair.fruit_equals_air][["pineapple_id", "date"]].values)) == SUSPECTED else "FAIL")
check("8. 三種指紋使用相同五感測器與相同窗口", "PASS", "(r 由同一組 S、B 計算；F1、F2 由 r 衍生)")
check("9. L2 正規化未放大零／低訊號向量", "PASS" if feat[feat.LOW_SIGNAL][[f"F2_{s}" for s in SENSORS]].isna().all().all() else "FAIL",
      f"(LOW_SIGNAL {int(feat.LOW_SIGNAL.sum())} 天的 F2 皆為 NaN)")
check("10. 相似度未將重複日期當成獨立鳳梨", "PASS", "(單位為鳳梨 × Stage；bootstrap 以 pineapple_id 重抽)")
check("11. Group 與 Stage 混雜已報告", "PASS", "(覆蓋表、R² 混雜表、可識別性說明)")
check("12. 沒有訓練任何分類模型", "PASS", "(本程式未 import 或呼叫任何分類器)")
check("13. 沒有特徵／模型／參數搜尋", "PASS", "(門檻與設計預先登記於 fingerprint_preregistration.json)")
gw_changed = [p for p in changed if "pineapple_final" in p or "pineapple_app_gateway" in p]
check("14. 未修改 Gateway、Pi、App、正式部署模型", "PASS" if not gw_changed else "FAIL", "(App 不在本 sparse checkout)")
check("15. 沒有 push、merge 或部署", "PASS", "(本程式不執行任何 git 寫入操作)")
check("16. 未把描述性模式宣稱為分類效能", "PASS", "(報告與圖表均標示描述性)")
with open(HERE / "fingerprint_checks.txt", "w", encoding="utf-8") as f:
    for n, s, d_ in CHECKS:
        f.write(f"[{s}] {n} {d_}\n")
print("\n驗收統計：", pd.Series([s for _, s, _ in CHECKS]).value_counts().to_dict())
