# PineNose — Raspberry Pi 3 鳳梨熟度辨識系統

**Raspberry Pi 3 Deployment | Electronic Nose | ExtraTrees | 30-Second Inference**

本資料夾保存 PineNose 鳳梨電子鼻非破壞性熟度檢測系統的 Raspberry Pi 3 部署版本，包含 Arduino 感測資料接收、空氣基準校正、30 秒熟度推論、Flask 網頁操作介面，以及歷史 Excel 資料模擬測試功能。

本版本以 2026 年 10 月 13 日完成修正與驗證的程式為基礎，主要針對實際量測流程、資料收集完整性、AIR baseline 管理及模型推論進行整理。

**對應 Git Commit：** `781ce66`  
**部署平台：** Raspberry Pi 3  
**主要模型：** ExtraTreesClassifier  
**模型輸入：** 11 個特徵  
**推論窗口：** 30 筆有效感測資料  
**分類結果：** 未熟、初熟、成熟、過熟

---

## 1. 專案介紹

PineNose 以電子鼻感測技術搭配機器學習模型，透過鳳梨釋放的揮發性氣體訊號進行熟度辨識，希望提供一種不需要切開果實的輔助判斷方式。

系統由 Arduino Mega 2560 負責感測資料擷取，Raspberry Pi 3 負責接收序列資料、執行空氣校正與特徵計算，再透過已訓練的 ExtraTrees 模型輸出熟度分類結果。

使用者可以透過 Flask 網頁執行即時量測，也可以使用專案提供的歷史 Excel 資料進行 Demo 測試。

### 主要功能

- **即時熟度辨識：** 從 Arduino 接收感測資料，收集完整 30 筆有效資料後執行推論。
- **空氣基準校正：** 量測沒有鳳梨樣本時的環境訊號，建立 AIR baseline。
- **三種量測模式：** 快速、標準、完整檢測，分別提供不同的前置氣味累積時間。
- **四階段熟度分類：** 未熟、初熟、成熟、過熟。
- **Demo 模擬測試：** 讀取歷史 Excel 資料，不需要連接 Arduino 即可執行測試。
- **網頁操作介面：** 整合校正、推論、機率與感測數據顯示。
- **異常處理：** 資料不足、序列埠連線失敗或缺少 AIR baseline 時，提供錯誤訊息並停止不完整的推論。

---

## 2. 系統架構

### 硬體組成

| 設備 | 用途 |
|---|---|
| Raspberry Pi 3 | 執行 Python、Flask 與機器學習模型 |
| Arduino Mega 2560 | 擷取並傳送感測器資料 |
| MQ-2 | 氣體感測 |
| MQ-3 | 氣體感測 |
| MQ-9 | 氣體感測 |
| MQ-135 | 氣體感測 |
| TGS2602 | 氣體感測 |
| BME280 | 環境溫度、濕度與氣壓資料 |

目前正式推論使用 MQ-2、MQ-3、MQ-9、MQ-135、TGS2602 五組感測器的原始數值進行特徵計算。其他環境欄位可作為量測紀錄或輔助資訊，但不屬於這個部署模型的 11 個輸入特徵。

### 資料處理流程

```text
Arduino Mega 2560
       |
       | USB Serial / 115200 baud
       v
Raspberry Pi 3
       |
       +-- AIR 空氣校正
       |      |
       |      +-- air_base.json
       |
       +-- 鳳梨量測
              |
              +-- 前置氣味累積（依模式選擇）
              |
              +-- 收集 30 筆有效感測資料
              |
              +-- AIR baseline 正規化
              |
              +-- 計算 11 個模型特徵
              |
              +-- ExtraTreesClassifier
              |
              +-- 四階段熟度分類
              |
              +-- Flask 網頁顯示結果
```

---

## 3. 專案檔案結構

```text
raspberrypi3/
├── app_local.py
├── calibrate_air_30s.py
├── inference_30s.py
├── deploy_student.pkl
├── deploy_meta.json
├── feature_columns.json
├── requirements.txt
├── requirements_rpi.txt
├── Dockerfile
├── docker-compose.yml
├── .gitignore
└── demo_data/
    └── pineapple_*.xlsx
```

### 主要檔案說明

