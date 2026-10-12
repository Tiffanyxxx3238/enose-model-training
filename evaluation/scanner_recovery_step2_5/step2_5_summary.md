# Scanner Recovery Step 2.5 — 總結

> **URGENT MANUAL ACTION: Rotate exposed Raspberry Pi SSH credentials.**
>
> - 同一組 Pi SSH 密碼曾以明碼寫在 3 個 `app_local.py`（對應 2 個 IP：172.20.10.2、192.168.0.152），且**仍存在於公開 Git 歷史**。本次只移除了工作樹中的明碼，**沒有**也**不能**讓已外洩的密碼失效。
> - 需另外由人工處理：（1）在 Pi 上更換密碼並改用 SSH 金鑰；（2）檢查此密碼是否在其他帳號／裝置重複使用；（3）檢查 Pi 的 SSH 登入紀錄（如 `/var/log/auth.log`、`last`）是否有異常存取；（4）評估是否清理 Git 歷史（需 force-push，影響所有協作者，須團隊決定）。
> - 本報告與所有輸出檔都**不含**該密碼。

- 工作區：`c:/Users/user/enose-scanner-recovery-step2-5`
- 分支：`analysis/scanner-recovery-step2-5`（由 `799552c` 建立；僅本機 commit，未 push／merge／部署）
- 本次未登入 Pi、未開 serial port、未啟動 server、未連正式 API、未改 App／Gateway、未重訓、未覆蓋 `.pkl`、未進行 Step 3。

## 最終決策

| 標記 | 是否成立 | 說明 |
|---|---|---|
| **BLOCKED BY UNVERIFIED DEPLOYMENT OR CREDENTIAL RISK** | **是（主要）** | 憑證尚未更換；Pi 上實際執行的程式版本未驗證（COMPETITION PATH NOT VERIFIED）。 |
| AIR CALIBRATION WORKFLOW REPAIR REQUIRED | 部分已處理 | demo／live baseline 分檔、provenance、拒絕 1.0 假 baseline 已修；baseline 有效期限尚無資料可定，需在 Pi 上實測決定。 |
| MORE SOFTWARE REPAIR REQUIRED | 否（離線範圍內） | Web CLI 特徵已與訓練一致（T1–T10 全 PASS）。App 的 random mock 屬展示風險，建議另案處理。 |
| READY FOR CONTROLLED PI VERIFICATION | **條件式** | 須先完成憑證更換，並由人工授權部署本分支到 Pi 後才成立。 |

**Step 3（AIR sensitivity）是否值得做：值得，但順序在後。** 先換憑證、確認 Pi 上的程式版本、把修正版 CLI 受控部署並做同果重複測試；之後再做 Step 3 才有意義（否則量到的是舊程式的誤差）。本次**未**開始 Step 3。

## 主要發現

1. **Web CLI（`pineapple_final/inference_30s.py`）兩個比值特徵算錯**：`MQ2_MQ3_ratio`、`MQ3_MQ135_ratio` 用原始 ADC 平均相除，訓練端是 `mean_norm(a)/(mean_norm(b)+1e-9)`。已修正，11 特徵與訓練參考最大差 1.58e-14（T1），四類機率最大差 3.47e-18（T2）。
2. **舊的後處理規則（early_stage / overripe override）是在錯誤比值上調出的門檻**。套到正確特徵上 0 次觸發；預設改為 `raw`（顯示模型原始判定），舊規則只輸出為診斷，保留 `--postprocess legacy` 供比對。
3. **AIR baseline 缺值時會默默用 1.0**（校正端與推論端都有）。已改為報錯；demo 校正改寫 `air_base_demo.json`，不再覆蓋實測的 `air_base.json`；baseline 附 `_meta`（來源、calibration_id、時間、樣本數）。
4. **新發現的資料異常**：pid 11 / 2026-02-14 的鳳梨檔與空氣檔相同（fruit == air），與既有的 (3, 0214)、(4, 0206) 同類。此檔與 pid 13 / 2026-03-04 的表頭在第 349 列（前面有 348 列預熱 log），先前讀取器只掃前 10 列而漏讀，因此 Step 2 只有 101 天。

