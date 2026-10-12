"""Audit: what the training notebook's read_raw_xlsx actually produced for each raw file."""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ORK = HERE.parent / "enose_model_training/orkspace"
RAW = ORK / "data/raw"
SENSORS = ["MQ2", "MQ3", "MQ9", "MQ135", "TGS2602"]


def notebook_reader(path):  # 原封不動照抄 notebook Cell 5
    raw = pd.read_excel(path, header=None)
    col_names = raw.iloc[1].tolist()
    df = raw.iloc[3:].copy()
    df.columns = col_names
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all").reset_index(drop=True)


def correct_reader(path):
    raw = pd.read_excel(path, header=None)
    hdr = [i for i in range(min(10, len(raw))) if str(raw.iloc[i, 0]).strip() == "timestamp_ms"]
    if not hdr:
        return None
    df = raw.iloc[hdr[0] + 1:].copy()
    df.columns = raw.iloc[hdr[0]].tolist()
    return df.apply(pd.to_numeric, errors="coerce").dropna(how="all").reset_index(drop=True)


audit = pd.read_excel(ORK / "data_label_audit_report.xlsx", sheet_name="all_key_audit")
audit = audit[audit.has_raw_fruit == 1]

rows = []
for _, a in audit.iterrows():
    for kind, fname in (("fruit", a.fruit_file), ("air", a.air_file)):
        if not isinstance(fname, str):
            continue
        path = RAW / fname
        try:
            nb = notebook_reader(path)
            nb_ok = all(f"{s}_raw" in nb.columns for s in SENSORS)
            nb_err = None
        except Exception as e:
            nb_ok, nb_err = False, type(e).__name__
        good = correct_reader(path)
        if nb_err:
            status = "讀檔例外（notebook 直接失敗）"
        elif nb_ok:
            status = "正常"
        elif good is None:
            status = "檔案本身無資料表頭（兩種讀法都讀不到）"
        else:
            status = "欄名錯位（notebook 讀不到感測欄 → 特徵 NaN）"
        rows.append({"pid": int(a.pid), "date": int(a.date), "kind": kind, "file": fname,
                     "label": a.stage, "status": status,
                     "rows_correct": None if good is None else len(good)})

df = pd.DataFrame(rows).drop_duplicates(["file", "kind"])
print("== 每個檔案的讀取結果")
print(df.groupby(["status", "kind"]).size().unstack(fill_value=0).to_string())

bad = df[df.status != "正常"]
print("\n== 受影響的 pid")
print(bad.groupby(["pid", "kind"]).size().unstack(fill_value=0).to_string())

fruit_bad = bad[bad.kind == "fruit"]
print("\n== 受影響的鳳梨天數（fruit 檔）中，有人工標籤的：")
lab = fruit_bad[fruit_bad.label.notna()]
print(f"{len(lab)} 天；標籤分布 {lab.label.astype(int).value_counts().sort_index().to_dict()}")
print("全部有標籤的天數：", int(audit.stage.notna().sum()))

# notebook 之後的處理：compute_features_one_day 在欄位不存在時填 NaN，
# build_window_feature_table 再用「全部資料」的中位數補值（未分訓練／測試）
print("\n== 結論")
print("欄名錯位的鳳梨檔 → compute_features_one_day 全部感測特徵 = NaN → fillna(全資料中位數)")
print("欄名錯位的空氣檔 → baseline 改用 pid_fallback_baseline（該 pid 第一天鳳梨檔），"
      "但若第一天鳳梨檔也錯位，fallback 會 except → 全部 1.0")
df.to_csv(HERE / "audit_reader.csv", index=False, encoding="utf-8-sig")
