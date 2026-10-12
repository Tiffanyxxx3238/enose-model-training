# Step 3 AIR Sensitivity Audit — 預先登錄規格

本檔在計算任何 Step 3 結果之前 commit。之後不因結果修改；若發現解析 bug，記錄原因與影響，並一致套用到所有條件。

## 0. 已核對的事實（來自程式與資料結構，不是結果）

- C2 特徵：`pineapple_app_gateway/app_gateway_v2.py` 的 `_build_features`（修正版，Step 2.5／2.6 已驗證與訓練 notebook 一致），經 `eval_common.extended_features` 呼叫。
- FIXED11 中有 **9 個特徵依賴 AIR baseline**：
  - 除以單一感測器的 baseline：MQ3_std_norm、MQ3_range_norm、TGS2602_min_norm、MQ2_auc_norm、MQ2_mean_norm、MQ9_min_norm、TGS2602_std_norm
  - 除以兩個感測器 baseline 的比值：MQ2_MQ3_ratio、MQ3_MQ135_ratio
  - **不依賴** AIR：MQ9_slope、MQ9_delta_mean
- 每次替換 AIR 都會重新計算完整的 11 個特徵，不是只改單一欄位。
- 部署模型 SHA-256：`a57dbbbf…16a1`。
- 原始檔案：333 個。有標籤且有鳳梨檔的日子：103 天。
- AIR 正式資料列數：102 份 900 列、1 份 899 列（4／2026-02-05，A2 窗口不完整）。鳳梨檔：900／899／901 列。沒有 1800 列的檔案。
- 窗口索引以「成功解析的正式 ADC 資料列」為準（表頭之後、5 個氣體感測值皆非缺值的列），不是 Excel 列號。

## 1. 資料集合（沿用 Step 2.6／2.7）

| 名稱 | 定義 | 角色 |
|---|---|---|
| **QA96** | S99 扣除「同一顆鳳梨、不同日期共用同一份 AIR 資料」的日子（4／0203、13／0311、13／0312） | **AIR 結論的主要有效集合**：每一天都有獨立的配對 AIR |
| **S99** | Round 2 的 101 天扣除 fruit==air 的 3／0214、4／0206 | 與舊研究完全可比的集合（同時報告） |
| S101 | Round 2 原始 101 天 | 敏感度 |
| S100 | 全部可讀的 103 天扣除 3 筆 fruit==air | 敏感度（擴充） |

- 11／2026-02-14（第三筆 fruit==air）不在 S99／QA96／S101 中，S100 也已將它排除。
- 「不同鳳梨同一天共用 AIR」（5／6 的 0202、7／8 的 0203）視為同一次空氣量測，只標記、不排除。
- 決策以 QA96 計算，S99 同時計算；**兩者的決策類別不同時，最終判為 EVALUATION INCONCLUSIVE**。

## 2. 窗口（30 筆；1 Hz）

| 代號 | AIR 列 | 用途 |
|---|---|---|
| A0 | 0–29 | 原始配對（＝訓練與部署定義；程式會 assert 等於既有 baseline） |
| A0+10 | 10–39 | 與 Fruit F1 對齊的短時間尺度 |
| A0+20 | 20–49 | 與 Fruit F2 對齊的短時間尺度 |
| A1 | 300–329 | 同日中段 |
| A2 | 870–899 | 同日後段（約 15 分鐘後） |

Fruit 窗口：F0＝0–29、F1＝10–39、F2＝20–49。

- AIR baseline ＝ 窗口內各感測器 ADC 平均。
- 同日 AIR 的比較只使用**所有窗口都可用的交集日**（AIR ≥ 900 列；因此 4／0205 不在交集中，另外報告）。
- 不依每一天的標籤挑選窗口。

## 3. 比較條件（全部相對於 B0＝F0＋同日 A0）

- **Part B（固定 Fruit F0，改 AIR）**：B1＝A1、B2＝A2；短時間尺度：A0+10、A0+20。
- **Part C（相鄰日期 AIR，counterfactual stress test）**：Fruit F0 搭配同一顆鳳梨「前一個」與「後一個」標籤日的 AIR A0，分開報告。
  - 往前（或往後）找最近的日期，該日 AIR 必須：檔案可讀、≥ 30 列、5 個感測器的 A0 都在 10–1000、該日不是 fruit==air、不屬於同一顆鳳梨跨日共用 AIR，且 AIR 資料不能和本日 AIR 完全相同。
  - 最近的日期不合格時繼續往前（後）找，並記錄相隔天數與跳過原因；找不到就跳過該配對，不填補。
- **Part D（固定 AIR A0，改 Fruit）**：F1、F2。
- **共同時間尺度**：AIR A0→A0+10 對 Fruit F0→F1；AIR A0→A0+20 對 Fruit F0→F2。在同一批交集日上比較。

## 4. 模型

- **E1 固定部署模型**（`deploy_student.pkl`，不重新訓練）：只回答固定模型的敏感度，不是泛化結果。
- **E2 嚴格 LOGO**（主要）：
  - 規格與 Round 2／Step 2.6／2.7 相同：ET n=400、sqrt、bootstrap=False、random_state=42；FIXED11；訓練窗口起點 0／30／60／90／120（權重 1/5）；只用訓練折中位數補值。
  - 訓練特徵使用原始配對 AIR A0（訓練定義不變）。
  - 每折留出一整顆鳳梨；**同一折的模型用於該折所有測試條件**。
  - 機率依 `classes_` 對應回 Stage 0–3。

