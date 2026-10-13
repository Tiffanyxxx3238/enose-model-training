# 鳳梨智慧辨識系統｜整合網頁歷史紀錄功能 README

本文件說明 Raspberry Pi 整合網頁中「歷史紀錄管理」模組的使用方式、檔案位置、啟動方式與維護注意事項。
此版本是 **本機端歷史紀錄版本**，資料會儲存在 Raspberry Pi 本機，不會直接寫入學校 VM Docker 資料庫。

---

## 1. 功能簡介

歷史紀錄功能主要用來儲存「鳳梨氣味成熟度辨識」完成後的結果，讓使用者可以在整合網頁中管理近 30 天的成熟度紀錄。

目前支援：

1. 儲存成熟度辨識結果
2. 自訂紀錄檔案名稱
3. 選擇既有資料夾儲存
4. 新增資料夾並儲存
5. 歷史紀錄頁以資料夾方式顯示
6. 可點進資料夾查看該資料夾內紀錄
7. 可勾選單筆或多筆紀錄
8. 可搬移選取紀錄到其他資料夾
9. 可刪除選取紀錄
10. 可清空目前資料夾內所有紀錄
11. 可刪除資料夾，並一併刪除資料夾內所有紀錄
12. 每筆紀錄保留 30 天
13. 顯示每筆紀錄剩餘幾天到期
14. 可下載單筆紀錄或整個資料夾
15. 單筆下載為 HTML 報告
16. 多筆或資料夾下載為 ZIP，內含 summary.csv 與每筆 HTML 報告

---

## 2. 建議放置位置

請將本 README 放在整合網頁資料夾中：

```bash
/home/linguanyu/pineapple_unified_web/README_history.md
```

也就是：

```bash
~/pineapple_unified_web/README_history.md
```

原因是歷史紀錄功能主要是加在整合網頁 `pineapple_unified_web` 內，而不是原本的成熟度模型資料夾 `~/pineapple`。

---

## 3. 相關資料夾與檔案

目前歷史紀錄相關檔案主要分布如下：

```text
/home/linguanyu/
├── pineapple/
│   └── app_local.py
│       └── 成熟度辨識頁面，負責顯示「儲存歷史紀錄」按鈕與儲存浮框
│
├── pineapple_unified_web/
│   ├── app.py
│   │   └── 整合網站主程式，也包含歷史紀錄 API
│   │
│   ├── templates/
│   │   ├── index.html
│   │   │   └── 整合網站首頁，包含歷史紀錄分頁 iframe
│   │   │
│   │   └── history.html
│   │       └── 歷史紀錄管理頁面
│   │
│   ├── static/
│   │   └── style.css
│   │       └── 整合網站與歷史紀錄頁面樣式
│   │
│   └── data/
│       └── history.json
│           └── 本機端歷史紀錄資料
│
├── start_pineapple_system.sh
└── stop_pineapple_system.sh
```

---

## 4. 歷史紀錄資料儲存位置

歷史紀錄資料目前存在：

```bash
~/pineapple_unified_web/data/history.json
```

完整路徑：

```bash
/home/linguanyu/pineapple_unified_web/data/history.json
```

資料內容包含兩大部分：

```json
{
  "folders": [],
  "records": []
}
```

說明：

| 欄位 | 說明 |
|---|---|
| folders | 歷史紀錄資料夾 |
| records | 成熟度辨識紀錄 |

---

## 5. 每筆歷史紀錄包含的內容

每筆紀錄大致包含：

| 欄位 | 說明 |
|---|---|
| id | 紀錄 ID |
| filename | 使用者輸入的檔案名稱 |
| folder_id | 所屬資料夾 ID |
| created_at | 建立時間 |
| expires_at | 到期時間 |
| ripeness_label | 成熟度結果 |
| confidence | 信心分數 |
| note | 使用者備註 |
| raw_text | 原始輸出文字 |

---

## 6. 啟動方式

展示或測試時，請先啟動 Raspberry Pi 端三個服務：

```bash
cd ~
~/stop_pineapple_system.sh
~/start_pineapple_system.sh
```

啟動後確認服務：

```bash
ss -tulnp | grep python
```

正常應看到：

```text
5000  成熟度辨識頁
5002  照片 gateway 頁
8000  整合主網頁
```

整合主網頁網址：

```text
http://172.20.10.2:8000
```

如果 Raspberry Pi IP 改變，網址與程式中的 IP 也要一起改。

---

## 7. 使用流程

### 7.1 儲存成熟度紀錄

1. 打開整合網頁：

```text
http://172.20.10.2:8000
```

2. 進入「氣味成熟度辨識」

3. 完成完整鳳梨成熟度推論

4. 在結果下方按：

