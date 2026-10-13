<!-- Copy of pinenose_release/docs/deployment_preflight_checklist.md as shipped in the release package (docs/deployment_preflight_checklist.md). -->
# PineNose 部署前檢查清單（人工關卡）

本套件狀態：**SOFTWARE RELEASE CANDIDATE — MATURITY INFERENCE NOT APPROVED**

每一項都需由負責人簽核。標示 ⛔ 的項目未完成時，**不得部署**。

## A. 發布套件

- [ ] 套件的 SHA-256 與發布紀錄的 `<套件>.tar.gz.sha256` 相符：`pinenose_backup.py install` 會自動驗證。
- [ ] `VERSION.json` 的 `source_commit` 與核准的發布 commit 相同。
- [ ] `SHA256SUMS` 驗證通過：`pinenose_service.py check` 會自動驗證。
- [ ] 套件內沒有任何 `.pkl`、原始資料、AIR 檔或掃描歷史。

## B. 安全

- [ ] ⛔ 曾外洩的 Pi SSH 憑證**已人工更換**。舊密碼仍留在 Git 歷史中。
- [ ] 部署環境中沒有任何密碼寫在檔案內。
- [ ] 不使用 SSH 執行模式：網頁服務以 `PINENOSE_WEB_EXEC=local` 執行，由服務管理程式自動設定。
- [ ] 舊 `start_server.sh`（ngrok）與 Gateway v1 不在 Pi 上執行。
- [ ] 服務只綁 127.0.0.1，或已核准的 Pi 私有區網 IP。沒有 `0.0.0.0`，也沒有公網轉發。

## C. 目標環境

在 Pi 上執行唯讀預檢：`ops/rpi3_preflight.py --profile-file …`。

- [ ] ⛔ 作業系統與架構已確認。建議 64-bit Raspberry Pi OS Bookworm（aarch64、Python 3.11）。
  - 32-bit 環境：模型 pickle 跨位元載入未驗證。
  - Bullseye（Python 3.9）**不相容**。
- [ ] ⛔ `requirements_release.txt` 全部版本在 Pi 上安裝成功：`python_packages` PASS。
- [ ] 記憶體（建議可用 ≥ 350 MB）與磁碟（≥ 500 MB）充足。
- [ ] 服務使用者在 `dialout` 群組（序列埠權限）。
- [ ] Arduino 序列埠可被列出（預檢只列出，不開啟）。

## D. 設定

- [ ] `profile.json` 是正式 profile，`runtime.formal.json` 的 mode 為 formal。
- [ ] ⛔ 正式核准清單 `model_registry.formal.json` **保持空白**，除非有書面的人工模型核准決定。
- [ ] ⛔ `air_max_age_sec` 保持 null，除非有經核准、具依據的 AIR 有效期限。
- [ ] `device_id`：只有真實存在的設備 ID 才能填；沒有就保持 null。
- [ ] `lan_access` 與各服務的 host、port 符合核准的網路配置；整合網頁的 `smell_url` 填 Pi 的區網位址。
- [ ] 工程（TEST）profile **不在**正式 Pi 上啟用。

## E. 實機驗證（Step 6B／6C，本套件尚未進行）

- [ ] ⛔ 在 Pi 上啟動、執行健康檢查、停止都正常。
- [ ] ⛔ 以真實 Arduino 完成 header 讀取、取消、逾時測試。
- [ ] ⛔ 正式 AIR 校正已依程序完成，並保留來源紀錄。
- [ ] ⛔ 原生 App 安裝檔已建置，並在實機測試。
- [ ] 部署前已備份（`pinenose_backup.py backup --execute`），且已驗證備份（`verify`）。
- [ ] 已確認回復程序（`rollback`）與負責人。

## F. 簽核

| 角色 | 姓名 | 日期 | 簽核 |
|---|---|---|---|
| 系統負責人 | | | |
| 安全／憑證負責人 | | | |
| 模型與資料負責人（確認：沒有核准模型） | | | |
