# PineNose Step 5 — 完整離線系統驗收報告

- Worktree：`C:/Users/user/enose-step5-offline-acceptance`
- 分支：`analysis/step5-offline-acceptance`
- 基準：`8e051578`（Step 4B）
- 預先登錄的驗收標準：`step5_protocol.md`，在任何重播或生命週期測試之前就已 commit（`e78425b2`）

**重要：離線軟體驗收 ≠ 模型準確度驗證 ≠ Raspberry Pi 硬體驗證。** 嚴格 LOGO 準確率仍約 0.424。沒有任何模型因本步驟被核准。

## 驗收結果

| 類別 | 結果 | 依據 |
|---|---|---|
| A. 離線 Python 後端 | **PASS** | 見下方 |
| B. App 建置與 API | **PASS** | 見下方 |
| C. 離線端到端 | **PASS** | 見下方 |
| D. 發布一致性 | **PASS**（含 OPEN 項目） | 見下方 |
| E. 實體硬體 | **NOT TESTED** | Step 5 不連接 Pi、序列埠或感測器 |
| **整體 Step 5 離線驗收** | **PASS（離線軟體範圍）** | A–D 全部 PASS。沒有任何關鍵的實際進入點測試是 BLOCKED 或 FAIL。兩個 App 都通過編譯與打包。原生建置與裝置測試另列為 BLOCKED |

**A. 離線 Python 後端（PASS）**
- Step 4B 回歸：85／85。
- 突變檢查：4／4 抓到。
- 生命週期：11／11。
- 儲存完整性：Python 7／7。
- Gateway HTTP 契約：29／29。
- 執行環境為釘選版本：sklearn 1.8.0、numpy 2.4.3、pandas 3.0.1。

**B. App 建置與 API（PASS）**
- 兩個 App 的 `tsc --noEmit` 都是 exit 0。
- Expo export 的 web 與 Android（Hermes）打包都是 exit 0。
- 整合測試：Consumer 26／26、Farmer 4／4，另以 App 的驗證程式檢查 99 筆重播回應。
- 原生 APK／IPA 與裝置測試為 **BLOCKED**，另列。

**C. 離線端到端（PASS）**
- S99 共 99 個水果日，在兩種環境都是 99／99 PASS。
- 預先宣告的容差全部符合。
- 無效掃描都被拒絕。

**D. 發布一致性（PASS，含 OPEN 項目）**
- 已產出相容性清單。
- 已驗證：FIXED11、序列埠欄位對應、模型 SHA、設定權限、TEST 標記、儲存分離、錯誤碼。
- 依預先登錄的規則，有提案但尚未套用的衝突列為 OPEN，不判為 FAIL：
  - 服務埠衝突（R08）；
  - 啟動腳本（R09）；
  - Farmer 的鎖定檔與 lint 設定。
- 祕密：本分支 HEAD 已乾淨，但 **git 歷史仍含外洩的密碼，必須更換**。

## 1. 實際執行的元件

| 元件 | 實際進入點 | 測試方式 |
|---|---|---|
| Gateway v2 | `pineapple_app_gateway/app_gateway_v2.py`：`/calibrate`、`/scan`、`/status`、`/cancel`、`/scan_records`、`/feedback`、`/health` | Flask test client。也透過真實 HTTP（只綁 127.0.0.1）供 App 測試。序列埠為假序列埠 |
| 安全層 | `pineapple_final/pinenose_safety.py` | 由 Gateway 與 CLI 實際呼叫 |
| 網頁推論 CLI | `inference_30s.py` `main()`，含 `--trace-json` | 程序內執行，假序列埠 |
| AIR 校正 | Gateway `/calibrate`；`calibrate_air_30s.py` `main()` | 以假序列埠重播歷史 AIR 列 |
| 網頁成熟度頁 | `app_local.py` `/infer` | 「遠端輸出」換成 CLI 的實際輸出（不使用 SSH） |
| 整合網頁 | `整合網頁/pineapple_unified_web/app.py` `/` | 只是 iframe 容器，指向寫死的 `192.168.0.152:5000`／`:5002` |
| Consumer App | `services/api.ts`、`SensorContext`、`CalibrationContext`、`HistoryContext`、`storage`、`app/processing.tsx`、`app/result.tsx` | App 自己的 TS 原始碼在 Node 執行，對真實 Gateway。另做 `tsc` 與 Expo 打包 |
| Farmer App | `services/api.ts`、`BatchScanScreen`、`BatchSummaryScreen`、`AppProvider` | 同上 |
| 掃描紀錄與 TEST 儲存 | Gateway 的 `scan_history/*.jsonl`；App 的 AsyncStorage 兩個 key | 真實檔案系統；記憶體版 AsyncStorage |