```text
💾 儲存歷史紀錄
```

5. 在浮框中填寫：

| 欄位 | 說明 |
|---|---|
| 檔案名稱 | 這筆紀錄的名稱 |
| 選擇既有資料夾 | 可選已有資料夾 |
| 新增資料夾名稱 | 若要新增資料夾，可在此輸入 |
| 備註 | 可填可不填 |

6. 按「儲存」

7. 到「歷史紀錄」分頁確認資料是否出現

---

## 8. 防呆機制

目前設計上應該只有在完整鳳梨成熟度推論完成後，才可以儲存歷史紀錄。

不應儲存的狀態：

| 狀態 | 是否可儲存 |
|---|---|
| 目前狀態頁 | 不可 |
| 空氣校正結果 | 不可 |
| Demo 空氣校正 | 不可 |
| 鳳梨成熟度推論結果 | 可 |
| Demo 鳳梨推論結果 | 可 |

若只完成空氣校正，不應出現「儲存歷史紀錄」按鈕。

---

## 9. 歷史紀錄頁操作

進入「歷史紀錄」分頁後，可以看到資料夾圖示。

### 9.1 查看資料夾

點擊資料夾卡片即可進入該資料夾，頁面會只顯示該資料夾內的紀錄。

### 9.2 返回全部資料夾

點擊：

```text
全部資料夾
```

即可回到全部資料夾檢視畫面。

### 9.3 選取紀錄

每筆紀錄左側有勾選框，可一筆一筆選取。

### 9.4 搬移紀錄

1. 勾選紀錄
2. 在「搬移到」下拉選單選目標資料夾
3. 按「搬移選取」

### 9.5 刪除紀錄

1. 勾選紀錄
2. 按「刪除選取」
3. 確認後會刪除選取紀錄

### 9.6 清空目前資料夾

進入某個資料夾後，按：

```text
清空目前資料夾
```

效果：

```text
只刪除目前資料夾內的所有紀錄
資料夾本身會保留
```

### 9.7 刪除目前資料夾

進入某個資料夾後，按：

```text
刪除目前資料夾
```

效果：

```text
刪除該資料夾
也會一併刪除該資料夾內所有紀錄
```

注意：

```text
預設資料夾不能刪除
```

---

## 10. 下載功能

歷史紀錄支援下載，方便管理者查看資料。

### 10.1 單筆下載

操作：

1. 勾選一筆紀錄
2. 按「下載選取」

下載結果：

```text
單筆 HTML 報告
```

例如：

```text
鳳梨成熟度紀錄_20260709_2205.html
```

管理者可直接雙擊，用瀏覽器開啟，不需要 VS Code。

---

### 10.2 多筆下載

操作：

1. 勾選兩筆以上紀錄
2. 按「下載選取」

下載結果：

```text
ZIP 壓縮檔
```

ZIP 內包含：

```text
summary.csv
每筆紀錄的 HTML 報告
```

其中：

| 檔案 | 說明 |
|---|---|
| summary.csv | 摘要表，可用 Excel 開啟 |
| xxx.html | 每筆紀錄的詳細報告 |

---

### 10.3 下載目前資料夾

操作：

1. 點進某個資料夾
2. 按「下載目前資料夾」

下載結果：

```text
ZIP 壓縮檔
```

ZIP 內包含：

```text
summary.csv
每筆紀錄的 HTML 報告
```

---

## 11. 後端 API

目前本機歷史紀錄 API 放在整合網站 `app.py`，服務位置：

```text
http://172.20.10.2:8000
```

主要 API：

| API | 方法 | 說明 |
|---|---|---|
| /history | GET | 歷史紀錄頁面 |
| /api/history | GET | 取得所有歷史紀錄 |
| /api/history/save | POST | 儲存一筆歷史紀錄 |
| /api/history/folders | POST | 新增資料夾 |
| /api/history/delete | POST | 刪除選取紀錄 |
| /api/history/move | POST | 搬移選取紀錄 |
| /api/history/folders/clear | POST | 清空資料夾內紀錄 |
| /api/history/folders/delete | POST | 刪除資料夾與其內部紀錄 |
| /api/history/download_report | POST | 下載 HTML / ZIP 報告 |

---

## 12. 檢查目前資料內容

若要在 Raspberry Pi 上查看目前有多少資料夾與紀錄，可執行：

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path.home() / "pineapple_unified_web/data/history.json"

print("history file:", p)
print("exists:", p.exists())

if not p.exists():
    print("目前還沒有 history.json")
    raise SystemExit

data = json.loads(p.read_text(encoding="utf-8"))

folders = data.get("folders", [])
records = data.get("records", [])

