"""
第一輪重新訓練（只用 101 天人工標籤，不用複查標籤或偽標籤）

1. 特徵穩定度分析（描述用，使用全部資料，不拿來決定最終特徵）
2. 嚴格 LOGO：留出整顆鳳梨；每一折只用訓練組做補值、特徵選擇與 ExtraTrees 訓練
3. 比較：原部署 11 特徵（固定）vs 每折重新選特徵；單窗口 vs 三窗口

資料與特徵計算沿用 eval_common.py（與 backtest.py 相同）與 gateway 的 _build_features。
部署模型 pineapple_final/deploy_student.pkl 不會被修改；本腳本不匯出任何模型。

Run:  python -u retrain_round1.py > retrain_round1_out.txt
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from eval_common import FEATURES, MODEL, SCAN_ROWS, SENSORS, STEP, WINDOW, load_days, new

K = (SCAN_ROWS - WINDOW) // STEP + 1  # 三窗口
PRIMARY_K = 8                          # 事先指定的主要特徵數；其他 k 只當敏感度參考
K_LIST = [5, 8, 11]
ET_PARAMS = MODEL.get_params()         # 與部署模型相同的 ExtraTrees 參數


# ─────────────────────────────────────────
# 特徵
# ─────────────────────────────────────────
GATEWAY_POOL = None  # gateway 目前算得出、可直接部署的特徵（不含 *_raw_ratio）


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


days = load_days()
for d in days:
    starts = range(0, len(d["rows"]) - WINDOW + 1, STEP)
    d["feats"] = []
    for s in starts:
        f, gw_keys = extended_features(d["rows"][s:s + WINDOW], d["air"])
        d["feats"].append(f)
GATEWAY_POOL = sorted(gw_keys)
EXT_POOL = sorted(days[0]["feats"][0])

# 擴充特徵與 gateway 同名特徵必須一致（同一套計算）
probe = days[0]["feats"][0]
assert abs(probe["MQ2_mean_norm"] - new._build_features(days[0]["rows"][:WINDOW], days[0]["air"])[0]["MQ2_mean_norm"]) < 1e-12

y = np.array([d["y"] for d in days])
pids = np.array([d["pid"] for d in days])
print(f"\nGateway 特徵池 {len(GATEWAY_POOL)} 個；擴充特徵池 {len(EXT_POOL)} 個")
print(f"多數類別基準準確率（全猜 Stage 0）= {np.mean(y == 0):.3f}")


def matrix(day_list, cols, k=0):
    return np.array([[d["feats"][k][c] for c in cols] for d in day_list], dtype=float)


# ─────────────────────────────────────────
# 1. 特徵穩定度分析（描述用）
# ─────────────────────────────────────────
def within_pid_rho(day_list, cols):
    """每顆鳳梨內，特徵與成熟階段的 Spearman 相關；回傳 (平均 rho, 方向一致比例, 有效鳳梨數)。"""
    out = {}
    groups = {}
    for d in day_list:
        groups.setdefault(d["pid"], []).append(d)
    for c in cols:
        rhos = []
        for ds in groups.values():
            st = [d["y"] for d in ds]
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


def eta2(v, groups):
    v = np.asarray(v, dtype=float)
    tot = np.sum((v - v.mean()) ** 2)
    if tot == 0:
        return 0.0
    between = sum(len(v[groups == g]) * (v[groups == g].mean() - v.mean()) ** 2 for g in np.unique(groups))
    return float(between / tot)


print("\n" + "=" * 72)
print("1. 特徵穩定度分析（全部 101 天，窗口起點 0；僅供描述，不用來決定最終特徵）")
print("=" * 72)
rho_all = within_pid_rho(days, EXT_POOL)
rows = []
for c in EXT_POOL:
    v0 = matrix(days, [c])[:, 0]
    # 窗口雜訊：同一天不同窗口的標準差，相對於跨天的標準差
    within_day = np.mean([np.std([f[c] for f in d["feats"]]) for d in days])
    across = np.std(v0)
    m, cons, n = rho_all[c]
    rows.append({
        "feature": c,
        "gateway": "Y" if c in GATEWAY_POOL else "",
        "pid內rho": round(m, 3),
        "方向一致": round(cons, 2),
        "鳳梨數": n,
        "eta2_階段": round(eta2(v0, y), 3),
        "eta2_鳳梨": round(eta2(v0, pids), 3),
        "窗口雜訊比": round(float(within_day / across), 3) if across > 0 else np.nan,
        "deploy11": "Y" if c in FEATURES else "",
    })
stab = pd.DataFrame(rows)
stab["score"] = (stab["pid內rho"].abs() * stab["方向一致"]).round(3)
stab = stab.sort_values("score", ascending=False)
pd.set_option("display.width", 200)
print("pid內rho：同一顆鳳梨內與成熟階段的相關（越接近 ±1 越好）")
print("方向一致：各鳳梨的相關方向與平均方向相同的比例")
print("eta2_階段 / eta2_鳳梨：特徵變異有多少可由「成熟階段」/「哪一顆鳳梨」解釋")
print("窗口雜訊比：同一天換窗口的變動 ÷ 跨天變動（越小越穩）\n")
print(stab.head(25).to_string(index=False))
print("\n原部署 11 特徵：")
print(stab[stab.deploy11 == "Y"].to_string(index=False))


# ─────────────────────────────────────────
# 2. 嚴格 LOGO
# ─────────────────────────────────────────
def select_features(train_days, pool, k):
    r = within_pid_rho(train_days, pool)
    score = {c: abs(r[c][0]) * r[c][1] for c in pool}
    return sorted(pool, key=lambda c: -score[c])[:k]


def fit_predict(train_days, test_days, cols):
    Xtr = matrix(train_days, cols)
    med = np.nanmedian(Xtr, axis=0)                    # 只用訓練組中位數
    Xtr = np.where(np.isnan(Xtr), med, Xtr)
    m = ExtraTreesClassifier(**ET_PARAMS).fit(Xtr, [d["y"] for d in train_days])
    cls = m.classes_.astype(int)
    out = []
    for d in test_days:
        Xd = np.array([[f[c] for c in cols] for f in d["feats"]], dtype=float)
        Xd = np.where(np.isnan(Xd), med, Xd)
        P = np.zeros((len(Xd), 4))
        P[:, cls] = m.predict_proba(Xd)
        out.append(P)
    return out


VARIANTS = [("FIXED11 原部署11特徵", "fixed", None)]
VARIANTS += [(f"SEL-GW k={k}（gateway池）", "gw", k) for k in (5, 8)]
VARIANTS += [(f"SEL-EXT k={k}（擴充池）", "ext", k) for k in K_LIST]

print("\n" + "=" * 72)
print("2. 嚴格 LOGO（留一顆鳳梨；補值、特徵選擇、訓練都只用其餘鳳梨）")
print("=" * 72)
print(f"ExtraTrees 參數同部署模型；主要設定為 k={PRIMARY_K}，其他 k 僅作敏感度參考")

summary, picked = [], {}
for name, pool_kind, k in VARIANTS:
    preds = {"single": [], "three": []}
    slide_cons, slide_flip = [], []
    per_pid = {}
    picked[name] = {}
    for pid in sorted(set(pids)):
        tr = [d for d in days if d["pid"] != pid]
        te = [d for d in days if d["pid"] == pid]
        if pool_kind == "fixed":
            cols = list(FEATURES)
        else:
            cols = select_features(tr, GATEWAY_POOL if pool_kind == "gw" else EXT_POOL, k)
        for c in cols:
            picked[name][c] = picked[name].get(c, 0) + 1
        for d, P in zip(te, fit_predict(tr, te, cols)):
            s1 = int(np.argmax(P[0]))
            s3 = int(np.argmax(P[:K].mean(axis=0)))
            preds["single"].append((d["y"], s1))
            preds["three"].append((d["y"], s3))
            per_pid.setdefault(pid, []).append(s3 == d["y"])
            seq = [int(np.argmax(P[i:i + K].mean(axis=0))) for i in range(len(P) - K + 1)]
            slide_cons.append(max(seq.count(v) for v in set(seq)) / len(seq))
            slide_flip.append(np.mean([a != b for a, b in zip(seq, seq[1:])]) if len(seq) > 1 else 0.0)

    for mode in ("single", "three"):
        yt, yp = np.array(preds[mode]).T
        cm = confusion_matrix(yt, yp, labels=[0, 1, 2, 3])
        _, R, F, _ = precision_recall_fscore_support(yt, yp, labels=[0, 1, 2, 3], zero_division=0)
        row = {
            "版本": name, "窗口": "單" if mode == "single" else "三",
            "acc": round(float(np.mean(yt == yp)), 3), "macroF1": round(float(np.mean(F)), 3),
            "R0": round(R[0], 2), "R1": round(R[1], 2), "R2": round(R[2], 2), "R3": round(R[3], 2),
            "S3→S0/1": int(cm[3, 0] + cm[3, 1]),
        }
        if mode == "three":
            row["滑動一致率"] = round(float(np.mean(slide_cons)), 3)
            row["相鄰翻轉率"] = round(float(np.mean(slide_flip)), 3)
        summary.append(row)
        if mode == "three":
            print(f"\n---- {name}（三窗口）")
            print(pd.DataFrame(cm, index=[f"真{i}" for i in range(4)], columns=[f"預{i}" for i in range(4)]).to_string())
            print("各鳳梨準確率：", {int(p): round(float(np.mean(v)), 2) for p, v in per_pid.items()})

print("\n" + "=" * 72)
print("總表（LOGO，13 折）")
print("=" * 72)
print(pd.DataFrame(summary).fillna("").to_string(index=False))

print("\n各版本在 13 折中被選到的特徵（次數）：")
for name, cnt in picked.items():
    if name.startswith("FIXED"):
        continue
    print(f"  {name}: " + ", ".join(f"{c}×{n}" for c, n in sorted(cnt.items(), key=lambda x: -x[1])))
