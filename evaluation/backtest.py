"""
Historical backtest of app_gateway_v2.py variants.

Uses the gateway's own feature / post-processing functions:
  - old gateway  : app_gateway_v2.py at commit 4e1a93d (before this branch)
  - new gateway  : ../pineapple_app_gateway/app_gateway_v2.py (this branch)

Run from anywhere inside the repo:  python -u backtest.py > backtest_out.txt
Model          : pineapple_final/deploy_student.pkl (sha256 a57dbbbf...)
Data           : enose_model_training/orkspace/data/raw  (fruit + air xlsx)
Labels         : data_label_audit_report.xlsx / all_key_audit (manual labels)
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from eval_common import FEATURES, MODEL, SCAN_ROWS, STEP, WINDOW, new, old, load_days

days = load_days()


# ── 每天所有窗口（起點每 STEP 筆）的特徵，一次批次推論 ──
def batch_proba(model, X):
    p = np.zeros((len(X), 4))
    p[:, model.classes_.astype(int)] = model.predict_proba(np.asarray(X, dtype=float))
    return p


for d in days:
    n = len(d["rows"])
    starts = list(range(0, n - WINDOW + 1, STEP))
    d["new_feat"] = [new._build_features(d["rows"][s:s + WINDOW], d["air"])[0] for s in starts]
    d["old_feat"] = [old._build_features(d["rows"][s:s + WINDOW], d["air"])[0] for s in starts]
    d["X_new"] = np.array([[f[c] for c in FEATURES] for f in d["new_feat"]])
    d["X_old"] = np.array([[f[c] for c in FEATURES] for f in d["old_feat"]])
    d["P_new"] = batch_proba(MODEL, d["X_new"])
    d["P_old"] = batch_proba(MODEL, d["X_old"])

K = N_WIN = (SCAN_ROWS - WINDOW) // STEP + 1  # 3


def legacy_decide(mod, proba, lfeat):
    raw_pred = int(np.argmax(proba))
    pred, early = mod._early_stage_override(raw_pred, proba, lfeat)
    if not early:
        pred, _ = mod._overripe_override(raw_pred, proba, lfeat)
    return pred


# 每個版本：給 (day, 窗口起點索引 k) → (最終預測, 各子窗口預測)
def v_A(d, k):  # 舊 gateway：舊特徵（原始比值）+ 舊後處理，單窗口
    p = d["P_old"][k]
    return legacy_decide(old, p, d["old_feat"][k]), [int(np.argmax(p))]


def v_B(d, k):  # 修正特徵，單窗口，raw
    p = d["P_new"][k]
    return int(np.argmax(p)), [int(np.argmax(p))]


def v_C(d, k):  # 修正特徵，三窗口平均，raw
    P = d["P_new"][k:k + K]
    return int(np.argmax(P.mean(axis=0))), [int(np.argmax(x)) for x in P]


def v_D(d, k):  # 修正特徵，三窗口平均 + 舊後處理（規則用舊比值）
    P = d["P_new"][k:k + K]
    return legacy_decide(new, P.mean(axis=0), new._legacy_feat(d["new_feat"][k + K - 1])), \
        [int(np.argmax(x)) for x in P]


VARIANTS = {
    "A 舊版 單窗口+舊特徵+舊後處理": v_A,
    "B 新版 單窗口+修正特徵": v_B,
    "C 新版 三窗口+修正特徵": v_C,
    "D 新版 三窗口+修正特徵+Legacy": v_D,
}
BAD_PIDS = {5, 6}  # 訓練時特徵被中位數取代的鳳梨


def report(name, yt, yp, extra=""):
    cm = confusion_matrix(yt, yp, labels=[0, 1, 2, 3])
    P, R, F, _ = precision_recall_fscore_support(yt, yp, labels=[0, 1, 2, 3], zero_division=0)
    print(f"\n==== {name} {extra}")
    print(pd.DataFrame(cm, index=[f"真{i}" for i in range(4)], columns=[f"預{i}" for i in range(4)]).to_string())
    print(pd.DataFrame({"precision": P, "recall": R, "f1": F}, index=[f"S{i}" for i in range(4)]).round(3).T.to_string())
    return cm, P, R, F


def sliding(fn, d):
    # 在整段資料上滑動（起點每 STEP 筆），回傳各起點的預測
    return [fn(d, k)[0] for k in range(0, len(d["P_new"]) - K + 1)]


y = np.array([d["y"] for d in days])
summary = []
for name, fn in VARIANTS.items():
    out = [fn(d, 0) for d in days]
    pred = np.array([o[0] for o in out])
    cm, P, R, F = report(name, y, pred, "（部署模型，資料開頭 50 筆）")
    agree = [np.mean([s == o[0] for s in o[1]]) for o in out if len(o[1]) == K]
    cons, flips = [], []
    for d in days:
        ps = sliding(fn, d)
        cons.append(max(ps.count(v) for v in set(ps)) / len(ps))
        flips.append(np.mean([a != b for a, b in zip(ps, ps[1:])]) if len(ps) > 1 else 0.0)
    ok = np.array([d["pid"] not in BAD_PIDS for d in days])
    summary.append({
        "版本": name,
        "acc": round(float(np.mean(pred == y)), 3),
        "acc(排除05/06)": round(float(np.mean(pred[ok] == y[ok])), 3),
        "macroF1": round(float(np.mean(F)), 3),
        "S3_recall": round(float(R[3]), 3),
        "S3→S1": int(cm[3, 1]),
        "S3→S0/S1": int(cm[3, 0] + cm[3, 1]),
        "三窗口一致率": round(float(np.mean(agree)), 3) if agree else None,
        "滑動一致率": round(float(np.mean(cons)), 3),
        "相鄰翻轉率": round(float(np.mean(flips)), 3),
    })

print("\n==== 總表（部署模型 a57dbbbf…，in-sample：模型訓練時見過這些天的開頭 30 筆）")
print(pd.DataFrame(summary).to_string(index=False))

# ── Stage 3 依鳳梨拆開 ──
print("\n==== Stage 3（過熟）各鳳梨的預測（A 舊版 / C 新版三窗口）")
for pid in sorted({d["pid"] for d in days if d["y"] == 3}):
    ds = [d for d in days if d["pid"] == pid and d["y"] == 3]
    a = [v_A(d, 0)[0] for d in ds]
    c = [v_C(d, 0)[0] for d in ds]
    print(f"pid {pid:2d}: {len(ds)} 天  A={a}  C={c}")

# ── 鳳梨 05/06：訓練時的特徵 vs 正確讀取後的特徵 ──
print("\n==== 鳳梨 05/06 正確讀取後，部署模型的預測（模型訓練時這些天只看到中位數）")
for pid in sorted(BAD_PIDS):
    ds = sorted([d for d in days if d["pid"] == pid], key=lambda d: d["date"])
    print(f"pid {pid}: 標籤 {[d['y'] for d in ds]}")
    print(f"        C預測 {[v_C(d, 0)[0] for d in ds]}")

# ── LOGO：同 ET 參數、修正後特徵、留一顆鳳梨重訓 ──
# 每一折只用訓練組資料（目前特徵沒有缺值，不需補值；若有缺值，用訓練組中位數補）
print("\n==== LOGO（留一顆鳳梨）重訓 ET：只用人工標籤、修正後特徵、正確讀取的 05/06")
params = MODEL.get_params()
pids = np.array([d["pid"] for d in days])
Xtr0 = np.array([d["X_new"][0] for d in days])
res = {"B": [], "C": []}
slide = {"B": [], "C": []}
per_pid = []
for pid in sorted(set(pids)):
    tr = pids != pid
    Xtr = Xtr0[tr].copy()
    med = np.nanmedian(Xtr, axis=0)
    Xtr = np.where(np.isnan(Xtr), med, Xtr)
    m = ExtraTreesClassifier(**params).fit(Xtr, y[tr])
    hits = []
    for d in [d for d in days if d["pid"] == pid]:
        Xd = np.where(np.isnan(d["X_new"]), med, d["X_new"])
        Pd = batch_proba(m, Xd)
        b = int(np.argmax(Pd[0]))
        c = int(np.argmax(Pd[:K].mean(axis=0)))
        res["B"].append((d["y"], b))
        res["C"].append((d["y"], c))
        hits.append(c == d["y"])
        nb = len(Pd) - K + 1
        bs = [int(np.argmax(Pd[k])) for k in range(nb)]
        cs = [int(np.argmax(Pd[k:k + K].mean(axis=0))) for k in range(nb)]
        for key, ps in (("B", bs), ("C", cs)):
            slide[key].append(max(ps.count(v) for v in set(ps)) / len(ps))
    per_pid.append((int(pid), len(hits), round(float(np.mean(hits)), 2)))

for key in ("B", "C"):
    yt, yp = np.array(res[key]).T
    F = precision_recall_fscore_support(yt, yp, labels=[0, 1, 2, 3], zero_division=0)[2]
    report(f"LOGO {key}", yt, yp,
           f"acc={np.mean(yt == yp):.3f} macroF1={np.mean(F):.3f} 滑動一致率={np.mean(slide[key]):.3f}")
print("\nLOGO C 各鳳梨準確率 (pid, 天數, acc)：", per_pid)
