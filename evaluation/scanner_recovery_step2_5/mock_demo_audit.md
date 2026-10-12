# Mock／Demo 稽核（Phase E）

依規定**未修改任何 App UI 或程式**，以下只列出發現與建議。路徑相對於 `Semester 2 Final Exam (三下-期末)/app/`。

| # | 位置 | 行為 | 是否會被觸發 | 風險 |
|---|---|---|---|---|
| 1 | `Farmer_pineapple-ripeness-main/screens/BatchScanScreen.tsx` 第 23–32 行 | 成熟度、糖度、黑心風險、異常旗標、信心值**全部用 `Math.random()` 產生** | **每次都會**（這個畫面沒有呼叫任何後端） | **高**：展示時若操作 Farmer 批次掃描，看到的是亂數，卻呈現成像真實結果 |
| 2 | `Farmer_pineapple-ripeness-main/services/api.ts` 第 37–42、96–105 行 | `startScan` 呼叫 `/scan/start`（後端沒有這個端點），失敗時回傳亂數 mock | 目前沒有任何畫面呼叫它 | 中：之後若有人接上，會在後端失敗時默默顯示亂數 |
| 3 | `Consumer_pineapple-ripeness-main/expo/services/api.ts` 第 369–420 行 | `apiFetchRipenessMock` 在後端無法連線時回傳 `buildOfflineMock()`（隨機階段） | 只被 import，沒有被呼叫 | 中：同上 |
| 4 | `Consumer_pineapple-ripeness-main/expo/utils/ripeness.ts` 第 73–75 行 | `generateMockSensorData` 產生隨機感測值 | 沒有呼叫者 | 低 |
| 5 | Consumer 主流程 `contexts/SensorContext.tsx` | `startScan` → `POST /scan` → 輪詢 `/status`（Gateway v2），錯誤時拋出 `SCAN_TIMEOUT` 等錯誤 | 是 | 無 mock fallback，**正確** |
| 6 | Web CLI `--demo` | 從本機 xlsx 讀取過去的實驗資料，不是即時感測 | 網頁 `/demo_*` 路由 | 中：需在 UI 上明確標示為「重播資料」 |

## 建議（未實作）

1. 移除 Farmer BatchScanScreen 的亂數結果，或在畫面上清楚標示「DEMO／模擬資料」。
2. 正式版關閉所有 random fallback：後端失敗時顯示錯誤，不要顯示假結果。
3. Web 的 demo 路由在結果頁標示「重播歷史資料」，並顯示 demo case 編號。
4. 結果頁顯示模型 SHA 前綴與 AIR `calibration_id`／時間，方便現場追溯。
