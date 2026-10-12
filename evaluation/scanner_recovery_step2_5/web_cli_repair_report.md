# Web CLI 修正報告（Phase B）

檔案：`pineapple_final/inference_30s.py`（原版 SHA 前綴 `92daa9a1`，基準 commit `799552c`）。模型、`feature_columns.json`、`deploy_meta.json` 都未修改。

## 修正內容

| # | 問題（原版） | 修正 |
|---|---|---|
| 1 | `MQ2_MQ3_ratio`、`MQ3_MQ135_ratio` 用原始 ADC 平均相除（第 394–395 行） | 改為 `mean_norm(a)/(mean_norm(b)+1e-9)`，與訓練 `add_cross_ratio_features` 一致；原始比值另存為 `*_raw_ratio`（只用於診斷） |
| 2 | 其他 9 個特徵 | 逐一和訓練 notebook 的 `compute_features_one_day` 比對，原本就一致（T1） |
| 3 | early／overripe override 以錯誤比值調門檻，會默默改判 | 新增 `--postprocess {raw,legacy}`，預設 `raw`：顯示＝模型原始判定；舊規則以 `legacy_view`（原始比值）計算並只印出診斷。`legacy` 模式可重現舊行為 |
| 4 | 缺少的特徵默默補 0（第 643 行） | 缺特徵或 NaN／Inf 時報錯 |
| 5 | `base_value` 缺值時用 1.0 | `validate_air`：5 個模型感測器都必須存在、有限，且在 10–1000 之間，否則報錯 |
| 6 | 無效列（非數字、超出 ADC 範圍）未過濾 | `parse_sensor_row` 拒絕非數字、非有限值，以及超出 0–1023 的列 |
| 7 | serial 不足 30 列也照樣推論；demo 不足時也照樣推論 | 必須剛好 30 列有效資料（serial 取最後 30 列），否則 `InputValidationError`，exit code 2，印出「❌ 無法推論：…」 |
| 8 | 無法追溯 | 輸出模型 SHA-256、AIR 來源（路徑／SHA／source／calibration_id／created_at／age_sec）、後處理模式；`--trace-json` 寫出完整鏈：raw rows → AIR → features → proba → raw／final／displayed |
| 9 | demo 與實測共用 `air_base.json` | `--air` 預設依模式選擇：demo 用 `air_base_demo.json`，實測用 `air_base.json`；實測模式拒絕 source=demo 的 baseline（除非加上 `--allow-demo-air`） |

**相容性**：stdout 格式（「成熟度判定：」「原始模型分類：Stage」「校正後分類：Stage」「成熟度條」、機率列、特徵區塊）保持不變，`app_local.py` 的 regex 仍可解析。raw 模式下「校正後分類」＝「原始模型分類」。

## 驗證

- 特徵一致性（`feature_parity.csv`）：在 103 天資料上，修正版 vs 訓練參考最大絕對差 1.58e-14。原版在 101 天上有 2/11 個特徵不一致（中位相對差 38%、85%）。2 天新讀到的資料中，原版有 4 個特徵不一致，修正版 0 個。
- 機率一致性：最大差 3.47e-18。
- 確定性：模組層與真實 CLI 各重跑 5 次，結果相同。
- CLI 實際執行（subprocess、假 serial／paramiko、暫存 demo 目錄）在 5 個 QA case 上與重播的 C2 完全相同。

## 未修改／刻意保留

- 3 窗平均（C3）**沒有**放進 CLI：離線結果沒有改善（acc 0.663→0.644，S0 recall 0.312→0.250），只列為候選。
- `print_feature_summary` 仍用 `feat.get(f, 0.0)`，但只影響顯示，不影響推論。
- `app_local.py` 只做憑證修正，未改推論或顯示邏輯。
