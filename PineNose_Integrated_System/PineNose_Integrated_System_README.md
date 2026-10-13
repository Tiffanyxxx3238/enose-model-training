# PineNose｜鳳梨智慧辨識整合系統

> Raspberry Pi 整合網頁、氣味成熟度辨識、照片品種辨識與本機歷史紀錄管理

這個資料夾整理 PineNose 專題於 Raspberry Pi 3 上實際使用的整合系統版本，包含網頁介面、照片辨識 Gateway、歷史紀錄管理，以及一鍵啟動／停止腳本。相關程式是依照目前已完成的專題功能整合與測試，並非獨立重新開發的另一套模型。

目前的整合入口由 Raspberry Pi 提供，讓使用者從同一個網頁切換氣味成熟度辨識、照片品種辨識與歷史紀錄。成熟度模型沿用本 Repository 的 `raspberrypi3/` 正式版本；照片模型則由 Windows 電腦提供推論服務。

## 1. 系統功能

| 模組 | 主要功能 | 執行位置 | Port |
|---|---|---|---|
| 氣味成熟度辨識 | 感測資料蒐集、空氣校正、30 秒視窗推論、成熟度結果顯示 | Raspberry Pi 3 | `5051` |
| 照片品種辨識 | 上傳鳳梨照片、轉送模型推論、顯示辨識結果 | Raspberry Pi 3（Gateway）＋ Windows（模型） | `5002`／`5001` |
| 整合網頁 | 集中顯示成熟度、照片辨識與歷史紀錄入口 | Raspberry Pi 3 | `8000` |
| 歷史紀錄管理 | 儲存成熟度結果、分類管理、搬移、刪除與報告下載 | Raspberry Pi 3 本機 JSON | 與整合網頁共用 `8000` |

成熟度目前分為四個階段：**未熟、初熟、成熟、過熟**。照片辨識由 Windows 模型伺服器處理，使用 YOLOv8n 與 EfficientNet-B0 的既有模型流程。

## 2. 系統架構

```text
使用者瀏覽器
    │
    ▼
Raspberry Pi 3｜整合網頁 :8000
    ├── 氣味成熟度辨識 :5051
    │       ├── Arduino Mega 2560＋氣體／環境感測器
    │       ├── 空氣校正、30 秒感測視窗
    │       └── ExtraTrees 成熟度分類
    │
    ├── 照片品種辨識 Gateway :5002
    │       ├── 接收並暫存使用者上傳的照片
    │       └── HTTP POST → Windows 模型服務 :5001/predict
    │                          └── YOLOv8n＋EfficientNet-B0
    │
    └── 歷史紀錄 :8000/history
            └── Raspberry Pi 本機 data/history.json
```

**注意：** 這裡的歷史紀錄是整合網頁專用的本機 JSON 儲存，不會直接寫入學校 VM Docker 內農民端／消費端 App 使用的歷史資料庫，兩者是不同的系統。

## 3. Repository 內的檔案

```text
PineNose_Integrated_System/
├── .gitignore
├── pineapple_app_gateway/
│   └── app_gateway.py                 # 照片上傳、推論轉送與辨識網頁
├── pineapple_unified_web/
│   ├── app.py                         # 整合網頁 Flask 程式及歷史紀錄 API
│   ├── README_history.md              # 歷史紀錄功能的詳細操作說明
│   ├── templates/
│   │   ├── index.html                 # 整合首頁
│   │   └── history.html               # 歷史紀錄介面
│   └── static/
│       └── style.css                  # 網頁樣式
├── start_pineapple_system.sh          # 啟動 Raspberry Pi 三個服務
└── stop_pineapple_system.sh           # 停止 Raspberry Pi 三個服務
```

成熟度辨識的正式程式與模型沒有在此重複存放，請參考 Repository 根目錄的 [`raspberrypi3/`](../raspberrypi3/)：`app_local.py`、`calibrate_air_30s.py`、`inference_30s.py`、`deploy_student.pkl`、`feature_columns.json` 和 `deploy_meta.json` 等檔案。

這裡的 `pineapple_app_gateway/app_gateway.py` 是**照片品種辨識 Gateway**，與 Repository 原有的 [`pineapple_app_gateway/app_gateway_v2.py`](../pineapple_app_gateway/app_gateway_v2.py)（氣味感測相關 API）用途不同，請勿直接互相覆蓋。