沒有建立任何替代 App、替代 Gateway 或獨立展示腳本。測試替身限於以下幾類：
- 假序列埠；
- SSH 替換；
- 原生模組（AsyncStorage、expo-router、圖示等）；
- 時鐘。

## 2. 完整歷史重播（Step 5B）

- **重播範圍：**
  - S99 共 **99 個不重複的水果日**，來自 13 顆鳳梨，每天只算一次。
  - 沒有重複窗口。
- **排除：** 共 78 列，見 `replay_exclusions.csv`。
  - S100 中有 1 天不在 S99：它的水果檔與 AIR 檔完全相同（R1 的 FRUIT_EQ_AIR 規則）。
  - 另外 77 列來自 R1 `excluded_samples.csv`：沒有原始檔、沒有人工標籤，或 AIR 超出範圍。
- **是否忠於原始取樣方式：**
  - 假序列埠以 1 Hz 列時鐘輸出（每讀一列，模擬時間前進 1 秒）。
  - Gateway 使用 W0，即暖機為 0 時的前 30 列。
  - CLI 收集 30 秒、取最後 30 列；經 trace 驗證，這 30 列與 W0 逐列相同。
  - AIR 經真實 `/calibrate` 計算，與 R1 的 `air_A0`（前 30 列平均）相對差 ≤ 2.2e-16。
  - 保留 C2 單窗口 30 秒契約：沒有多窗口平均、投票、AIR 改判或窗口一致性拒絕。
- **溯源：**
  - 重播產生的 AIR `_meta.source` 寫的是 `live`，因為這是程式碼路徑的行為。
  - 暫存檔已加註 `test_fixture_note: …NOT a real measurement`，執行完即刪除。
  - 沒有任何合成來源被當作實測。

| 指標（容差） | 釘選環境 Py 3.12.7／sklearn 1.8.0／numpy 2.4.3 | 本機 Py 3.10.11／sklearn 1.7.1／numpy 2.2.6 |
|---|---|---|
| PASS 天數 | **99／99** | **99／99** |
| FIXED11：Gateway vs CLI（≤1e-9） | 0.0 | 0.0 |
| FIXED11：Gateway vs R1 訓練管線（≤1e-9） | 2.2e-16 | 2.2e-16 |
| AIR：Gateway `/calibrate` vs R1（相對 ≤1e-9） | 2.2e-16 | 2.2e-16 |
| 機率：Gateway API（6 位小數）vs CLI（≤5e-7） | 4.8e-7 | 4.8e-7 |
| 機率：網頁顯示 vs CLI（≤5e-5，顯示 4 位小數） | 4.3e-5 | 4.3e-5 |
| Stage：Gateway＝CLI＝網頁 | 99／99 | 99／99 |
| 重複執行逐位元相同（Gateway 與 CLI） | 99／99 | 99／99 |
| API 結構檢查＋App 的 `validateRpiResult` | 99／99 | — |
| 網頁顯示 TEST 標示與判定 | 99／99 | 99／99 |
| 兩種環境之間 | — | Stage 99／99 相同；API 機率差 0.0 |

Stage 分布：0：10、1：41、2：38、3：10。這只是重播輸出，**不是準確度**。

## 3. 找到並修正的真實缺陷

| # | 元件 | 缺陷 | 如何發現 | 影響 |
|---|---|---|---|---|
| 1 | **Gateway** | **`np.trapz` 在 numpy 2.4（requirements_rpi.txt 的釘選版本）已被移除**。`except` 把錯誤吞掉並回傳 0.0，使 **`MQ2_auc_norm` 恆為 0** | 以釘選版本重播 | 修正前：99／99 天特徵錯誤（最大差 1.45），機率差最高 0.44，**3／99 天 Gateway 與 CLI 的 Stage 不同**。修正後 99／99 PASS。修正前的證據：`full_replay_results_pinned_BEFORE_trapz_fix.csv`、`logs/manual_replay_pinned_BEFORE_trapz_fix.log` |
| 2 | Gateway | `/status` 的 `mode` 與 `result_kind` 取自**查詢當下**的設定。後端由工程切到正式後，舊的 TEST 掃描在回應外層被標成 FORMAL | 生命週期 L08 | 改用掃描自己的值，另加 `backend_mode` |
| 3 | Gateway | 掃描進行中重新載入設定：結果被標成 FORMAL，卻寫入 TEST 歷史 | L09 | 改為每代設定一個 `_runtime_gen`。重新載入時在提交鎖內作廢結果（`RUNTIME_RELOADED`）。結果使用掃描自己的模式 |
| 4 | Gateway | AIR 檔損毀時 `/health` 回 500；`/scan` 只回泛用的 `SCAN_ERROR` | S01 | `load_air_file`：回 `AIR_INVALID_FILE` |
| 5 | 安全層 | 歷史檔中有非 UTF-8 的行時，整個讀取失敗（`/scan_records` 會當機） | S03 | 逐行解碼；無法解碼的行標為損毀，不刪除 |
| 6–12 | App | 7 項，見 `app_build_results.md`：Consumer 8 個 TS 錯誤（Step 4B 造成）、寫死的 `confidence 0.7`、舊上傳佇列、隨機感測值產生器；Farmer 的錯誤匯入路徑（無法編譯）、0 樣本時顯示「0.0 Brix」、錯誤的「mock 結果」文字 | `tsc`、整合測試 | 已全部修正 |
| 13 | 文件 | 追蹤中的 README 含 Pi 密碼（不輸出原值） | 祕密掃描 | 本分支已遮蔽；**歷史仍在，必須更換** |

