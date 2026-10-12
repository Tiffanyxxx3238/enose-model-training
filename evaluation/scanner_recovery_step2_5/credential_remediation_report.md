# 憑證處理報告（P0）

> **URGENT MANUAL ACTION: Rotate exposed Raspberry Pi SSH credentials.**

## 發現

- 3 個檔案以明碼寫入**同一組** Pi SSH 密碼（本報告只比對雜湊，從未輸出密碼本身）：
  - `Semester 2 Final Exam (三下-期末)/pineapple_final/app_local.py`（IP 172.20.10.2）
  - `Semester 2 Final Exam (三下-期末)/pineapple_deployment_system/app_local.py`（IP 192.168.0.152）
  - `3rd Grade - Semester 2(三下-期中)/pineapple_deployment_system/app_local.py`（IP 192.168.0.152）
- 使用者名稱 `linguanyu` 與 IP 也寫在程式中（不是秘密，但洩漏了攻擊目標資訊）。
- 密碼**仍存在於公開 repo 的 Git 歷史**中；本分支的修改無法移除它。

## 本次修正（3 個檔案相同）

- 刪除密碼常數，改成註解說明憑證來源。
- `RPI_USER`、`RPI_IP` 可以用環境變數 `PINENOSE_RPI_USER`、`PINENOSE_RPI_HOST` 覆寫，原值保留為預設。
- 新增 `_ssh_auth_kwargs()`：
  1. 優先使用 `PINENOSE_RPI_KEY_FILE`（SSH 金鑰，建議）；
  2. 其次使用 `PINENOSE_RPI_PASSWORD`；
  3. 兩者都沒有就 `RuntimeError`，**沒有任何寫死的 fallback**。
- `client.connect(...)` 改為使用 `**_ssh_auth_kwargs()`。

## 驗證（T9）

- 舊密碼只在記憶體中從 Git 歷史取出，用來比對後立即刪除，從未印出或寫檔。
- 掃描 35 個修改過的檔案與新輸出，含舊密碼的檔案數：0。
- 3 個 `app_local.py` 都用**假的**環境憑證測試：金鑰優先、密碼次之、缺少憑證時報錯。paramiko 被替換為假物件，沒有建立任何真實連線。

## 需要人工處理（本次不能也未執行）

1. 在 Pi 上更換密碼，建議改用金鑰登入並關閉密碼登入（`PasswordAuthentication no`）。
2. 檢查該密碼是否在其他帳號、Wi-Fi、服務上重複使用。
3. 檢查 Pi 的 SSH 存取紀錄（`/var/log/auth.log`、`last`、`journalctl -u ssh`）。
4. 團隊決定是否清理 Git 歷史（如 `git filter-repo`，需要 force-push 並通知所有協作者）；就算清理了，也要假設密碼已經外洩，因此第 1 點仍然必須做。