## 4. 實際部署位置

目前 Raspberry Pi 實際運作時使用以下路徑，而不是直接從本 GitHub 資料夾執行：

```text
/home/linguanyu/
├── pineapple/                        # 正式成熟度辨識程式與模型
│   └── app_local.py
├── pineapple_app_gateway/            # 正式照片辨識 Gateway
│   ├── app_gateway.py
│   └── uploads/                       # 執行期間的上傳照片
├── pineapple_unified_web/            # 正式整合網頁
│   ├── app.py
│   ├── templates/
│   ├── static/
│   └── data/
│       └── history.json              # 執行時產生的歷史資料
├── start_pineapple_system.sh
└── stop_pineapple_system.sh
```

本資料夾保存已驗證版本的**程式碼與部署腳本**。若要在另一台 Raspberry Pi 還原，需先將相關檔案部署到上列預期路徑，安裝必要套件、準備成熟度模型及感測器連線，再調整目前網路環境中的 IP 設定。**只下載本資料夾並直接執行 `.sh`，不代表能自動完成全新環境部署。**

## 5. 網路與服務設定

以下是 2026 年 10 月整合測試時的區域網路配置，**不是固定不變的公開網址**。

| 服務 | 測試環境網址 |
|---|---|
| 整合網頁 | `http://172.20.10.3:8000` |
| 成熟度辨識 | `http://172.20.10.3:5051` |
| 照片辨識 Gateway | `http://172.20.10.3:5002` |
| Windows 照片模型服務 | `http://172.20.10.10:5001` |

IP 設定目前寫在既有程式內，網路環境變動時需檢查：

- `pineapple_unified_web/app.py`：`SMELL_PAGE_URL`、`PHOTO_PAGE_URL`。
- `pineapple_app_gateway/app_gateway.py`：`MODEL_SERVER_URL`，需指向 Windows 的 `/predict` API。
- `start_pineapple_system.sh`：末尾顯示的網址僅供操作提示。

測試中曾發生 Windows 同時存在乙太網路與 Wi-Fi 路由時，瀏覽器上傳照片會出現 `ERR_CONNECTION_RESET`；指定 Wi-Fi 來源 IP 的 POST 測試則正常回傳 HTTP 200。若再次遇到此狀況，應優先檢查網卡與路由，而不是立即修改照片辨識模型。

## 6. 啟動與停止

### Raspberry Pi 端

確認三個正式程式資料夾及各自的 Python 環境已準備完成後，從 Raspberry Pi 的家目錄執行：

```bash
~/start_pineapple_system.sh
```

此腳本會分別檢查 `5051`、`5002`、`8000` 是否已有服務監聽。若 Port 已被占用，腳本會跳過該服務；這只是 Port 檢查，並不保證占用者一定是正確的 PineNose 程式。

檢查 Port：

```bash
ss -ltn | grep -E ':(5002|5051|8000)\b'
```

關閉 Raspberry Pi 三個服務：

```bash
~/stop_pineapple_system.sh
```

停止腳本會嘗試比對監聽程序的執行路徑與模組名稱，再傳送 `SIGTERM`，避免使用廣泛的 `pkill -f app.py`。停止腳本**不會刪除模型、照片或歷史紀錄**。

啟動日誌位置：

```text
~/pineapple_logs/ripeness.log
~/pineapple_logs/photo_gateway.log
~/pineapple_logs/unified_web.log
```

### Windows 照片模型端

照片 Gateway 不在 Raspberry Pi 上直接執行 YOLO／EfficientNet 推論，而是將照片送到 Windows 模型服務。測試環境以既有 `pineapple_detection/server_variety.py` 啟動：

```powershell
cd "C:\Users\user\Desktop\pineapple_detection"
python server_variety.py
```

模型服務需能接受 `POST /predict`，並可由 Raspberry Pi 透過 `MODEL_SERVER_URL` 連線。**Windows 模型服務不會被 Raspberry Pi 的兩個 `.sh` 自動啟動或停止。** 本 GitHub 子資料夾也沒有包含 Windows 模型權重及 Windows 專案完整程式。

## 7. 使用方式

開啟整合網頁 `http://172.20.10.3:8000`（依實際 Raspberry Pi IP 調整），即可在同一個入口操作各模組。

