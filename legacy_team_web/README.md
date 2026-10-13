# 鳳梨智慧辨識系統整合網站 README

本專案為「鳳梨智慧辨識系統」的整合展示版本，主要目標是將原本分開操作的兩個功能整合到同一個 Raspberry Pi 網站中，讓使用者可以透過同一個入口頁面切換功能分頁，分別操作：

1. 鳳梨氣味成熟度辨識
2. 鳳梨照片品種辨識

整合後的網站網址為：

```text
http://192.168.0.152:8000
```

使用者只需要打開這個網址，就可以在同一個網站中使用兩個功能，不需要再分別記住不同網站頁面。

---

## 一、目前系統架構

目前系統分成三個主要服務：

```text
1. 鳳梨氣味成熟度辨識網頁
   執行位置：Raspberry Pi
   資料夾：/home/linguanyu/pineapple
   啟動檔案：app_local.py
   使用連接埠：5000

2. 鳳梨照片品種辨識呈現頁
   執行位置：Raspberry Pi
   資料夾：/home/linguanyu/pineapple_app_gateway
   啟動檔案：app_gateway.py
   使用連接埠：5002

3. 鳳梨智慧辨識整合網站
   執行位置：Raspberry Pi
   資料夾：/home/linguanyu/pineapple_unified_web
   啟動檔案：app.py
   使用連接埠：8000
```

另外，照片品種辨識的模型本體目前是跑在 Windows 本機端 VS Code 中：

```text
Windows 本機端資料夾：
C:\Users\user\Desktop\鳳梨\pineapple_detection

主要啟動檔：
server_variety.py

模型 API：
http://192.168.0.176:5001/predict
```

因此目前整體流程為：

```text
使用者
  ↓
Raspberry Pi 整合網站
http://192.168.0.152:8000
  ↓
分頁一：氣味成熟度辨識
  ↓
Raspberry Pi 本機執行成熟度模型
  ↓
回傳成熟度結果

分頁二：照片品種辨識
  ↓
Raspberry Pi 呈現頁接收圖片
  ↓
送到 Windows 本機端照片模型 API
http://192.168.0.176:5001/predict
  ↓
回傳品種辨識結果
```

---

## 二、今日新增與修改內容

今天主要完成以下整合工作：

```text
1. 新增 Raspberry Pi 整合網站資料夾 pineapple_unified_web
2. 建立整合網站 app.py
3. 建立整合網站 templates/index.html
4. 建立整合網站 static/style.css
5. 將氣味成熟度頁面與照片品種辨識頁面整合到同一個網站中
6. 使用分頁方式切換兩個功能
7. 將整合網站外觀改成較正式的展示系統風格
8. 加入開場動畫
9. 將開場動畫改成農夫抱著一籃鳳梨的版本
10. 加入系統總覽、狀態卡、操作說明與頁尾開發資訊
11. 新增一鍵啟動腳本 start_pineapple_system.sh
12. 新增一鍵停止腳本 stop_pineapple_system.sh
13. 建立備份與下載方式，方便將整合網站與 shell script 備份回 Windows 本機
```

---

## 三、Raspberry Pi 目前重要資料夾

目前 Raspberry Pi 家目錄下主要相關資料夾如下：

```text
/home/linguanyu/
├── pineapple/
│   └── 鳳梨氣味成熟度辨識系統
│
├── pineapple_app_gateway/
│   └── 鳳梨照片品種辨識呈現頁
│
├── pineapple_unified_web/
│   └── 鳳梨智慧辨識整合網站
│
├── start_pineapple_system.sh
│   └── 一鍵啟動 Raspberry Pi 端所有網站服務
│
├── stop_pineapple_system.sh
│   └── 一鍵停止 Raspberry Pi 端所有網站服務
│
└── pineapple_logs/
    └── 啟動後產生的服務紀錄檔
```

---

## 四、整合網站資料夾結構

`pineapple_unified_web` 目前結構如下：

```text
pineapple_unified_web/
├── app.py
├── templates/
│   └── index.html
├── static/
│   └── style.css
└── .venv/
```

