"""
第二輪：三類分類與多窗口訓練（只用 101 天人工標籤；離線實驗，不匯出模型）

四組實驗（皆為整顆鳳梨 LOGO；補值與特徵選擇只用當折訓練鳳梨）：
  A  4 類  每天開頭單窗口訓練     ← 與第一輪銜接
  B  3 類  每天開頭單窗口訓練
  C  4 類  每天多窗口訓練
  D  3 類  每天多窗口訓練

三類定義：Stage 0+1 → 未熟、Stage 2 → 成熟／可食、Stage 3 → 過熟
多窗口：每天開頭 150 秒內 5 個不重疊的 30 秒窗口（起點 0/30/60/90/120 筆），
        每窗口樣本權重 1/5，每個「鳳梨－日期」對訓練的總權重與單窗口相同。
        只增加訓練鳳梨的樣本；測試鳳梨一律用部署方式（開頭三窗口平均）。
特徵：FIXED11（原部署 11 特徵，主要）與 SEL-GW k=8（每折從 gateway 池重選，次要）
ExtraTrees 參數同部署模型。

Run:  python -u retrain_round2.py > retrain_round2_out.txt
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from eval_common import (FEATURES, MODEL, SCAN_ROWS, STEP, WINDOW, extended_features, load_days,
                         select_features)

K = (SCAN_ROWS - WINDOW) // STEP + 1           # 測試用三窗口（0/10/20 筆）
AUG_STARTS = [0, 30, 60, 90, 120]              # 多窗口訓練的起點（筆）
AUG_IDX = [s // STEP for s in AUG_STARTS]      # 對應 d["feats"] 的索引（feats 每 STEP 筆一個）
ET_PARAMS = MODEL.get_params()
SEL_K = 8

TASKS = {
    4: {"map": {0: 0, 1: 1, 2: 2, 3: 3}, "names": ["未熟", "初熟", "成熟", "過熟"]},
    3: {"map": {0: 0, 1: 0, 2: 1, 3: 2}, "names": ["未熟(0+1)", "成熟/可食(2)", "過熟(3)"]},
}

days = load_days()
for d in days:
    d["feats"] = [extended_features(d["rows"][s:s + WINDOW], d["air"])[0]
                  for s in range(0, len(d["rows"]) - WINDOW + 1, STEP)]
gw_keys = extended_features(days[0]["rows"][:WINDOW], days[0]["air"])[1]
GATEWAY_POOL = sorted(gw_keys)
pids = np.array([d["pid"] for d in days])


def run(task, train_mode, feat_mode):
    cmap = TASKS[task]["map"]
    label = lambda d: cmap[d["y"]]  # noqa: E731
    out = {"y": [], "single": [], "three": [], "pid": [], "flip": []}
    picked = {}
    for pid in sorted(set(pids)):
        tr = [d for d in days if d["pid"] != pid]
        te = [d for d in days if d["pid"] == pid]
        cols = list(FEATURES) if feat_mode == "FIXED11" else select_features(tr, GATEWAY_POOL, SEL_K, label)
        for c in cols:
            picked[c] = picked.get(c, 0) + 1

        idx = [0] if train_mode == "single" else AUG_IDX
        X = np.array([[d["feats"][i][c] for c in cols] for d in tr for i in idx], dtype=float)
        yl = np.array([label(d) for d in tr for _ in idx])
        w = np.full(len(yl), 1.0 / len(idx))
        med = np.nanmedian(X, axis=0)                      # 只用訓練組
        X = np.where(np.isnan(X), med, X)
        m = ExtraTreesClassifier(**ET_PARAMS).fit(X, yl, sample_weight=w)
        cls = m.classes_.astype(int)

        for d in te:
            Xd = np.array([[f[c] for c in cols] for f in d["feats"]], dtype=float)
            Xd = np.where(np.isnan(Xd), med, Xd)
            P = np.zeros((len(Xd), task))
            P[:, cls] = m.predict_proba(Xd)
            out["y"].append(label(d))
            out["single"].append(int(np.argmax(P[0])))
            out["three"].append(int(np.argmax(P[:K].mean(axis=0))))
            out["pid"].append(pid)
            seq = [int(np.argmax(P[i:i + K].mean(axis=0))) for i in range(len(P) - K + 1)]
            out["flip"].append(np.mean([a != b for a, b in zip(seq, seq[1:])]))
    return out, picked


def metrics(task, yt, yp):
    labels = list(range(task))
    cm = confusion_matrix(yt, yp, labels=labels)
    _, R, F, _ = precision_recall_fscore_support(yt, yp, labels=labels, zero_division=0)
    return cm, R, F


def critical(task, cm):
    # 實際應用上最值得注意的誤判
    if task == 4:
        return {"成熟→未熟/初熟": int(cm[2, 0] + cm[2, 1]),
                "過熟→成熟": int(cm[3, 2]),
                "過熟→未熟/初熟": int(cm[3, 0] + cm[3, 1])}
    return {"成熟→未熟": int(cm[1, 0]),
            "過熟→成熟": int(cm[2, 1]),
            "過熟→未熟": int(cm[2, 0])}


def baseline(task):
    yt = np.array([TASKS[task]["map"][d["y"]] for d in days])
    maj = np.bincount(yt).argmax()
    _, _, F = metrics(task, yt, np.full_like(yt, maj))[0:3]
    return float(np.mean(yt == maj)), float(np.mean(F)), TASKS[task]["names"][maj]


print("\n多數類別基準（全部猜最多的那一類）：")
for t in (4, 3):
    acc, f1, name = baseline(t)
    print(f"  {t} 類：全猜「{name}」 accuracy={acc:.3f}  macroF1={f1:.3f}")

EXPS = [("A", 4, "single"), ("B", 3, "single"), ("C", 4, "multi"), ("D", 3, "multi")]
summary = []
collapsed_ref = []

for feat_mode in ("FIXED11", "SEL-GW8"):
    print("\n" + "=" * 76)
    print(f"特徵：{feat_mode}" + ("（原部署 11 特徵，主要比較）" if feat_mode == "FIXED11" else "（每折從 gateway 池重選 8 個）"))
    print("=" * 76)
    for exp, task, train_mode in EXPS:
        out, picked = run(task, train_mode, feat_mode)
        yt = np.array(out["y"])
        names = TASKS[task]["names"]
        for mode in ("single", "three"):
            yp = np.array(out[mode])
            cm, R, F = metrics(task, yt, yp)
            row = {"特徵": feat_mode, "實驗": exp, "類別": task,
                   "訓練": "單窗口" if train_mode == "single" else "多窗口",
                   "測試": "單" if mode == "single" else "三",
                   "acc": round(float(np.mean(yt == yp)), 3), "macroF1": round(float(np.mean(F)), 3)}
            row.update({f"R_{n}": round(float(r), 2) for n, r in zip(names, R)})
            row.update(critical(task, cm))
            if mode == "three":
                row["相鄰翻轉率"] = round(float(np.mean(out["flip"])), 3)
            summary.append(row)

        yp = np.array(out["three"])
        cm, R, F = metrics(task, yt, yp)
        print(f"\n---- {exp}：{task} 類 / {'單窗口' if train_mode == 'single' else '多窗口'}訓練 / 測試三窗口"
              f"  acc={np.mean(yt == yp):.3f} macroF1={np.mean(F):.3f}")
        print(pd.DataFrame(cm, index=[f"真:{n}" for n in names], columns=[f"預:{n}" for n in names]).to_string())
        per_pid = {int(p): round(float(np.mean([a == b for a, b, q in zip(yt, yp, out["pid"]) if q == p])), 2)
                   for p in sorted(set(out["pid"]))}
        print("各鳳梨準確率：", per_pid)
        if feat_mode != "FIXED11":
            print("被選到的特徵（13 折次數）：", ", ".join(f"{c}×{n}" for c, n in sorted(picked.items(), key=lambda x: -x[1])))

        # 參考：4 類模型的預測直接合併成 3 類（不是 3 類模型，只用來判斷「重訓 3 類」是否真的有幫助）
        if task == 4:
            cmap3 = TASKS[3]["map"]
            yt3 = np.array([cmap3[v] for v in yt])
            yp3 = np.array([cmap3[v] for v in yp])
            _, R3, F3 = metrics(3, yt3, yp3)
            collapsed_ref.append({"特徵": feat_mode, "來源": f"{exp}（4 類模型合併）",
                                  "acc": round(float(np.mean(yt3 == yp3)), 3), "macroF1": round(float(np.mean(F3)), 3),
                                  **{f"R_{n}": round(float(r), 2) for n, r in zip(TASKS[3]["names"], R3)}})

pd.set_option("display.width", 250)
df = pd.DataFrame(summary)
print("\n" + "=" * 76)
print("總表：4 類（LOGO 13 折）")
print("=" * 76)
cols4 = ["特徵", "實驗", "訓練", "測試", "acc", "macroF1", "R_未熟", "R_初熟", "R_成熟", "R_過熟",
         "成熟→未熟/初熟", "過熟→成熟", "過熟→未熟/初熟", "相鄰翻轉率"]
print(df[df["類別"] == 4][cols4].fillna("").to_string(index=False))
print("\n" + "=" * 76)
print("總表：3 類（LOGO 13 折）")
print("=" * 76)
cols3 = ["特徵", "實驗", "訓練", "測試", "acc", "macroF1", "R_未熟(0+1)", "R_成熟/可食(2)", "R_過熟(3)",
         "成熟→未熟", "過熟→成熟", "過熟→未熟", "相鄰翻轉率"]
print(df[df["類別"] == 3][cols3].fillna("").to_string(index=False))
print("\n參考：4 類模型預測（測試三窗口）直接合併成 3 類——不是 3 類模型，只用來對照重訓 3 類是否有幫助")
print(pd.DataFrame(collapsed_ref).to_string(index=False))
