# Gateway 歷史資料回測與讀檔稽核

這個資料夾只放評估程式與結果，**不屬於 Raspberry Pi 的執行目錄**，也沒有修改任何部署模型。

| 檔案 | 內容 |
|---|---|
| `audit_reader.py` / `audit_reader.csv` | 逐檔比較訓練 notebook 的 `read_raw_xlsx` 與正確讀法，找出讀錯的原始檔 |
| `backtest.py` / `backtest_out.txt` | 用歷史資料比較 4 個 gateway 版本，並做 LOGO 重訓評估 |

執行（需要 `enose_model_training/orkspace/data/raw/`、`pineapple_final/` 與 git）：

```bash
python -u audit_reader.py
python -u backtest.py > backtest_out.txt
```

## 資料

- 標籤：`data_label_audit_report.xlsx` 的 `all_key_audit`（人工標籤，未使用複查後標籤或偽標籤）
- 有標籤且資料足夠 50 筆的天數：101 天、13 顆鳳梨；標籤分布 0:32、1:27、2:27、3:15
- `pineapple_11_20260214.xlsx`、`pineapple_13_20260304.xlsx` 沒有資料表頭，略過
- 讀檔改為尋找 `timestamp_ms` 那一列當欄名；標準格式檔案的結果與 notebook 相同

## 讀檔稽核結果

notebook 的 `read_raw_xlsx` 固定把第 2 列當欄名。鳳梨 05、06 的檔案欄名在第 1 列，因此：

- 17 個鳳梨檔、17 個空氣檔讀不到感測欄（05：10 天、06：7 天）
- `compute_features_one_day` 得到全 NaN，之後被**全體資料**中位數補值
- 其中 15 天有人工標籤（0:13、1:1、2:1）

## 四個版本（部署模型 `a57dbbbf…`，每天資料開頭 50 筆）

| 版本 | 說明 |
|---|---|
| A | 舊 gateway（commit `4e1a93d`）：原始讀值比值 + 舊後處理，單窗口 |
| B | 新 gateway：正規化比值，單窗口，raw |
| C | 新 gateway：正規化比值，三窗口平均，raw（目前預設） |
| D | C + 舊後處理規則（規則使用舊比值） |

「滑動一致率」與「相鄰翻轉率」：在同一天整段資料上，起點每 10 筆滑動一次重新判斷。

## 已知限制（解讀結果前請先看）

1. **A～D 是 in-sample。** 部署模型訓練時看過這些天的開頭 30 筆，準確率偏樂觀；只適合比較版本間的相對差異。
2. **05/06 對部署模型而言不是 in-sample。** 模型訓練時只看到中位數，因此另外列出排除 05/06 的準確率。
3. **LOGO 的留出單位是整顆鳳梨（pineapple_id）**，同一顆鳳梨的所有日期都只在測試組。
4. **LOGO 使用固定的 11 個部署特徵。** 這組特徵是當初用全部資料選出的，沒有在每一折內重新選擇，所以 LOGO 結果若有偏差，應該是**偏樂觀**。補值只用訓練組中位數（目前資料實際上沒有缺值）。
5. **LOGO 只用 101 天人工標籤**，訓練資料比原 notebook（含偽標籤）少，與 notebook 的 73% / 92.5% 不是同條件比較。
6. 歷史資料是每天一次的連續記錄，不是同一顆鳳梨反覆取放的實驗；能評估窗口位置敏感度，**不能證明感測器恢復問題已解決**。
