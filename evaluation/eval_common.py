"""
evaluation/ 共用的資料讀取：gateway 模組、部署模型、原始資料與人工標籤。
backtest.py 與 retrain_round1.py 都從這裡取資料，確保兩者使用同一套處理流程。
"""
import importlib.util
import json
import pickle
import subprocess
import sys
import tempfile
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

warnings.filterwarnings("ignore")
sys.modules["serial"] = types.ModuleType("serial")

HERE = Path(__file__).resolve().parent
WT = HERE.parent  # Semester 2 Final Exam (三下-期末)/
# 舊版 gateway：main 分支修改前的 app_gateway_v2.py（commit 4e1a93d）
OLD_GATEWAY_REV = "4e1a93d"
ORK = WT / "enose_model_training/orkspace"
RAW = ORK / "data/raw"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


new = load("gw_new", WT / "pineapple_app_gateway/app_gateway_v2.py")
_old_src = subprocess.run(
    ["git", "show", f"{OLD_GATEWAY_REV}:Semester 2 Final Exam (三下-期末)/pineapple_app_gateway/app_gateway_v2.py"],
    cwd=WT, capture_output=True, check=True,
).stdout
_old_path = Path(tempfile.gettempdir()) / "app_gateway_v2_old.py"
_old_path.write_bytes(_old_src)
old = load("gw_old", _old_path)

MODEL = pickle.load(open(WT / "pineapple_final/deploy_student.pkl", "rb"))
FEATURES = json.load(open(WT / "pineapple_final/feature_columns.json", encoding="utf-8"))
SENSORS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]
WINDOW, STEP, SCAN_ROWS = new.WINDOW, new.WINDOW_STEP, new.SCAN_ROWS


# ── 讀檔：找 timestamp_ms 那一列當欄名（標準格式時結果與訓練 notebook 相同；
#    notebook 固定用第 2 列，pid 05/06 的檔案欄名在第 1 列，訓練時會讀不到） ──
def read_raw_xlsx(path):
    raw = pd.read_excel(path, header=None)
    hdr = [i for i in range(min(10, len(raw))) if str(raw.iloc[i, 0]).strip() == "timestamp_ms"]
    if not hdr:
        return None
    df = raw.iloc[hdr[0] + 1:].copy()
    df.columns = raw.iloc[hdr[0]].tolist()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all").reset_index(drop=True)


def to_rows(df):
    # 轉成 gateway 的 row 格式；缺任一氣體值的列丟掉（同 _read_arduino_row）
    rows = []
    for _, r in df.iterrows():
        row = {s: r.get(f"{s}_raw") for s in SENSORS}
        if any(pd.isna(v) for v in row.values()):
            continue
        row = {k: float(v) for k, v in row.items()}
        ts = r.get("timestamp_ms")
        row["timestamp_ms"] = None if pd.isna(ts) else float(ts)
        rows.append(row)
    return rows


def proba_of(feat):
    x = np.array([feat[f] for f in FEATURES], dtype=float).reshape(1, -1)
    p = np.zeros(4)
    p[MODEL.classes_.astype(int)] = MODEL.predict_proba(x)[0]
    return p



def load_days():
    # ── 讀取標籤與檔案對應 ──
    audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
    audit = audit[(audit.has_raw_fruit == 1) & audit.stage.notna()].copy()
    audit["stage"] = audit.stage.astype(int)

    fallback = {}  # 同 notebook：沒有空氣檔時用該 pid 第一天鳳梨檔整體平均
    for pid, g in audit.sort_values("date").groupby("pid"):
        df0 = next(x for x in (read_raw_xlsx(RAW / f) for f in g.fruit_file) if x is not None)
        fallback[pid] = {s: float(df0[f"{s}_raw"].mean()) for s in SENSORS}

    days = []
    for _, a in audit.iterrows():
        fdf = read_raw_xlsx(RAW / a.fruit_file)
        if fdf is None:
            print("略過無法讀取的檔案：", a.fruit_file)
            continue
        fruit = to_rows(fdf)
        air_df = read_raw_xlsx(RAW / a.air_file) if isinstance(a.air_file, str) and (RAW / a.air_file).exists() else None
        if air_df is not None:
            air_df = air_df.iloc[:WINDOW]  # 訓練：空氣檔前 30 筆
            air = {s: float(air_df[f"{s}_raw"].mean()) for s in SENSORS}
        else:
            air = dict(fallback[a.pid])
        days.append({"pid": int(a.pid), "date": int(a.date), "y": int(a.stage), "rows": fruit, "air": air})

    days = [d for d in days if len(d["rows"]) >= SCAN_ROWS]
    print(f"有標籤且資料足夠的天數：{len(days)}，鳳梨數：{len({d['pid'] for d in days})}")
    print("標籤分布：", pd.Series([d["y"] for d in days]).value_counts().sort_index().to_dict())

    # 歷史資料的實際取樣間隔
    med = [new._sampling_quality(d["rows"][:SCAN_ROWS])["median_interval_sec"] for d in days]
    med = [m for m in med if m is not None]
    print(f"歷史資料取樣間隔中位數：min={min(med):.3f}s  median={np.median(med):.3f}s  max={max(med):.3f}s")
    return days