| 檔案 | 功能 |
|---|---|
| `app_local.py` | Flask 網頁介面與本機程式整合 |
| `calibrate_air_30s.py` | 30 筆有效資料的 AIR 空氣校正 |
| `inference_30s.py` | 感測資料收集、特徵計算及模型推論 |
| `deploy_student.pkl` | 已訓練的 ExtraTrees 模型 |
| `feature_columns.json` | 模型輸入特徵與排列順序 |
| `deploy_meta.json` | 模型版本及部署資訊 |
| `requirements_rpi.txt` | Raspberry Pi 推論環境使用的套件版本 |
| `requirements.txt` | 原有部署相依套件清單 |
| `demo_data/` | 歷史 AIR 與鳳梨感測 Excel 資料 |
| `Dockerfile` | 既有 Docker 映像設定 |
| `docker-compose.yml` | 既有 Docker Compose 設定 |

本儲存庫沒有包含 Python 虛擬環境、實際執行時產生的 AIR baseline，以及個別設備的本機設定資料。

---

## 4. 開發與執行環境

### 軟體技術

- Python
- Flask
- NumPy
- Pandas
- Scikit-learn
- PySerial
- ExtraTreesClassifier
- Docker（保留既有部署設定）

### Raspberry Pi Python 套件

`requirements_rpi.txt` 記錄目前部署版本的主要推論套件：

```text
joblib==1.5.3
numpy==2.4.3
pandas==3.0.1
pyserial==3.5
python-dateutil==2.9.0.post0
scikit-learn==1.8.0
scipy==1.17.1
six==1.17.0
threadpoolctl==3.6.0
```

Flask 網頁另外需要 Flask 套件，Demo Excel 讀取也需要相容的 Excel 讀取套件，例如 `openpyxl`。

**環境注意事項：** 上述套件版本是目前儲存庫的記錄，並不代表已在所有 Raspberry Pi OS 或 Python 版本上重新安裝測試。部署前應先確認作業系統、Python 版本及套件相容性。

---

## 5. Raspberry Pi 部署方式

### 5.1 取得專案

```bash
git clone https://github.com/Tiffanyxxx3238/enose-model-training.git
cd enose-model-training/raspberrypi3
```

### 5.2 建立 Python 虛擬環境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安裝依賴套件前，應確認目前 Raspberry Pi OS 的 Python 版本可以支援相應套件。

### 5.3 安裝套件

```bash
python -m pip install -r requirements_rpi.txt
python -m pip install flask openpyxl
```

如環境需要其他相依套件，應依實際錯誤訊息確認，避免直接覆蓋既有正式環境。

### 5.4 確認 Arduino 連線

將 Arduino Mega 2560 透過 USB 連接 Raspberry Pi。

```bash
ls /dev/ttyACM*
```

常見序列埠：

```text
/dev/ttyACM0
```

程式會自動尋找 `/dev/ttyACM*` 或 `/dev/ttyUSB*` 裝置，也可以在命令列手動指定序列埠。

目前程式使用的 Baud Rate 為 **115200**。

若找不到序列埠，應先確認 USB 線材、Arduino 供電、系統裝置權限，以及 Arduino 是否持續輸出預期的 CSV 資料格式。

---

## 6. AIR 空氣基準校正

正式量測前，需要先建立環境空氣的基準值。

AIR baseline 用來提供各感測器的參考數值，讓後續鳳梨量測資料可以依相同基準進行正規化。

### 6.1 實際校正流程

1. 確認感測裝置正常運作。
2. 將鳳梨樣本移出量測空間。
3. 確認 Arduino 已連接 Raspberry Pi。
4. 執行 AIR 校正。
5. 等待系統收集 30 筆有效資料。
6. 成功後產生 `air_base.json`。

執行指令：

```bash
python calibrate_air_30s.py
```

手動指定序列埠：

```bash
python calibrate_air_30s.py --port /dev/ttyACM0
```

### 6.2 校正資料完整性

正式 AIR 校正要求收集 **30 筆有效資料**。

若在指定等待時間內無法取得完整資料，程式會停止校正，不會使用不足的資料覆蓋正式 AIR baseline。

當新的正式 baseline 成功寫入時，程式具有保留既有校正資料備份的機制。

### 6.3 AIR 檔案管理