各檔案功能：

```text
app.py
負責啟動整合網站，並指定氣味成熟度頁面與照片品種辨識頁面的網址。

templates/index.html
整合網站主畫面，包含開場動畫、首頁內容、功能分頁、iframe 內嵌頁面、操作說明與 footer。

static/style.css
整合網站的所有版面與動畫樣式，包含正式展示系統風格與農夫抱鳳梨籃開場動畫。
```

---

## 五、整合網站目前連接設定

`pineapple_unified_web/app.py` 中目前設定：

```python
SMELL_PAGE_URL = "http://192.168.0.152:5000"
PHOTO_PAGE_URL = "http://192.168.0.152:5002"
```

意思是：

```text
氣味成熟度辨識頁面：
http://192.168.0.152:5000

照片品種辨識呈現頁：
http://192.168.0.152:5002

整合網站入口：
http://192.168.0.152:8000
```

如果之後 Raspberry Pi 的 IP 改變，需要一起修改 `app.py` 裡面的 IP。

可使用以下指令查詢 Raspberry Pi IP：

```bash
hostname -I
```

---

## 六、Windows 本機端照片模型設定

照片辨識模型目前跑在 Windows 本機端：

```text
C:\Users\user\Desktop\鳳梨\pineapple_detection
```

啟動指令：

```bat
cd /d C:\Users\user\Desktop\鳳梨\pineapple_detection
python server_variety.py
```

`server_variety.py` 最後應確認使用：

```python
app.run(host="0.0.0.0", port=5001)
```

不能只使用：

```python
app.run(host="127.0.0.1", port=5001)
```

因為 `127.0.0.1` 只允許 Windows 電腦自己連線，Raspberry Pi 會連不到。

目前 Windows 電腦 Wi-Fi IP 為：

```text
192.168.0.176
```

所以照片模型 API 位址為：

```text
http://192.168.0.176:5001/predict
```

---

## 七、啟動系統流程

展示前需要先啟動 Windows 本機端照片模型，再啟動 Raspberry Pi 端服務。

### 步驟 1：啟動 Windows 本機端照片模型

在 Windows CMD 或 VS Code Terminal 執行：

```bat
cd /d C:\Users\user\Desktop\鳳梨\pineapple_detection
python server_variety.py
```

確認看到類似：

```text
Running on http://127.0.0.1:5001
Running on http://192.168.0.176:5001
```

代表 Windows 端照片模型已啟動。

### 步驟 2：啟動 Raspberry Pi 端所有網站服務

在 Raspberry Pi 執行：

```bash
~/start_pineapple_system.sh
```

這個腳本會依序啟動：

```text
1. 鳳梨氣味成熟度辨識頁面
   http://192.168.0.152:5000

2. 鳳梨照片品種辨識呈現頁
   http://192.168.0.152:5002

3. 鳳梨智慧辨識整合網站
   http://192.168.0.152:8000
```

### 步驟 3：打開整合網站

在瀏覽器開啟：

```text
http://192.168.0.152:8000
```

進入後會先看到開場動畫，接著進入主系統頁面。

主系統包含兩個功能分頁：

```text
1. 氣味成熟度辨識
2. 照片品種辨識
```

---

## 八、停止系統流程

如果要停止 Raspberry Pi 端所有網站服務，執行：

```bash
~/stop_pineapple_system.sh
```

執行後會停止：

```text
app_local.py
app_gateway.py
pineapple_unified_web/app.py
```

如果 Windows 本機端照片模型也要停止，請回到 Windows 執行 `server_variety.py` 的視窗，按：

```text
Ctrl + C
```

即可停止照片模型 API。

---

## 九、一鍵啟動腳本內容

`start_pineapple_system.sh` 主要功能是一次啟動 Raspberry Pi 上的三個服務。

目前腳本位置：

```text
/home/linguanyu/start_pineapple_system.sh
```

使用方式：

```bash
~/start_pineapple_system.sh
```