## C0–C3 比較（101 天 Step 2 資料集；accuracy 為訓練資料上的參考值，不代表泛化）

| 版本 | 說明 | 最終分佈 [S0,S1,S2,S3] | 改判次數 | acc（參考） | Recall S0/S1/S2/S3 |
|---|---|---|---|---|---|
| C0 | 原版 CLI | [13,37,40,11] | 20 | 0.624 | 0.312 / 0.778 / 0.852 / 0.600 |
| C1 | 只修特徵 | [10,42,38,11] | 0 | 0.663 | 0.312 / 0.852 / 0.889 / 0.667 |
| **C2** | 修特徵＋不覆寫（主要最小修正） | [10,42,38,11] | 0 | 0.663 | 0.312 / 0.852 / 0.889 / 0.667 |
| C3 | C2＋3 窗平均（0/10/20 秒，僅候選） | [8,44,38,11] | 0 | 0.644 | 0.250 / 0.852 / 0.889 / 0.667 |

- C0→C1：最終類別改變 29/101 天（A 10、B 14、C 4、D 1）。C1→C2：0 天。C2→C3：2 天（皆 C 組，S0→S1）。
- 排除 2 個已知異常（99 天）：C0 0.626、C2 0.667、C3 0.646。含 2 天新讀到的資料（103 天）：C0 0.621、C2 0.650。
- **C3 不建議採用**：沒有改善，反而降低 S0 recall。
- 跨果實（LOGO）的真實準確率在先前輪次約 0.43，本次修正只消除軟體不一致，不會提升模型本身的泛化能力。

## 測試結果：10/10 PASS

T1 特徵一致、T2 機率一致、T3 重播可重現、T4 缺失／無效 AIR、T5 無效輸入（12/12）、T6 無靜默改判、T7 模型 SHA 不變、T8 無部署變更、T9 憑證衛生、T10 推論可追溯。詳見 `test_results.txt`。

## 剩餘風險

1. Pi 上實際執行的程式版本未知（可能仍是舊版）。
2. 憑證尚未更換，且舊密碼仍在 Git 歷史中。
3. AIR baseline 的有效期限／漂移未知，沒有依據的期限值未寫入程式。
4. 同一顆鳳梨在硬體上的重複性未量測（Step 2 已知 9 天的結果會隨取樣窗改變）。
5. 跨果實準確率有限（LOGO 約 0.43）；S0 recall 只有 0.31。
6. App 端有 random mock 路徑（Farmer BatchScanScreen 永遠是亂數），展示時可能被誤認為真實結果。

## 輸出檔

| 檔案 | 內容 |
|---|---|
| `actual_inference_path_audit.md` | 實際資料流 A–D 路徑稽核 |
| `web_cli_repair_report.md` | Web CLI 修正內容 |
| `feature_parity.csv` | 每天 × 每特徵：訓練參考 vs 原版 CLI vs 修正版 CLI |
| `prediction_variant_comparison.csv` | 每天 C0–C3 預測 |
| `class_flip_attribution.csv` | 類別改變歸因 |
| `variant_metrics.csv`、`confusion_matrices.json` | 指標與混淆矩陣 |
| `air_baseline_state_audit.md` | AIR baseline 狀態稽核與修正 |
| `mock_demo_audit.md` | mock／demo 稽核（未改 UI） |
| `credential_remediation_report.md` | 憑證處理 |
| `model_integrity_check.txt` | 模型 SHA 檢查 |
| `test_results.txt` | T1–T10 |
| `git_safety_check.txt` | 工作區安全檢查 |
| `step2_5_validation.py`、`run_log.txt` | 可重跑的驗證腳本與執行紀錄 |