| 檔案 | 用途 |
|---|---|
| `air_base.json` | 正式量測使用的 AIR baseline |
| `air_base_demo.json` | Demo 模式使用的 AIR baseline |
| `air_history/` | AIR 歷史備份資料夾 |

AIR 校正資料與量測環境有關，因此沒有將執行時產生的正式 baseline 直接提交至 GitHub。

**注意：** 正式量測與 Demo 校正應使用各自的 AIR 檔案，避免歷史測試資料覆蓋實際環境的校正結果。

---

## 7. 鳳梨熟度即時推論

正式推論由 `inference_30s.py` 負責執行。

### 7.1 三種量測模式

| 模式 | 前置累積時間 | 正式資料收集 | 理論總時間 |
|---|---:|---:|---:|
| 快速檢測 | 0 秒 | 約 30 秒 | 約 30 秒 |
| 標準檢測 | 60 秒 | 約 30 秒 | 約 90 秒 |
| 完整檢測 | 180 秒 | 約 30 秒 | 約 210 秒 |

上述時間為量測流程的設定值，實際執行時間還會受到序列埠初始化、資料輸出頻率與系統處理時間影響。

### 7.2 快速檢測

```bash
python inference_30s.py --warmup-sec 0
```

### 7.3 標準檢測

```bash
python inference_30s.py --warmup-sec 60
```

### 7.4 完整檢測

```bash
python inference_30s.py --warmup-sec 180
```

### 7.5 資料完整性檢查

正式推論必須取得完整 30 筆有效感測資料。

若資料不足，系統會顯示錯誤並停止推論，不會將不完整的量測資料送入模型。

這項設計是為了避免序列埠中斷、資料格式錯誤或感測器輸出異常時，仍產生看似正常的分類結果。

---

## 8. ExtraTrees 熟度分類模型

### 8.1 模型資訊

| 項目 | 設定 |
|---|---|
| 模型類型 | ExtraTreesClassifier |
| 模型檔案 | `deploy_student.pkl` |
| 特徵數量 | 11 |
| 資料窗口 | 30 筆 |
| 分類數量 | 4 |
| 是否使用日期特徵 | 否 |
| 預設後處理 | `raw` |

模型輸入使用固定順序的 11 個特徵，順序由 `feature_columns.json` 決定。

### 8.2 模型輸入特徵

| 編號 | 特徵名稱 |
|---|---|
| 1 | `MQ3_std_norm` |
| 2 | `MQ3_range_norm` |
| 3 | `MQ2_MQ3_ratio` |
| 4 | `MQ3_MQ135_ratio` |
| 5 | `MQ9_slope` |
| 6 | `TGS2602_min_norm` |
| 7 | `MQ2_auc_norm` |
| 8 | `MQ2_mean_norm` |
| 9 | `MQ9_min_norm` |
| 10 | `TGS2602_std_norm` |
| 11 | `MQ9_delta_mean` |

特徵包含感測訊號的統計量、變化趨勢、感測器間比例，以及相對 AIR baseline 的正規化數值。

本部署模型不使用 `day_ratio` 與 `day_index`，避免推論時依賴額外的日期資訊。

### 8.3 熟度分類

| Stage | 分類 |
|---|---|
| 0 | 未熟 |
| 1 | 初熟 |
| 2 | 成熟 |
| 3 | 過熟 |

程式會輸出模型分類結果與各類別機率。

目前預設使用 `--postprocess raw`，以模型原始分類作為主要結果；`legacy` 選項保留舊版規則，供比較與測試使用。

### 8.4 無有效鳳梨訊號檢查

推論程式包含空氣／無樣本訊號檢查機制。

當資料符合相關防呆條件時，介面會提示「無有效鳳梨訊號」，避免直接將該筆資料視為正常的鳳梨熟度判定。

此機制屬於輔助判斷規則，不能視為已經完全解決所有空樣本或環境干擾問題。

---

## 9. Flask 網頁操作介面

`app_local.py` 提供 Raspberry Pi 本機網頁操作功能。

目前版本直接在 Raspberry Pi 上透過 Python subprocess 執行校正與推論程式，不需要再透過 SSH 連回同一台設備。

### 9.1 啟動網頁