print("\n資料夾數量:", len(folders))
print("歷史紀錄數量:", len(records))

print("\n=== 資料夾 ===")
for f in folders:
    print(f"- {f.get('name')} | id={f.get('id')}")

print("\n=== 歷史紀錄 ===")
for i, r in enumerate(records, 1):
    print(f"{i}. {r.get('filename')}")
    print(f"   folder_id: {r.get('folder_id')}")
    print(f"   成熟度: {r.get('ripeness_label')}")
    print(f"   信心分數: {r.get('confidence')}")
    print(f"   建立時間: {r.get('created_at')}")
    print(f"   到期時間: {r.get('expires_at')}")
PY
```

---

## 13. 備份歷史紀錄資料

建議在大改功能前備份：

```bash
cp ~/pineapple_unified_web/data/history.json    ~/pineapple_unified_web/data/history_backup_$(date +%Y%m%d_%H%M%S).json
```

若程式改壞，可用備份還原。

---

## 14. 重啟服務

修改程式後，請重啟服務：

```bash
~/stop_pineapple_system.sh
~/start_pineapple_system.sh
```

若畫面沒有更新，請在瀏覽器按：

```text
Ctrl + F5
```

---

## 15. 常見問題

### Q1：資料有儲存，但歷史紀錄頁沒看到？

請先重新整理：

```text
Ctrl + F5
```

再確認資料是否真的寫入：

```bash
cat ~/pineapple_unified_web/data/history.json
```

---

### Q2：只做空氣校正也出現儲存按鈕？

代表 `app_local.py` 裡的按鈕放錯位置。

正確位置應該在：

```html
{% if mode == 'infer' and parsed %}
```

這個區塊內，不可以放在：

```html
{% if mode == 'air' and parsed %}
```

或整個頁面的外層。

---

### Q3：下載下來還是 JSON？

代表前端仍呼叫舊 API：

```text
/api/history/download
```

請確認 `history.html` 裡面已改成：

```text
/api/history/download_report
```

檢查指令：

```bash
grep -n "api/history/download" ~/pineapple_unified_web/templates/history.html
```

正確應該看到：

```text
/api/history/download_report
```

---

### Q4：ZIP 裡面應該有什麼？

新版下載應該包含：

```text
summary.csv
多個 .html 報告
```

如果還看到：

```text
_summary.json
多個 .json 檔案
```

代表還是舊版下載功能。

---

## 16. 與學校 VM App 歷史紀錄的關係

目前本功能是：

```text
Raspberry Pi 整合網頁本機歷史紀錄
```

資料存在：

```text
~/pineapple_unified_web/data/history.json
```

學校 VM 上的 App 歷史紀錄是另一套後端：

```text
pineapple-history
Port: 5002
用途：農民端 / 消費端 App 歷史紀錄
```

兩者目前不要混在一起。

建議後續做法：

```text
整合網頁保留「本機歷史紀錄」
另外新增「App VM 後台紀錄」分頁或獨立網頁
```

原因：

| 項目 | 本機歷史紀錄 | VM App 歷史紀錄 |
|---|---|---|
| 儲存位置 | Raspberry Pi history.json | 學校 VM Docker SQLite |
| 用途 | 整合網頁成熟度辨識 | 農民端 / 消費端 App |
| 欄位 | filename、folder、raw_text | app_type、variety、maturity、batch |
| 連線需求 | 不需要 VPN | 校外通常需要 VPN |

---

## 17. 開發注意事項

1. 不要把 VPN、VM 帳號密碼寫進 README 或前端程式。
2. 修改 `app.py` 前請先備份。
3. 修改 `history.html` 前請先備份。
4. 修改 `app_local.py` 前請先備份。
5. 歷史紀錄功能目前為本機 JSON 版本，未來若接 VM DB，建議另外做版本或分頁。
6. 若要給非工程背景管理者下載資料，建議使用 HTML 報告與 CSV，不建議只給 JSON。

---

## 18. 給同學看的最短版

歷史紀錄功能放在：

```bash
~/pineapple_unified_web
```

主要資料檔：

```bash
~/pineapple_unified_web/data/history.json
```

主要頁面：

```bash
~/pineapple_unified_web/templates/history.html
```

主要 API：

```bash
~/pineapple_unified_web/app.py
```

啟動：

```bash
~/stop_pineapple_system.sh
~/start_pineapple_system.sh
```

網址：

```text
http://172.20.10.2:8000
```

功能：

```text
成熟度推論完成後可儲存歷史紀錄
可用資料夾管理
可搬移、刪除、清空、刪除資料夾
可下載單筆 HTML 報告
可下載多筆或整個資料夾 ZIP
ZIP 內有 summary.csv 與 HTML 報告
```