## 5. 定義

- **翻轉**：條件的 argmax 類別 ≠ B0 的 argmax 類別（同一個模型）。
- **跨級跳動**：|pred_條件 − pred_B0| ≥ 2。
- **嚴重錯誤**：|pred − true| ≥ 2。
- **機率變化**：L1 ＝ Σ|p − p_B0|；Max ＝ max|p − p_B0|。
- **對錯轉換**（相對 B0）：
  - 對→錯（Correct→Incorrect）
  - 錯→對（Incorrect→Correct）
  - 錯→另一個錯（Incorrect→Different Incorrect）
  - 錯但不變（Unchanged Incorrect）
  - 對且不變（Unchanged Correct）
- **事後可救回比例（只描述，oracle）**：B0 判錯的天數中，在 {A1, A2} 至少一個條件下變對的比例；以及在所有同日 AIR 條件 {A0, A0+10, A0+20, A1, A2} 都仍然錯的天數。**不是可部署的方法。**
- **S2／3→S0 錯誤**：B0 中真實為 2 或 3、預測為 0 的天數；報告其中在任何同日 AIR 條件（A1、A2、A0+10、A0+20）下預測會改變的比例，以及改變後是否變對。

## 6. AIR 穩定性（Part A，只描述）

- 範圍：每個有標籤日的配對 AIR 檔；共用 AIR 只計一次並標記。
- 每個感測器、每個窗口：mean、median、std；A0→A1、A0→A2 的絕對變化與相對變化（A0 平均 ≥ 10 才計算相對變化，否則記 NaN）；全段線性斜率（ADC／100 列）；不同 ADC 值的數量。
- 標記「明顯漂移」：任一感測器 |A0→A2 相對變化| ≥ 0.10（不使用標籤）。
- 各群組（負責人群組，不是設備 ID）、各階段的 A0 分布。
- 同一顆鳳梨相鄰日期 AIR A0 的差異（只描述，不是重複性量測）。

## 7. 統計

- 以 pineapple ID 為群集的 paired bootstrap：B=2000、seed=0、percentile 95% CI，探索性。
- 計算項目：
  - 各同日 AIR 條件的翻轉率
  - 各條件相對 B0 的 accuracy 差
  - Fruit F1、F2 的翻轉率
  - 共同時間尺度的差：（AIR A0+10 翻轉率 − Fruit F1 翻轉率）、（A0+20 − F2）
  - 相鄰日期的翻轉率（只用各自可用的日子，與同日條件分開）
  - A1、A2 相對 B0 的 Stage 2／3 嚴重錯誤率變化
- 同一表格內的比較使用相同的交集樣本。

## 8. 決策準則（以 QA96 的 LOGO 計算；S99 必須得到相同類別）

令 `flip_same` ＝ max（A0→A1 翻轉率，A0→A2 翻轉率）。

- **I（大量且分散的不穩定）**：同時符合
  - `flip_same` ≥ 0.25，且其 CI 下限 ≥ 0.15
  - 有翻轉的鳳梨 ≥ 8／13
  - 單一鳳梨貢獻的翻轉數 ≤ 30%
  - 排除任何有資料旗標的日子後，`flip_same` 仍 ≥ 0.25
- **E（能解釋主要錯誤）**：B0 的 S2／3→S0 錯誤中，在任何同日 AIR 條件下預測改變的比例 ≥ 0.25。

判定順序：

1. `flip_same` < 0.10 → **B. AIR VARIATION HAS LIMITED PREDICTIVE IMPACT**
2. 符合 I 且符合 E → **A. AIR VARIATION IS A MAJOR PREDICTION INSTABILITY FACTOR**
3. `flip_same` ≥ 0.10 且不符合 E → **C. AIR EFFECT EXISTS BUT DOES NOT EXPLAIN MAIN ERRORS**
4. 其他 → **D. EVALUATION INCONCLUSIVE**

**部署建議**（與上述決策分開判斷）：

- 事先指定、**不使用標籤**的 AIR 品質指標：
  - q1：A0→A2 最大相對漂移（5 個感測器取最大絕對值）
  - q2：A0 窗口內最大變異係數（std ÷ mean，5 個感測器取最大）
  - q3：任何 AIR 資料旗標
- 以 QA96 的分位數（q1、q2 取前 25%，只用 AIR 數值）分組，比較 LOGO B0 的錯誤率。
- 只有在某個指標的「高值組 − 其他組」錯誤率差 ≥ 0.15、cluster bootstrap CI 下限 > 0，且 S99 方向一致時，才判為 **AIR QUALITY CHANGE WORTH FUTURE VALIDATION**（只是值得在新資料上驗證，不是部署）。否則判為 **DO NOT ADD NEW AIR DECISION RULES**。
- 任何 AIR 條件的 accuracy 點估計較高，都不能作為推薦依據。

## 9. 停止條件

- A0 baseline 與既有 `d["air"]` 不一致，或 B0 特徵與既有 `d["feats"][0]` 不一致 → 停止（路徑錯誤）。
- 任一條件的 LOGO B0 預測與 Step 2.7 Strategy A 不一致 → 停止。
- 安全檢查失敗（`.pkl`、原始 XLSX 雜湊或其他工作區有變動）→ 停止並回報。
- 不寫出任何模型檔，不連接任何設備，不開始任何新的 AIR 校正方案設計。
