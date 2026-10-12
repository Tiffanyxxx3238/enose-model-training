# 鳳梨電子鼻模型訓練

此資料夾包含本專題「電子鼻鳳梨成熟度檢測系統」的模型訓練流程。

整個訓練流程會從重新整理後的原始感測特徵開始，結合人工標註與複查後的標籤，進行特徵工程、模型評估，最後匯出可部署到 Raspberry Pi 的模型與相關檔案。

---

## 概述

此目錄主要用於本專題的**模型訓練與部署前準備階段**。

主要用途包含：

- 從原始 Excel 檔重新建立每日特徵表
- 合併鳳梨資料與每日空氣基準資料
- 載入並修正標註資料
- 整合人工複查後的標籤
- 產生工程化特徵
- 評估多種訓練策略
- 比較 CatBoost teacher model 與 student deploy model
- 匯出 Raspberry Pi 可使用的最終部署模型包

目前此資料夾主要使用的 Notebook 為：

- `labeling_perfect_final.ipynb`

這份 Notebook 是目前模型訓練流程的最新整合版本。

---

## 目前資料夾結構

```text
enose_model_training/
└── orkspace/
    ├── catboost_info/
    ├── data/
    ├── deploy_rpi_catboost/
    ├── deploy_rpi_et_10s/
    ├── deploy_rpi_et_10s_noday/
    ├── deploy_rpi_et_30s_noday/
    ├── deploy_rpi_et_30s_noday_s3_sensitive/
    ├── deploy_rpi_student/
    ├── deploy_rpi_student_short/
    ├── models/
    ├── reports/
    ├── cutpoints.json
    ├── data_label_audit_report.xlsx
    ├── feature_columns.json
    ├── labeling_perfect_final.ipynb
    ├── labeling.xlsx
    ├── model_final.pkl
    └── stage_timeline.png
```

> 注意：`orkspace` 是目前此專案結構中的實際資料夾名稱。

---

## 主要 Notebook

### `labeling_perfect_final.ipynb`

這是目前版本中鳳梨電子鼻模型訓練流程的主要 Notebook。

此 Notebook 包含以下主要工作：

### 1. 從原始 Excel 檔重新建立特徵

此 Notebook 會從所有原始 Excel 檔重新建立每日特徵資料，包含：

- 鳳梨樣本檔案
- 個別空氣檔案
- 共用空氣檔案

此步驟取代舊版較分散的前處理流程，並建立較乾淨的特徵表，方便後續模型訓練使用。

### 2. 交叉特徵與空氣對照特徵

此流程會額外建立工程化特徵，包含：

- 感測器之間的比例特徵
- 鳳梨與空氣之間的差異特徵
- 以每日空氣基準為基礎的比較特徵

這些特徵可以幫助模型更好地捕捉鳳梨樣本與背景空氣之間的氣味模式差異。

### 3. 標籤載入與修正

Notebook 會載入 `labeling.xlsx`，並根據稽核結果修正標籤。

重點如下：

- 保留原本四階段設定：`0 / 1 / 2 / 3`
- 保留 Stage 3，不將其合併或刪除
- 套用人工複查後的標籤修正
- 檢查 Stage 3 合併與覆蓋情況
- 產生稽核與複查輔助表格

### 4. 混合式標籤傳播與偽標籤

針對部分尚未完整標註的資料，Notebook 使用混合式策略，結合：

- 人工標籤
- anchor-based propagation
- 成熟度代理特徵
- 氣味相似度
- 成熟階段的單調性限制

此方法可以擴充訓練資料，同時維持成熟階段變化的合理性。

### 5. 特徵選擇

Notebook 會使用多種方法進行特徵選擇，例如：

- mutual information
- 與成熟階段的單調關係
- proxy-based importance
- 穩定特徵池比較

此步驟用於找出最適合部署、且最有用的特徵。

### 6. 模型評估

Notebook 會評估多種模型策略，包含：

- 複查標籤訓練表
- 混合標籤版本
- CatBoost ordinal models
- 穩定特徵池實驗
- 錯誤熱點分析
- 單顆鳳梨的表現分析

此 Notebook 著重於**真實泛化能力**，而不只是訓練集準確率。

### 7. 部署候選模型搜尋

Notebook 也會探索適合 Raspberry Pi 部署的模型，包含：

- CatBoost-based deploy packs
- student models
- ExtraTrees deploy candidates
- 短時間窗口推論測試
- 不使用日期特徵的部署版本

### 8. 最終 Raspberry Pi 匯出

Notebook 最後的儲存格會匯出可直接用於 Raspberry Pi 的模型部署包。

---

## 訓練流程

此資料夾的整體流程如下：

1. 從 Arduino Mega 蒐集原始氣體感測資料
2. 整理鳳梨與空氣 Excel 檔案
3. 重新建立每日特徵
4. 產生工程化特徵
5. 載入並複查標籤
6. 修正或細化成熟階段標籤
7. 訓練並評估模型
8. 比較可部署候選模型
9. 匯出最終 Raspberry Pi 部署包

---

## 重要檔案

