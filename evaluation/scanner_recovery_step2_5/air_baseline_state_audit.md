# AIR Baseline 狀態稽核（Phase D）

## 原版問題

| # | 問題 | 位置（`799552c`） | 影響 |
|---|---|---|---|
| 1 | 校正時某感測器沒有有效讀值，就把 baseline 設成 1.0 | `calibrate_air_30s.py` 第 171 行 | 正規化特徵放大數百倍，推論結果無意義。已實測：缺 TGS2602 時 baseline＝1.0 |
| 2 | 推論端 `base_value` 缺值時也回傳 1.0 | `inference_30s.py` 第 383–386 行 | 同上，而且沒有任何警告 |
| 3 | demo 校正與實測校正都寫入 `air_base.json` | `calibrate_air_30s.py` 第 382 行 | 在展示現場跑過 demo 後，實測會默默使用 demo 檔案的空氣值 |
| 4 | baseline 沒有來源、時間、樣本數 | — | 無法判斷 baseline 是否過期或來自哪次校正 |
| 5 | 沒有範圍檢查 | — | 感測器斷線（0）或飽和（1023）的值會被當成 baseline |

## 本次修正（最小修正）

- `calibrate_air_30s.py`
  - `MODEL_SENSORS` 都必須有有效讀值，否則 `AirCalibrationError`。TGS2620 不在模型中，缺值時略過。
  - baseline 必須介於 10–1000（與韌體 `isValidMQRaw` 相同）。
  - 輸出 `_meta`：`source`（demo／live）、`calibration_id`（uuid4）、`created_at`（UTC ISO）、`sample_count`、`model_sensors`，demo 另記 `demo_case`／`air_file`，live 另記 `port`／`duration_sec`。
  - 實測樣本少於 30 列時印出警告。
  - `--out` 預設依模式：demo 寫 `air_base_demo.json`，live 寫 `air_base.json`。
- `inference_30s.py`
  - `load_air`：檔案不存在就報錯；做範圍驗證；印出並記錄 provenance（含 `age_sec`）；實測模式拒絕 `source=demo` 的 baseline（`--allow-demo-air` 可強制）。
  - 沒有 `_meta` 的舊檔案仍可使用（source 視為 unknown），但會顯示出來，以維持相容。

## 刻意未做

- **沒有設定 baseline 有效期限。** 目前沒有資料可以決定 baseline 多久會失效（這正是 Step 3 AIR sensitivity 要回答的問題），因此只記錄 `age_sec`，不拒絕舊 baseline，也不編造期限值。
- 沒有改 Gateway v2 的 AIR 流程（它有自己的 `air_base.json` 處理，本次不在範圍內）。

## 相容性注意

- `app_local.py` 的 `parse_air_output` 取 stdout 最後的 JSON，現在 JSON 會多一個 `_meta` 字典，網頁 UI 可能多顯示一列 `_meta`。這只影響顯示，不影響推論；如要隱藏，需另行修改 `app_local.py`（本次未改）。
- 部署到 Pi 後，第一次實測前**必須重新做一次實測空氣校正**，以產生帶有 `source=live` 的 `air_base.json`。

## 測試（T4）

缺檔 → rc=2；demo 預設檔不存在 → rc=2；缺 TGS2602 或 MQ3=1.0 → rc=2；實測模式使用 demo baseline → rc=2；校正缺值 → `AirCalibrationError`。