在專案資料夾執行：

```bash
python app_local.py
```

程式預設使用：

```text
http://<Raspberry-Pi-IP>:5050
```

其中 `<Raspberry-Pi-IP>` 應替換為 Raspberry Pi 在區域網路中的實際 IP 位址。

### 9.2 網頁功能

| 功能 | 說明 |
|---|---|
| 空氣校正 | 建立正式 AIR baseline |
| 快速檢測 | 直接收集 30 筆有效資料 |
| 標準檢測 | 前置累積 60 秒後推論 |
| 完整檢測 | 前置累積 180 秒後推論 |
| Demo 空氣校正 | 由歷史 Excel 建立 Demo baseline |
| Demo 鳳梨推論 | 由歷史 Excel 執行模型測試 |
| 推論結果顯示 | 呈現熟度、分類機率與感測數據 |

### 9.3 正式部署 Port 說明

本次驗證環境中，正式版 Flask 另外使用 **Port 5051** 啟動，與測試環境的 Port 5050 分開。

但 `app_local.py` 直接執行時，預設仍為 Port 5050。

因此，Port 5051 是本次正式環境的啟動設定，不是程式檔案中的預設值。

---

## 10. Demo 模式

為了在沒有實際鳳梨或 Arduino 裝置的情況下展示系統，專案提供歷史 Excel 資料模擬功能。

### 10.1 Demo 資料

`demo_data/` 包含 20 個 Excel 檔案，分為：

- 10 個 AIR 空氣資料檔。
- 10 個鳳梨量測資料檔。

資料涵蓋未熟、初熟、成熟與過熟四種標籤。

### 10.2 Demo AIR 校正

例如：

```bash
python calibrate_air_30s.py \
  --demo \
  --demo-case pineapple_03_20260214
```

預設產生：

```text
air_base_demo.json
```

不會覆蓋正式量測使用的 `air_base.json`。

### 10.3 Demo 鳳梨推論

例如：

```bash
python inference_30s.py \
  --demo \
  --demo-case pineapple_03_20260214 \
  --demo-stage 過熟 \
  --air air_base_demo.json
```

Demo 模式會從對應 Excel 檔案讀取感測資料，不需要 Arduino 即時傳輸。

也可以直接透過 Flask 網頁選擇歷史資料執行 Demo 校正與推論。

**注意：** Demo Excel 中的熟度標籤代表歷史資料標記，不代表模型一定會輸出相同分類。模型預測仍應依實際執行結果判斷。

---

## 11. Docker 部署設定

本資料夾保留原有 `Dockerfile` 與 `docker-compose.yml`，作為既有容器部署設定的紀錄。

目前 Docker Compose 設定包含：

- Python 3.10 基礎映像。
- 容器名稱 `pineapple-maturity`。
- Port `5000:5000`。
- Arduino 裝置 `/dev/ttyACM0`。
- `SERIAL_PORT` 環境變數。
- `privileged: true` 設定。

**重要：** 這些設定是原有部署檔案，尚未針對 2026 年 10 月 13 日的最新 Raspberry Pi 正式版重新完成 Docker 驗證。

此外，目前 Flask 程式預設 Port 為 5050，與 Docker 原有 Port 5000 不一致。正式使用 Docker 前，應先確認服務監聽 Port、容器權限及裝置映射是否正確。

不建議直接將這份 Docker 設定視為已驗證完成的正式部署方案。

---

## 12. 本次版本修正與驗證

### 2026-10-13｜Raspberry Pi 3 正式版整理

本次主要針對 Raspberry Pi 實際部署時的資料收集、AIR 校正、模型推論及 Flask 整合進行修正與驗證。

| 項目 | 修正與確認內容 |
|---|---|
| AIR 校正 | 必須取得完整 30 筆有效資料 |
| 推論資料收集 | 必須取得完整 30 筆有效資料 |
| 資料不足處理 | 不進行不完整推論 |
| 前置累積 | 支援 0、60、180 秒模式 |
| Flask 整合 | 改為 Raspberry Pi 本機 subprocess 執行 |
| 模型載入 | 使用正式 ExtraTrees 模型 |
| Demo 模式 | 與正式 AIR 校正資料分離 |
| GitHub 保存 | 正式程式、模型及 Demo 資料完成提交 |