**氣味成熟度辨識：** 透過既有 Arduino／感測器資料蒐集流程進行空氣校正及成熟度推論；完成有效辨識後，可使用成熟度頁面的「儲存歷史紀錄」功能。

**照片品種辨識：** 在照片辨識頁上傳圖片並按「開始辨識」，Gateway 會先儲存上傳檔，再向 Windows 模型服務提出推論請求，最後將結果顯示在網頁上。

**歷史紀錄：** 可依資料夾管理已儲存的成熟度結果，包括新增資料夾、查看紀錄、搬移、刪除、清空資料夾及下載報告。歷史紀錄預設保留 **30 天**；到期紀錄會在讀取歷史資料時清理。下載支援單筆 HTML 報告，以及多筆／資料夾的 ZIP（含 CSV 摘要與 HTML 報告）。

## 8. 主要 API

| 服務 | 路徑與方法 | 用途 |
|---|---|---|
| Gateway | `GET /` | 照片辨識網頁 |
| Gateway | `GET /api/status` | Gateway 服務狀態 |
| Gateway | `POST /web/predict` | 網頁照片辨識 |
| Gateway | `POST /variety/predict` | 回傳 JSON 的照片辨識 API |
| 整合網頁 | `GET /` | 整合首頁 |
| 整合網頁 | `GET /history` | 歷史紀錄頁 |
| 整合網頁 | `GET /api/history` | 取得歷史紀錄與資料夾 |
| 整合網頁 | `POST /api/history/save` | 儲存成熟度結果 |
| 整合網頁 | `POST /api/history/folders` | 新增資料夾 |
| 整合網頁 | `POST /api/history/move` | 搬移紀錄 |
| 整合網頁 | `POST /api/history/delete` | 刪除選取紀錄 |
| 整合網頁 | `POST /api/history/folders/clear` | 清空指定資料夾 |
| 整合網頁 | `POST /api/history/folders/delete` | 刪除資料夾及其紀錄 |
| 整合網頁 | `POST /api/history/download_report` | 匯出 HTML／ZIP 報告 |

既有程式亦保留 `POST /api/history/download`（JSON／ZIP 資料匯出）；目前網頁報告下載主要使用 `/api/history/download_report`。更詳細的操作方式請參考 [`README_history.md`](pineapple_unified_web/README_history.md)。

## 9. 歷史資料與版本管理

歷史紀錄儲存在 Raspberry Pi：

```text
~/pineapple_unified_web/data/history.json
```

這是**檔案式 JSON 儲存**，不是 MySQL、PostgreSQL 或 SQLite。第一次使用且檔案不存在時，整合網頁會建立包含預設資料夾與空白紀錄的檔案。儲存結果包含成熟度、信心分數、機率、特徵、原始輸出及備註等資訊。

本資料夾的 `.gitignore` 排除 `data/`、`uploads/`、虛擬環境、日誌與敏感設定檔；GitHub 上保留的是程式與介面，而不是實際使用者照片或歷史紀錄。若需備份資料，可另外在 Raspberry Pi 本機複製 `history.json` 並妥善保存。

## 10. 注意事項

- 目前程式中的測試 IP 為特定區域網路配置；換網路或設備時需要重新確認 IP、Port 與連通性。
- Raspberry Pi 3 的成熟度服務需要既有感測器、Arduino、模型及 Python 環境；單靠整合網頁無法完成氣味推論。
- Windows 照片模型需先啟動，否則 Gateway 雖然可以開啟，照片推論仍會失敗。
- `.sh` 僅管理 Raspberry Pi 的三個 Flask 服務，不會自動控制 Windows 模型，也不會管理學校 VM Docker 資料庫。
- 目前三個服務使用 Flask 內建伺服器，適合本機展示與受控的開發測試環境；請勿直接當作已完成安全性強化的公開網路部署。
- 後續修改應以實際運行版本為準，先備份、測試，再同步更新到 GitHub。

---

**專題：** PineNose 鳳梨電子鼻非破壞性熟度檢測系統  
**本目錄內容：** Raspberry Pi 整合網頁、照片辨識串接及歷史紀錄管理  
**版本紀錄：** 2026 年 10 月，Raspberry Pi 整合測試版本