腳本會將 log 存到：

```text
/home/linguanyu/pineapple_logs/
```

三個 log 檔案分別為：

```text
ripeness.log
photo_gateway.log
unified_web.log
```

如果某個服務沒有正常啟動，可以查看 log：

```bash
cat ~/pineapple_logs/ripeness.log
cat ~/pineapple_logs/photo_gateway.log
cat ~/pineapple_logs/unified_web.log
```

---

## 十、一鍵停止腳本內容

`stop_pineapple_system.sh` 主要功能是停止 Raspberry Pi 上的相關 Python 網站服務。

目前腳本位置：

```text
/home/linguanyu/stop_pineapple_system.sh
```

使用方式：

```bash
~/stop_pineapple_system.sh
```

---

## 十一、檢查服務是否啟動成功

在 Raspberry Pi 執行：

```bash
ss -tulnp | grep python
```

正常情況下應該看到類似：

```text
0.0.0.0:5000
0.0.0.0:5002
0.0.0.0:8000
```

代表三個 Raspberry Pi 端服務都有成功啟動。

---

## 十二、常見問題與排除方式

### 1. 整合網站開得起來，但分頁裡面顯示拒絕連線

可能原因：

```text
1. 對應功能頁沒有啟動
2. app.py 裡面的 IP 寫錯
3. iframe 使用 localhost，導致瀏覽器誤判為 Windows 本機
4. 該 port 被其他程式占用
```

解決方式：

```bash
ss -tulnp | grep python
```

確認是否有：

```text
5000
5002
8000
```

並確認 `pineapple_unified_web/app.py` 裡面是 Raspberry Pi IP，不是 localhost。

### 2. 照片辨識無法回傳結果

可能原因：

```text
1. Windows 端 server_variety.py 沒有啟動
2. Windows 電腦 IP 改變
3. Raspberry Pi 與 Windows 電腦不在同一個網路
4. server_variety.py 使用 127.0.0.1，而不是 0.0.0.0
5. Windows 防火牆擋住 Python
```

檢查 Windows IP：

```bat
ipconfig
```

目前應使用 Wi-Fi 的 IPv4：

```text
192.168.0.176
```

在 Raspberry Pi 測試是否能連到 Windows：

```bash
ping 192.168.0.176
```

測試照片模型 API：

```bash
curl -X POST -F "image=@test_7.jpg" http://192.168.0.176:5001/predict
```

如果欄位名稱不是 `image`，可改測：

```bash
curl -X POST -F "file=@test_7.jpg" http://192.168.0.176:5001/predict
```

### 3. 修改 CSS 後畫面沒有變

通常是瀏覽器快取。

解決方式：

```text
Ctrl + F5
```

或使用無痕視窗重新開啟：

```text
http://192.168.0.152:8000
```

### 4. 啟動腳本沒有反應

確認腳本有執行權限：

```bash
chmod +x ~/start_pineapple_system.sh
chmod +x ~/stop_pineapple_system.sh
```

重新執行：

```bash
~/start_pineapple_system.sh
```

### 5. port 被占用

可以先停止所有服務：

```bash
~/stop_pineapple_system.sh
```

再重新啟動：

```bash
~/start_pineapple_system.sh
```

或查詢目前占用狀況：

```bash
ss -tulnp | grep python
```

---

## 十三、備份整合網站

今日新增的整合網站與啟動腳本可打包備份。

在 Raspberry Pi 執行：

```bash
cd ~
tar --exclude='pineapple_unified_web/.venv' \
    -czvf pineapple_unified_web_backup.tar.gz \
    start_pineapple_system.sh \
    stop_pineapple_system.sh \
    pineapple_unified_web
```

這會產生：

```text
/home/linguanyu/pineapple_unified_web_backup.tar.gz
```

此備份包含：

```text
start_pineapple_system.sh
stop_pineapple_system.sh
pineapple_unified_web/
```

但不包含 `.venv`，因此檔案較乾淨，也比較適合傳給同學或自己留存。

---