測試程式本身的錯誤（已修正，驗收標準沒有改）：
- 重播的結構檢查誤以 JSON 鍵順序比對特徵（Flask 會排序鍵）。
- L08 的一個斷言原本寫成缺陷 #2 的錯誤行為。

## 4. 取消、逾時與歷史完整性

以下案例全部 PASS（Step 4B 回歸＋Step 5 生命週期＋App 測試）：
- 掃描中取消；
- 提交前取消；
- 寫入中取消（取消會等鎖，回 409）；
- 400 次並行壓力測試；
- 重複取消；
- 延遲完成：舊讀取尚未釋放序列埠時，新掃描回 409；之後舊結果作廢；
- 提交時逾時；
- 序列埠卡住時逾時，或卡住時取消；
- 歷史寫入失敗：模擬失敗，以及真實檔案系統（用資料夾佔住檔名）；
- 損毀行保留，新紀錄只追加；
- 上傳紀錄無法寫入時回 500；
- 未知的 scan_id 回 404；
- 缺少 scan_id 回 400；
- App 端：
  - 離開畫面時取消；
  - 輪詢逾時後取消；
  - 舊結果驗證失敗。

**無效掃描從未出現在結果歷史中**，只寫入 `scan_failures.jsonl`，且 stage 為 null。**舊結果無法覆寫新結果。**

## 5. TEST 與正式分離

- **Gateway：**
  - TEST 結果只寫入 `history_test.jsonl`，上傳只寫入 `client_uploads_test.jsonl`。
  - 宣稱為 FORMAL 的上傳回 409。
  - 切換模式不會轉換任何紀錄。
- **CLI 與網頁：** 都輸出並顯示「結果類型：TEST」。
- **Consumer App：**
  - TEST 紀錄存在獨立的 key，不上傳。
  - 結果頁顯示 TEST 標示。
  - 舊上傳佇列拒絕 TEST。
- **Farmer App：** 不產生任何結果。
- **正式模式：** 出貨的核准清單為空，Gateway、CLI、App 一律回 `MODEL_NOT_APPROVED`。

## 6. 剩餘的 BLOCKED／OPEN 項目

完整說明見 `unresolved_blockers.md`。
- 必須人工更換外洩的 Pi 憑證。
- 沒有核准模型。
- 沒有正式的 AIR 期限，也沒有實機校正。
- 實體硬體與 Pi 3 相容性：NOT TESTED。
- 原生 App 建置與裝置測試：BLOCKED。
- 服務埠衝突與啟動腳本：OPEN，已提出布局，尚未套用。
- Farmer 的鎖定檔需審查，且沒有 lint 設定。
- 兩個 App 都有 lucide 與 React 19 的 peer 衝突。

## 7. Step 6 是否可以開始

**可以開始離線封裝（Step 6）**，條件如下：
- 封裝時必須處理 OPEN 項目 6–8：服務埠布局、啟動／停止腳本、Farmer 鎖定檔與 lint。
- 必須以 `requirements_rpi.txt` 的釘選版本封裝。
- 在 BLOCKER 1–4 解決之前，**不得部署或正式使用**：憑證更換、模型核准、AIR 期限與實機校正、硬體驗證。

## 偏離紀錄

- 用 VS Code 的 Electron 當作 Node 執行；npm 為可攜版。
- 安裝依賴時使用 `--legacy-peer-deps`。
- ESLint 與打包在 ASCII 鏡像中執行（逐檔雜湊驗證）。
- 釘選版本環境使用 Anaconda 的 Python 3.12.7 建立 venv（本機 Python 3.10 無法安裝釘選版本）。
- Farmer 的鎖定檔是在測試時產生的。
- 依賴下載時連線到 npm registry 與 PyPI；所有測試本身都在本機、不連網（Python 測試的 socket 已攔截，App 測試只用 127.0.0.1）。
