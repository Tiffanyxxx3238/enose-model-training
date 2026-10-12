# 實際推論路徑稽核（Phase A）

**結論：COMPETITION PATH NOT VERIFIED。** repo 內有 4 條可能的推論路徑，但無法從 repo 判定比賽／展示當天 Pi 上實際跑的是哪一條、哪個版本。本次依規定未登入 Pi，因此無法驗證。

證據等級：**Code** = 從 repo 程式碼讀出；**Replay** = 離線重播驗證；**Unverified** = 需要 Pi 上的實際檔案或紀錄。

## 路徑總表

| | A：網頁（Web CLI） | B：App Gateway v2 | C：舊 Gateway（v1） | D：App mock／demo |
|---|---|---|---|---|
| 入口 | 筆電瀏覽器 → `pineapple_final/app_local.py`（Flask） | Consumer App → `pineapple_app_gateway/app_gateway_v2.py` | `pineapple_app_gateway/app_gateway.py` | Consumer／Farmer App |
| 端點 | `/air`、`/infer`、`/demo_air`、`/demo_infer` | `POST /calibrate`、`POST /scan`、`GET /status` | `/ripeness/calibrate`、`/ripeness/infer`（port 8000） | 無（本機產生） |
| 傳遞方式 | paramiko SSH 到 Pi，在 `/home/linguanyu/pineapple` 執行 CLI，再用 regex 解析 stdout | Pi 上同一行程內推論 | subprocess 呼叫 `inference_30s.py`／`calibrate_air_30s.py` | — |
| 推論程式 | `inference_30s.py` | `app_gateway_v2.py` 內建 `build_features` | `inference_30s.py`（同 A） | — |
| 模型 | `deploy_student.pkl`（Pi 上的副本） | `PINEAPPLE_DIR/deploy_student.pkl` | 同 A | 無 |
| AIR 來源 | `air_base.json`（原版 demo 也寫這個檔） | `PINEAPPLE_DIR/air_base.json` | 同 A | 無 |
| 特徵 | 原版：2 個比值錯誤 → **本次已修** | 已在 `fix/gateway-feature-consistency` 修正（Step 2 驗證完全一致） | 同 A（呼叫同一支 CLI；Pi 上的副本是否已更新：Unverified） | — |
| 後處理 | 原版：early／overripe override → 本次預設 raw | 舊規則改用 raw ratio 診斷（legacy view） | 同 A | — |
| 顯示 | `app_local.py` 解析「成熟度判定」「原始模型分類」「校正後分類」與機率 | App 顯示 `/status` 的 JSON | JSON | 隨機或固定值 |
| mock／demo | `--demo` 讀本機 xlsx，**不是真實感測** | 無 random fallback | — | Farmer BatchScanScreen：**永遠亂數**；Consumer `buildOfflineMock`：存在但未被呼叫 |
| 證據等級 | Code + Replay；Pi 上版本 Unverified | Code + Replay（Step 2）；Pi 上版本 Unverified | Code；Pi 上版本 Unverified | Code |

## 主要依據（行號為本分支修改後的檔案）

- `pineapple_final/app_local.py`：Flask 路由 → `run_remote_script` → SSH 執行 `python3 inference_30s.py --warmup-sec N` 或 `--demo --demo-case X --demo-stage Y`；stdout 由約第 233–323 行的 regex 解析。
- 原版 `inference_30s.py`（`799552c`）：
  - 第 394–395 行：比值使用原始 ADC 平均。
  - 第 383–386 行：`base_value` 缺值時回傳 1.0。
  - 第 643 行：`feat.get(f, 0.0)` 會把缺少的特徵默默補 0。
  - 第 662、675 行：early／overripe override。
  - 第 572 行：serial 少於 30 列時照樣推論。
- `app_gateway_v2.py`：第 40、43 行模型與 AIR 路徑；第 413–425 行為已修正的比值；第 1053、1074、1113 行為路由。
- `app_gateway.py`：第 745–800 行以 subprocess 呼叫 `calibrate_air_30s.py`／`inference_30s.py`；第 824 行 port 8000。
- Consumer App：`SensorContext.startScan` → `apiStartScan()`（`POST /scan`）＋輪詢 `/status`，也就是走路徑 B。

## 需要人工在 Pi 上確認（REQUIRES MANUAL AUTHORIZATION）

1. `/home/linguanyu/pineapple/` 內 `inference_30s.py`、`calibrate_air_30s.py`、`app_gateway*.py` 的 SHA-256，與本分支比對。
2. `deploy_student.pkl` 的 SHA-256 是否為 `a57dbbbf…16a1`。
3. 展示時實際啟動的是 v1 還是 v2 Gateway（systemd／`start_server.sh`／shell history）。
4. `air_base.json` 的內容與修改時間（是否曾被 demo 校正覆蓋）。
