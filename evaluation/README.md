# Gateway 歷史資料回測與讀檔稽核

這個資料夾只放評估程式與結果，**不屬於 Raspberry Pi 的執行目錄**，也沒有修改任何部署模型。

| 檔案 | 內容 |
|---|---|
| `audit_reader.py` / `audit_reader.csv` | 逐檔比較訓練 notebook 的 `read_raw_xlsx` 與正確讀法，找出讀錯的原始檔 |
| `eval_common.py` | 共用的資料讀取（gateway 模組、部署模型、原始資料、人工標籤） |
| `backtest.py` / `backtest_out.txt` | 用歷史資料比較 4 個 gateway 版本，並做 LOGO 重訓評估 |
| `retrain_round1.py` / `retrain_round1_out.txt` | 第一輪重新訓練：特徵穩定度分析 + 嚴格 LOGO（每折重新選特徵） |
| `retrain_round2.py` / `retrain_round2_out.txt` | 第二輪：4 類／3 類 × 單窗口／多窗口訓練 |
| `round3_diagnosis.py` / `round3_diagnosis.md`（輸出：`round3_*.csv/png`、`round3_results/`） | 第三輪：標籤一致性、動態訊號、Stage 2 誤判歸因 |
| `round4_analysis.py` / `round4_report.md`（輸出：`round4_results/`） | 第四輪：資料品質、訊號表示、群組／月份混雜、探索性 PCA 校正、溫濕度、訊號對空氣波動比 |
| `reliability_phase1.py` / `reliability_phase1_report.md`（輸出：`reliability_phase1_results/`） | 可靠度研究 Phase 1：預測信心能否辨識判錯（只讀既有 LOGO 預測，不訓練模型） |

執行（需要 `enose_model_training/orkspace/data/raw/`、`pineapple_final/` 與 git）：

```bash
python -u audit_reader.py
python -u backtest.py > backtest_out.txt
python -u retrain_round1.py > retrain_round1_out.txt
python -u retrain_round2.py > retrain_round2_out.txt
python -u round3_diagnosis.py > round3_results/round3_run_log.txt
python -u round4_analysis.py > round4_results/round4_run_log.txt   # 約 15～20 分鐘（含 10 個亂數種子）
python -u reliability_phase1.py > reliability_phase1_results/phase1_run_log.txt
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

## 第一輪重新訓練（`retrain_round1.py`）

- 只用 101 天人工標籤；ExtraTrees 參數與部署模型相同；**不匯出模型，不修改部署包**
- 特徵池：gateway 池（15 個，可直接部署）、擴充池（76 個，notebook 的各感測器統計量 + 兩兩比值，部署需擴充 gateway）
- 每折特徵選擇只用訓練組 12 顆鳳梨：依「鳳梨內與成熟階段的 Spearman 相關 × 各鳳梨方向一致比例」排序取前 k
- 主要設定事先指定為 k=8；k=5、11 只作敏感度參考
- 特徵穩定度分析使用全部資料，只用來描述，不拿來決定最終特徵

## 第二輪（`retrain_round2.py`）

- 三類：Stage 0+1 → 未熟、Stage 2 → 成熟／可食、Stage 3 → 過熟；3 類模型是**重新訓練**，不是把 4 類預測合併（合併結果另列為參考）
- 多窗口：每天開頭 150 秒內 5 個不重疊 30 秒窗口（起點 0/30/60/90/120 筆），每窗口權重 1/5；只擴增訓練鳳梨，測試仍用開頭三窗口
- 多數類別基準：4 類 0.317（macroF1 0.120）；3 類 0.584（macroF1 0.246）
- 101 天的準確率標準誤約 ±0.05，2～5 個百分點的差異不能視為確定改善

## 第三輪（`round3_diagnosis.py`，報告 `round3_diagnosis.md`）

- 重現第二輪主要基準（4 類／FIXED11／多窗口訓練／三窗口測試），並匯出逐日 LOGO 預測（`round3_logo_predictions.csv`）
- 發現 2 天鳳梨檔與空氣檔逐筆相同（鳳梨 3 號 02-14、4 號 02-06）；鳳梨讀值中位數 ≤ 空氣基準；空氣基準絕對值主要由標註群組決定
- `retrain_round2.py` 只增加逐日診斷輸出並移入 `__main__`，`retrain_round2_out.txt` 逐字相同

## 第四輪（`round4_analysis.py`，報告 `round4_report.md`）

- 事先指定 15 個方法：4A 資料品質（A0、A1、A2）、4B 訊號表示（B0 FIXED11、Raw、S−B、S/B、log S/B、S/B＋B）、4D 探索性 PCA 校正（log 空間，k=0/1/2）、4E 溫濕度（輸入／訓練折線性補償）
- 事後診斷（非預先指定，只用於解讀）：只計群組 A＋B／C＋D、留出整個群組、亂數種子 0～9、鳳梨−空氣差距 vs 空氣漂移
- 4D 是 PCA-based exploratory correction，**不是** CPCA 或 Direct Standardization（缺少參考氣體與轉移樣本，見報告 E 節）
- 主要結論：跨鳳梨 LOGO 下看似的改善主要來自群組捷徑；留出整個群組時所有方法 ≤ 0.34

## 可靠度研究 Phase 1（`reliability_phase1.py`，報告 `reliability_phase1_report.md`）

- 輸入：`round3_logo_predictions.csv` 的 FIXED11 列（4 類／多窗口訓練／三窗口測試的 LOGO out-of-fold 預測）
- 指標：1−最高機率、1−Top-2 差距、正規化熵的 Error AUROC；以 pineapple_id 為 cluster 的 bootstrap（2000 次）；群組、Stage、逐顆鳳梨分析
- Window Disagreement：NOT AVAILABLE（只有三窗口平均機率）
- 決定：**STOP**（三種 AUROC 0.50～0.59，CI 都包含 0.5；最高機率 ≥0.70 的 8 天中 6 天判錯；Stage 2 方向相反）
- 未執行 Phase 2：沒有選門檻、沒有拒判、沒有訓練新模型