### `labeling_perfect_final.ipynb`
目前最新的完整訓練 Notebook。

### `labeling.xlsx`
原始人工標註檔，是主要的標籤來源。

### `data_label_audit_report.xlsx`
用於檢查標籤一致性與合併條件的稽核報表。

### `feature_columns.json`
儲存最終部署模型所使用的特徵欄位名稱。

### `model_final.pkl`
其中一個最終可部署版本所儲存的訓練模型檔。

### `cutpoints.json`
當模型採用 ordinal-style prediction 設計時，會使用此檔案中的切點設定。

### `stage_timeline.png`
用於視覺化成熟階段變化或階段相關分析的圖表。

---

## 資料夾說明

### `data/`
儲存訓練相關資料檔、中間處理資料，以及重建後的特徵表。

### `models/`
儲存訓練好的模型檔、中間模型，以及模型比較輸出。

### `reports/`
儲存訓練摘要、評估結果、稽核結果與相關匯出報表。

### `catboost_info/`
CatBoost 自動產生的訓練紀錄與暫存輸出。

此資料夾通常不一定需要上傳到 GitHub，必要時可以忽略。

### `deploy_rpi_catboost/`
使用 CatBoost ordinal-style model 的 Raspberry Pi 部署包。

### `deploy_rpi_student/`
使用 student model 的 Raspberry Pi 部署包，通常是由 teacher pipeline 蒸餾或簡化而來。

### `deploy_rpi_student_short/`
較短或較輕量化的 Raspberry Pi 部署版本。

### `deploy_rpi_et_10s/`
使用 10 秒推論窗口的 ExtraTrees 部署包。

### `deploy_rpi_et_10s_noday/`
使用 10 秒推論窗口、且不使用日期特徵的 ExtraTrees 部署包。

### `deploy_rpi_et_30s_noday/`
使用 30 秒推論窗口、且不使用日期特徵的 ExtraTrees 部署包。

此版本是重要的部署候選之一，因為它更適合實際裝置端推論。

### `deploy_rpi_et_30s_noday_s3_sensitive/`
修改過的 30 秒 ExtraTrees 部署包，對 Stage 3 相關判斷更敏感。

當系統希望更謹慎判斷過熟傾向時，此版本會較有幫助。

---

## Raspberry Pi 部署檔案

根據目前的訓練 Notebook，最終 Raspberry Pi 部署包應包含所選部署版本需要的檔案。

### 常見必要檔案

最終 Raspberry Pi 套件通常包含：

- 訓練好的模型檔案
- `feature_columns.json`
- 選用的 `scaler.pkl`
- 選用的 `cutpoints.json`
- 選用的 `deploy_meta.json`

實際檔案組合會依所選部署版本而不同。

### 選項 1：CatBoost Ordinal Deploy Pack

如果使用 CatBoost ordinal deployment 版本，Raspberry Pi 套件通常應包含：

- `cb_ge1.cbm`
- `cb_ge2.cbm`
- `cb_ge3.cbm`
- `scaler.pkl`
- `feature_columns.json`
- `deploy_meta.json`

這些檔案通常位於：

- `deploy_rpi_catboost/`

此版本對應 teacher-style ordinal deployment workflow。

### 選項 2：ExtraTrees 30s No-Day Deploy Pack

如果使用最終輕量化 Raspberry Pi 部署版本，套件通常應包含：

- `model_final.pkl` 或等效的 ET 模型檔
- `feature_columns.json`
- `deploy_meta.json`，若有產生

這些檔案通常位於：

- `deploy_rpi_et_30s_noday/`

如果使用對 Stage 3 更敏感的版本，則使用：

- `deploy_rpi_et_30s_noday_s3_sensitive/`

此版本更適合 Raspberry Pi，原因如下：

- 比 CatBoost 更輕量
- 避免使用日期相關特徵
- 支援短時間窗口推論
- 適合實際裝置部署

---

## 目前建議部署方向

根據 Notebook 後段的實驗結果，目前建議的部署方向為：

- 使用對 Raspberry Pi 友善的模型
- 優先選擇較短的推論窗口
- 避免不必要的日期相關特徵
- 固定 feature columns，確保推論穩定
- 匯出完整部署資料夾，而不是只匯出單一模型檔

因此，以下資料夾特別重要：

- `deploy_rpi_catboost/`
- `deploy_rpi_et_30s_noday/`
- `deploy_rpi_et_30s_noday_s3_sensitive/`

---

## 注意事項

- 此資料夾用途為**模型訓練、模型評估與部署包匯出**
- 此資料夾不是 Arduino 資料蒐集資料夾
- 此資料夾不是最終 Flask 或 Raspberry Pi runtime 資料夾
- `catboost_info/` 是訓練紀錄資料夾，通常不需要提交到 GitHub
- 如果 Git 出現路徑過長問題，請縮短資料夾名稱，或忽略暫存訓練資料夾

---

## 專案背景

此資料夾屬於本畢業專題的一部分：

**基於電子鼻之非破壞性鳳梨成熟度檢測系統**

此流程訓練出的模型後續會整合到 Raspberry Pi 推論端，並連接到整體應用系統。