# ─────────────────────────────────────────
# 特徵計算與每折特徵選擇（retrain_round1.py、retrain_round2.py 共用）
# ─────────────────────────────────────────
def extended_features(rows, air):
    """gateway 特徵 + 訓練 notebook compute_features_one_day 的其他統計量與兩兩比值。"""
    feat, data = new._build_features(rows, air)
    feat = {k: v for k, v in feat.items() if not k.endswith("_raw_ratio")}
    gw_keys = set(feat)
    mean_norm = {}
    for s in SENSORS:
        x = data[s]
        b = new._base_value(air, s)
        d = np.diff(x)
        acc = np.diff(d)
        n30 = max(1, len(x) // 30)
        extra = {
            "mean_norm": np.mean(x) / b,
            "std_norm": np.std(x) / b,
            "min_norm": np.min(x) / b,
            "max_norm": np.max(x) / b,
            "range_norm": (np.max(x) - np.min(x)) / b,
            "auc_norm": np.trapz(x) / (len(x) * b),
            "slope": new._safe_slope(x),
            "accel_mean": np.mean(acc),
            "accel_std": np.std(acc),
            "relative_change": (np.mean(x[-n30:]) - np.mean(x[:n30])) / (np.mean(x[:n30]) + 1e-9),
            "delta_mean": np.mean(d),
            "delta_std": np.std(d),
            "delta_max_abs": np.max(np.abs(d)),
        }
        mean_norm[s] = extra["mean_norm"]
        for k, v in extra.items():
            feat.setdefault(f"{s}_{k}", float(v))
    for i, a in enumerate(SENSORS):
        for b in SENSORS[i + 1:]:
            feat.setdefault(f"{a}_{b}_ratio", float(mean_norm[a] / (mean_norm[b] + 1e-9)))
    return feat, gw_keys


def matrix(day_list, cols, k=0):
    return np.array([[d["feats"][k][c] for c in cols] for d in day_list], dtype=float)


def within_pid_rho(day_list, cols, label=lambda d: d["y"]):
    """每顆鳳梨內，特徵與成熟階段的 Spearman 相關；回傳 (平均 rho, 方向一致比例, 有效鳳梨數)。"""
    out = {}
    groups = {}
    for d in day_list:
        groups.setdefault(d["pid"], []).append(d)
    for c in cols:
        rhos = []
        for ds in groups.values():
            st = [label(d) for d in ds]
            if len(ds) < 3 or len(set(st)) < 2:
                continue
            v = [d["feats"][0][c] for d in ds]
            if np.std(v) == 0:
                continue
            r = spearmanr(v, st).correlation
            if np.isfinite(r):
                rhos.append(r)
        if not rhos:
            out[c] = (0.0, 0.0, 0)
            continue
        m = float(np.mean(rhos))
        cons = float(np.mean(np.sign(rhos) == np.sign(m))) if m != 0 else 0.0
        out[c] = (m, cons, len(rhos))
    return out


def select_features(train_days, pool, k, label=lambda d: d["y"]):
    r = within_pid_rho(train_days, pool, label)
    score = {c: abs(r[c][0]) * r[c][1] for c in pool}
    return sorted(pool, key=lambda c: -score[c])[:k]