## 十四、從 Raspberry Pi 下載備份到 Windows

在 Windows CMD 或 PowerShell 執行：

```bat
cd /d C:\Users\user\Desktop
scp linguanyu@192.168.0.152:/home/linguanyu/pineapple_unified_web_backup.tar.gz .
```

下載後，桌面會出現：

```text
pineapple_unified_web_backup.tar.gz
```

---

## 十五、還原備份到 Raspberry Pi

如果之後要把備份傳回 Raspberry Pi：

在 Windows 執行：

```bat
scp C:\Users\user\Desktop\pineapple_unified_web_backup.tar.gz linguanyu@192.168.0.152:/home/linguanyu/
```

在 Raspberry Pi 解壓縮：

```bash
cd ~
tar -xzvf pineapple_unified_web_backup.tar.gz
chmod +x start_pineapple_system.sh
chmod +x stop_pineapple_system.sh
```

如果 `.venv` 沒有備份，需要重新建立整合網站的虛擬環境：

```bash
cd ~/pineapple_unified_web
python3 -m venv .venv
source .venv/bin/activate
pip install flask
```

---

## 十六、正式展示建議流程

正式展示時建議照以下順序操作：

```text
1. 確認 Raspberry Pi、Windows 電腦在同一個 Wi-Fi
2. Windows 先啟動照片模型 server_variety.py
3. Raspberry Pi 執行 ~/start_pineapple_system.sh
4. 開啟整合網站 http://192.168.0.152:8000
5. 先展示首頁與系統總覽
6. 切到氣味成熟度辨識分頁，展示成熟度檢測流程
7. 切到照片品種辨識分頁，展示照片上傳與品種辨識流程
8. 展示完成後，Raspberry Pi 執行 ~/stop_pineapple_system.sh
9. Windows 端按 Ctrl + C 停止 server_variety.py
```

---

## 十七、目前系統限制

目前版本仍有以下限制：

```text
1. 照片模型仍需 Windows 本機端啟動
2. Raspberry Pi 目前主要負責整合展示與氣味成熟度模型
3. 整合網站透過 iframe 顯示原本兩個功能頁，因此內層頁面風格可能與外層網站略有差異
4. 若 Raspberry Pi 或 Windows 的 IP 改變，需要同步修改相關設定
5. Windows 端若未啟動 server_variety.py，照片品種辨識分頁無法正常完成推論
```

---

## 十八、未來可改進方向

後續可以繼續改進：

```text
1. 將照片品種辨識模型也部署到 Raspberry Pi 或 Docker 中
2. 將兩個內層功能頁面改成與整合網站一致的正式風格
3. 將結果寫入資料庫，方便 App 或後台查詢
4. 加入系統健康檢查頁面，顯示三個服務是否正常啟動
5. 加入一鍵啟動 Windows 照片模型與 Raspberry Pi 網站的自動化流程
6. 將整合網站改成真正 API 整合，而不是 iframe 內嵌
7. 加入正式報表輸出功能，例如檢測紀錄、成熟度結果、品種結果與時間戳記
```

---

## 十九、開發團隊資訊

本系統由：

```text
長庚大學資訊工程學系專題團隊
```

開發建置。

團隊成員：

```text
林冠妤
陳怡禎
廖文歆
陳玟妤
```

指導教授：

```text
張哲維 教授
```

系統名稱：

```text
Pineapple Smart Recognition System
鳳梨智慧辨識系統
```

---

## 二十、今日完成總結

今日完成的重點是將原本分散的網頁操作流程整合成單一網站入口。

原本需要分別開啟：

```text
氣味成熟度辨識頁
照片品種辨識頁
整合或展示頁
```

現在改為：

```text
只需開啟：
http://192.168.0.152:8000
```

即可透過同一個網站分頁操作兩個功能。

此版本保留原本已成功運作的成熟度辨識與照片辨識架構，不直接破壞原有模型與環境，只在 Raspberry Pi 上新增整合入口網站，因此較穩定，也較適合比賽展示、專題報告與後續 App 對接。