### 本次驗證範圍

已完成 Python 語法檢查、正式模型檔案一致性檢查、GitHub 同步檢查，以及本次實際 Arduino 量測流程驗證。

本次實測包含 10 次量測，每次收集完整 30 筆有效資料，其中 8 次輸出「成熟」分類。

這個結果僅代表當次量測的分類分布，**不能直接解讀為 80% 的模型準確率**。模型準確率仍需要具有獨立真實熟度標籤的測試資料進行評估。

### GitHub 版本紀錄

```text
Commit: 781ce66
Branch: main

Add Raspberry Pi 3 production deployment
and validated 30s inference
```

---

## 13. 常見問題與排除方式

### 找不到 Arduino 序列埠

請先確認 USB 連線：

```bash
ls /dev/ttyACM*
ls /dev/ttyUSB*
```

若沒有找到裝置，檢查 Arduino 電源、USB 傳輸線及 Raspberry Pi 的裝置權限。

### AIR baseline 不存在

若正式推論顯示找不到 `air_base.json`，請先執行：

```bash
python calibrate_air_30s.py
```

完成正式空氣校正後再進行鳳梨量測。

### 收集不到完整 30 筆資料

可能原因包括 Arduino 資料輸出中斷、序列資料格式不正確、裝置連線不穩定，或等待時間內沒有足夠有效資料。

目前程式會停止推論，而不是直接使用不足的資料。

### Demo 模式找不到 Excel

確認 `demo_data/` 資料夾位於專案目錄下，且檔名符合程式預期的格式。

### 網頁無法開啟

先確認 Flask 是否已啟動，再確認 Raspberry Pi IP、Port 與網路連線。

直接執行 `app_local.py` 的預設 Port 為 5050；若使用其他 Port 啟動，應以實際設定為準。

### Python 套件或模型載入失敗

確認目前使用的是相容的 Python 環境，以及模型與 Scikit-learn 版本是否相容。

`deploy_student.pkl` 為 Python 序列化模型檔案，應只從可信任的來源載入。

---

## 14. 已知限制與後續工作

目前版本已能執行完整的 Raspberry Pi 端量測與推論流程，但仍有以下項目可持續改善：

1. **跨批次與跨環境驗證：** 增加不同鳳梨、不同量測日期與環境條件下的獨立測試。
2. **模型準確率評估：** 使用具備可靠真實標籤的資料建立混淆矩陣、各類別 Recall、Precision 與整體 Accuracy。
3. **環境漂移問題：** 持續評估 AIR baseline 與溫濕度變化對推論結果的影響。
4. **Docker 設定更新：** 統一容器與 Flask Port，重新驗證容器部署。
5. **部署自動化：** 後續可增加服務自動啟動與系統日誌管理。
6. **測試紀錄整理：** 將獨立測試結果與版本更新紀錄持續保存，方便後續比較。

---

## 15. 資料與版本管理說明

本資料夾主要保存可以重現 Raspberry Pi 端推論流程的程式、模型與 Demo 資料。

以下內容不包含在 GitHub 中：

- Python 虛擬環境。
- 執行期間產生的正式 AIR baseline。
- AIR 歷史備份。
- 本機日誌與暫存檔。
- 私人憑證及環境設定。
- 尚未整理進儲存庫的個別實驗測試報告。

若需要完整重建原始實驗環境，仍應搭配硬體接線資訊、Arduino 韌體、相容的 Python 執行環境及原始量測資料。

---

## 16. 專案資訊

**專案名稱：** PineNose — 鳳梨電子鼻非破壞性熟度檢測系統  
**團隊：** PineNose Team  
**學校：** 長庚大學  
**研究與實作領域：** Embedded Systems、Electronic Nose、Machine Learning、Edge AI、Web Integration

**GitHub Repository：**  
https://github.com/Tiffanyxxx3238/enose-model-training

**Raspberry Pi 3 Deployment：**  
https://github.com/Tiffanyxxx3238/enose-model-training/tree/main/raspberrypi3

---

*本 README 依據 Raspberry Pi 3 正式版 Commit `781ce66` 整理。程式功能、測試結果與尚未驗證的部署項目分別說明，以保留實際開發及驗證紀錄。*
